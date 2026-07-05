"""
Flask REST API Server for Podcast Studio

This module serves as the application entry point. It uses the
``create_app()`` factory pattern with Flask Blueprints for modular
route organization and dependency injection for JobManager.

Endpoints:
  GET  /api/engines          — List all TTS engines
  GET  /api/health            — System health check
  POST /api/generate          — Start async podcast generation (returns job_id)
  GET  /api/jobs              — List all jobs
  GET  /api/jobs/<job_id>     — Get job status
  GET  /api/rss/<session_id>  — Download RSS feed
  GET  /api/sessions          — List all podcast sessions
  GET  /api/session/<id>      — Get session details

Usage:
    python3 api_server.py [--port 8080]
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from config import Config, load_config
from middleware import register_middleware
from routes.api import init_api
from routes.static import init_static_routes
from utils import api_error, api_success, generate_id

# ── Configuration ────────────────────────────────────────────────
cfg: Config = load_config()
logger = logging.getLogger(__name__)

# Backward-compatible module-level aliases (used by tests and routes)
PORT = cfg.port
WEB_ROOT = cfg.web_root
UPLOAD_DIR = cfg.upload_dir
OUTPUT_DIR = cfg.output_dir
_HAS_PIPELINE = cfg.has_pipeline
_ALLOWED_STATIC_EXT = cfg.allowed_static_ext
_SESSION_ID_RE = cfg.session_id_re
_RATE_LIMIT_WINDOW = cfg.rate_limit_window
_RATE_LIMIT_MAX = cfg.rate_limit_max


# ── Job Manager ──────────────────────────────────────────────────

class JobManager:
    """In-memory async job queue using threading."""

    # Class-level defaults (can be overridden per-instance via constructor)
    MAX_JOBS = 200
    MAX_LOGS_PER_JOB = 500
    JOB_TTL_SEC = 3600

    def __init__(self, max_jobs: int | None = None, max_logs: int | None = None,
                 job_ttl: int | None = None) -> None:
        self.MAX_JOBS = max_jobs if max_jobs is not None else JobManager.MAX_JOBS
        self.MAX_LOGS_PER_JOB = max_logs if max_logs is not None else JobManager.MAX_LOGS_PER_JOB
        self.JOB_TTL_SEC = job_ttl if job_ttl is not None else JobManager.JOB_TTL_SEC
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _cleanup_expired(self) -> None:
        """Remove completed/failed jobs older than JOB_TTL_SEC. Must hold lock."""
        now = time.time()
        expired = [
            jid for jid, j in self._jobs.items()
            if j["status"] in ("completed", "failed")
            and j.get("completed_at")
            and (now - j["completed_at"]) > type(self).JOB_TTL_SEC
        ]
        for jid in expired:
            del self._jobs[jid]
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired jobs")

    def create_job(self, job_type: str, params: dict) -> str:
        job_id = generate_id()
        with self._lock:
            self._cleanup_expired()
            max_jobs = type(self).MAX_JOBS
            if len(self._jobs) >= max_jobs:
                completed = [(jid, j) for jid, j in self._jobs.items()
                             if j["status"] in ("completed", "failed")]
                completed.sort(key=lambda x: x[1].get("completed_at", 0))
                for jid, _ in completed[:max(1, len(completed) - max_jobs // 2)]:
                    del self._jobs[jid]
            self._jobs[job_id] = {
                "id": job_id,
                "type": job_type,
                "status": "pending",
                "params": params,
                "result": None,
                "error": None,
                "progress": 0,
                "stage": "",
                "created_at": time.time(),
                "started_at": None,
                "completed_at": None,
                "logs": [],
            }
        return job_id

    def start_job(self, job_id: str, target_func, *args, **kwargs) -> str:
        def _wrapper():
            self.update_job(job_id, status="running", started_at=time.time())
            try:
                result = target_func(*args, **kwargs)
                self.update_job(job_id, status="completed", result=result,
                               progress=100, completed_at=time.time())
            except Exception as e:
                logger.error(f"Job {job_id} failed: {e}", exc_info=True)
                self.update_job(job_id, status="failed", error=str(e),
                               completed_at=time.time())
        thread = threading.Thread(target=_wrapper, daemon=True)
        thread.start()

    def update_job(self, job_id: str, **kwargs) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(kwargs)

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [dict(j) for j in self._jobs.values()]

    def add_log(self, job_id: str, message: str, level: str = "info") -> None:
        with self._lock:
            if job_id in self._jobs:
                logs = self._jobs[job_id]["logs"]
                cap = type(self).MAX_LOGS_PER_JOB
                if len(logs) < cap:
                    logs.append({
                        "time": time.strftime("%H:%M:%S"),
                        "level": level,
                        "message": message,
                    })


# Module-level singleton (backward compatibility for tests)
job_manager = JobManager()


# ── Application Factory ──────────────────────────────────────────

def create_app(config: Config | None = None, jm: JobManager | None = None) -> Flask:
    """Create and configure a Flask application instance.

    This is the standard Flask application factory pattern. It:
      1. Creates a Flask app with security settings
      2. Registers middleware (logging, rate limiting, security headers)
      3. Initializes API routes with dependency injection
      4. Registers static file serving routes
      5. Registers error handlers

    Args:
        config: Application configuration. Defaults to the module-level cfg.
        jm: JobManager instance. Defaults to the module-level job_manager.

    Returns:
        Configured Flask application instance.
    """
    if config is None:
        config = cfg
    if jm is None:
        jm = job_manager

    # Ensure directories exist
    os.makedirs(config.upload_dir, exist_ok=True)
    os.makedirs(config.output_dir, exist_ok=True)

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = config.max_upload_mb * 1024 * 1024

    # Register middleware
    register_middleware(app, config)

    # Initialize API routes with DI
    init_api(app, config, jm)

    # Initialize static file routes
    init_static_routes(app, config)

    # ── Error Handlers ──────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return api_error("Not found", 404)

    @app.errorhandler(413)
    def too_large(e):
        return api_error(
            f"File too large. Max upload size is {config.max_upload_mb}MB", 413
        )

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal error: {e}", exc_info=True)
        return api_error("Internal server error", 500)

    return app


# ── Rate Limit Store (backward compatibility for tests) ──────────
# These are populated by register_middleware at create_app() time.
# For backward compatibility, we also maintain module-level references
# that tests can access directly.
_rate_limit_store: dict[str, list[float]] = {}
_health_cache: dict = {"result": None, "timestamp": 0}


# ── Module-level app (for backward compatibility with tests) ────
# Tests import `api_server.app` directly, so we create it at import time.
# The rate_limit_store and rl_config are accessed by tests via app.extensions.
app = create_app()

# Sync module-level references for backward compatibility
_rate_limit_store = app.extensions.get("rate_limit_store", {})
_health_cache = app.extensions.get("health_cache", {"result": None, "timestamp": 0})
_RATE_LIMIT_MAX = cfg.rate_limit_max
_RATE_LIMIT_WINDOW = cfg.rate_limit_window


# ── Entry Point ──────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Podcast Studio API Server")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Kill any existing server on the port
    try:
        subprocess.run(["fuser", "-k", f"{args.port}/tcp"], capture_output=True)
        time.sleep(1)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"Port cleanup skipped: {e}")

    logger.info(f"Podcast Studio API Server starting on port {args.port}")
    logger.info(f"Open http://localhost:{args.port}/ in your browser")

    effective_debug = args.debug and args.host in ("127.0.0.1", "localhost")
    app.run(host=args.host, port=args.port, debug=effective_debug, threaded=True)


if __name__ == "__main__":
    main()
