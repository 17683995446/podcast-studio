"""
Flask middleware for Podcast Studio API Server.

Provides:
  - Request logging
  - Rate limiting (IP-based, in-memory)
  - Security response headers
"""
from __future__ import annotations

import logging
import time
from typing import Any

from flask import Flask, Request, Response, request

from config import Config
from utils import api_error

logger = logging.getLogger(__name__)


def register_middleware(app: Flask, config: Config) -> None:
    """Register all middleware on the Flask app.

    Args:
        app: Flask application instance.
        config: Application configuration.
    """
    rate_limit_store: dict[str, list[float]] = {}

    # Store config in a mutable dict so tests can override values
    rl_config = {
        "window": config.rate_limit_window,
        "max": config.rate_limit_max,
        "cleanup_threshold": config.rate_limit_cleanup_threshold,
    }

    # Expose for tests (backward compatibility)
    app.extensions["rate_limit_store"] = rate_limit_store
    app.extensions["rate_limit_config"] = rl_config

    # ── Request Logging ─────────────────────────────────────
    @app.before_request
    def log_request():
        logger.debug(f"{request.method} {request.path} from {request.remote_addr}")

    # ── Rate Limiter ────────────────────────────────────────
    @app.before_request
    def rate_limit():
        if request.path.startswith("/podcast-output/") or request.path.startswith("/_shared"):
            return  # Don't rate-limit static assets
        ip = request.remote_addr or "unknown"
        now = time.time()
        # Read dynamically from app.extensions (allows test override)
        rl_cfg = app.extensions.get("rate_limit_config", {})
        store = app.extensions.get("rate_limit_store", {})
        window = rl_cfg["window"]
        max_req = rl_cfg["max"]

        if ip not in store:
            store[ip] = []
        store[ip] = [t for t in store[ip] if now - t < window]
        if len(store[ip]) >= max_req:
            return api_error("Rate limit exceeded. Please slow down.", 429)
        store[ip].append(now)

        # Periodically purge stale IPs
        if len(store) > rl_cfg["cleanup_threshold"]:
            stale = [k for k, v in store.items()
                     if not v or (now - v[-1]) > window]
            for k in stale:
                del store[k]

    # ── Security Headers ────────────────────────────────────
    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "media-src 'self'; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response
