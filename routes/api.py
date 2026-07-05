"""
API Blueprint for Podcast Studio.

All REST API endpoints are registered on this blueprint:
  GET  /api/engines          — List all TTS engines
  GET  /api/health            — System health check (cached)
  POST /api/generate          — Start async podcast generation
  GET  /api/jobs              — List all jobs (paginated)
  GET  /api/jobs/<job_id>     — Get job status
  GET  /api/sessions          — List all sessions (paginated)
  GET  /api/session/<id>      — Get session details
  GET  /api/rss/<session_id>  — Download RSS feed
  GET  /api/download/<id>/<file> — Download episode audio
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    Flask,
    Response,
    jsonify,
    request,
    send_file,
)

from config import Config
from utils import (
    api_error,
    api_success,
    extract_manifest_field,
    generate_id,
    is_valid_id,
    paginate,
    parse_pagination_params,
    redact_params,
)

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__)


def init_api(app: Flask, config: Config, job_manager) -> None:
    """Initialize the API blueprint with app-specific dependencies.

    Args:
        app: Flask application instance.
        config: Application configuration.
        job_manager: JobManager instance for async job tracking.
    """
    app.extensions["job_manager"] = job_manager
    app.extensions["health_cache"] = {"result": None, "timestamp": 0}

    @app.route("/favicon.ico")
    def favicon():
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        svg += '<circle cx="16" cy="16" r="14" fill="#e85d3a"/>'
        svg += '<circle cx="16" cy="16" r="6" fill="#fff"/></svg>'
        return Response(svg.encode("utf-8"), content_type="image/svg+xml")

    @app.route("/api/engines")
    def api_engines():
        if not config.has_pipeline:
            return api_error(
                status=503, error_code="PIPELINE_UNAVAILABLE", config=config
            )
        import importlib.util
        tts_path = Path(config.pipeline_src) / "enhanced_tts.py"
        spec = importlib.util.spec_from_file_location("pipeline_enhanced_tts", tts_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mgr = mod.EnhancedTTSManager()
        engines = mgr.list_engines()
        return jsonify({
            "success": True,
            "active_engine": mgr.active_engine_name,
            "engines": [
                {
                    "name": e.name,
                    "available": e.available,
                    "quality_score": e.quality_score,
                    "is_offline": e.is_offline,
                    "supports_chinese": e.supports_chinese,
                    "voice_count": e.voice_count,
                    "description": e.description,
                }
                for e in sorted(engines, key=lambda x: -x.quality_score)
            ]
        })

    @app.route("/api/health")
    def api_health():
        health_cache = app.extensions["health_cache"]
        now = time.time()
        # Support ?force=true to bypass cache (for manual refresh)
        force_refresh = request.args.get("force", "").lower() in ("true", "1", "yes")
        if not force_refresh and health_cache["result"] and (now - health_cache["timestamp"]) < config.health_cache_ttl:
            cached = health_cache["result"].copy()
            cached["cached"] = True
            return jsonify(cached)

        checks = {
            "edge_tts": False,
            "ffmpeg": False,
            "noisereduce": False,
            "pedalboard": False,
            "feedgen": False,
            "mutagen": False,
            "langdetect": False,
            "markdown": False,
        }
        try:
            import edge_tts; checks["edge_tts"] = True
        except ImportError:
            pass
        try:
            checks["ffmpeg"] = subprocess.run(
                ["which", "ffmpeg"], capture_output=True, timeout=5
            ).returncode == 0
        except Exception as e:
            logger.debug(f"FFmpeg check failed: {e}")
        for mod in config.health_check_modules:
            try:
                importlib.import_module(mod)
                checks[mod] = True
            except ImportError:
                pass

        all_ok = all(checks.values())
        result = {
            "success": True,
            "status": "healthy" if all_ok else "degraded",
            "checks": checks,
            "output_dir": config.output_dir,
            "upload_dir": config.upload_dir,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        health_cache["result"] = result
        health_cache["timestamp"] = now
        return jsonify(result)

    @app.route("/api/generate", methods=["POST"])
    def api_generate():
        if "file" not in request.files:
            return api_error(error_code="NO_FILE_UPLOADED", config=config)

        file = request.files["file"]
        if not file.filename:
            return api_error(error_code="EMPTY_FILENAME", config=config)

        if config.has_pipeline:
            import importlib.util
            br_path = Path(config.pipeline_src) / "book_reader.py"
            br_spec = importlib.util.spec_from_file_location("pipeline_book_reader", br_path)
            br_mod = importlib.util.module_from_spec(br_spec)
            br_spec.loader.exec_module(br_mod)
            allowed_ext = br_mod.BookFormatRegistry.supported_extensions()
        else:
            allowed_ext = config.allowed_book_ext
        ext = Path(file.filename).suffix.lower()
        if ext not in allowed_ext:
            return api_error(
                f"Unsupported file format: {ext}. Allowed: {', '.join(sorted(allowed_ext))}",
                error_code="UNSUPPORTED_FORMAT", config=config
            )

        session_id = generate_id()

        safe_name = Path(file.filename).name
        if len(safe_name) > config.max_filename_len:
            return api_error(error_code="FILENAME_TOO_LONG", config=config)
        book_path = os.path.join(config.upload_dir, f"{session_id}_{safe_name}")
        file.save(book_path)
        file_size = os.path.getsize(book_path)

        preferred_engine = request.form.get("engine", "")[:config.max_engine_name_len]
        try:
            max_episodes = int(request.form.get("maxEpisodes", "0"))
        except (ValueError, TypeError):
            max_episodes = 0
        max_episodes = max(0, min(max_episodes, config.max_episodes_limit))
        export_format = request.form.get("format", "wav")[:config.max_form_field_len]
        if export_format not in config.allowed_export_formats:
            export_format = "wav"
        enable_eq = request.form.get("enableEq", "false") == "true"
        script_only = request.form.get("scriptOnly", "false") == "true"
        enable_nr = request.form.get("enableNoiseReduction", "true") == "true"
        enable_pb = request.form.get("enablePedalboard", "true") == "true"
        generate_rss = request.form.get("generateRss", "true") == "true"
        embed_id3 = request.form.get("embedId3", "true") == "true"

        session_output = os.path.join(config.output_dir, f"session_{session_id}")

        job_id = job_manager.create_job("podcast_generation", {
            "book_path": book_path,
            "filename": safe_name,
            "file_size": file_size,
            "session_output": session_output,
            "session_id": session_id,
            "engine": preferred_engine or "auto",
            "max_episodes": max_episodes,
            "format": export_format,
            "enable_eq": enable_eq,
            "script_only": script_only,
            "enable_noise_reduction": enable_nr,
            "enable_pedalboard": enable_pb,
            "generate_rss": generate_rss,
            "embed_id3": embed_id3,
        })

        job_manager.start_job(
            job_id, _run_pipeline_async,
            job_id, book_path, session_output, max_episodes,
            preferred_engine, enable_eq, export_format, script_only,
            enable_nr, enable_pb, generate_rss, embed_id3,
        )

        logger.info(f"Job started: {job_id} for {safe_name}")

        return api_success({
            "job_id": job_id,
            "session_id": session_id,
            "status": "pending",
            "message": f"Generation started for {safe_name}",
        })

    @app.route("/api/jobs")
    def api_jobs():
        page, limit = parse_pagination_params(request, config)
        jobs = job_manager.list_jobs()
        jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
        for j in jobs:
            if j.get("result") and isinstance(j["result"], dict):
                j["result_summary"] = {
                    "success": j["result"].get("success", False),
                    "total_time_sec": j["result"].get("total_time_sec", 0),
                    "stages": list(j["result"].get("stages", {}).keys()),
                }
                j.pop("result", None)
            if j.get("params"):
                j["params"] = redact_params(j["params"], config.sensitive_params)
        page_info = paginate(jobs, page, limit)
        return api_success({
            "jobs": page_info["items"],
            "count": page_info["count"],
            "total": page_info["total"],
            "page": page_info["page"],
            "limit": page_info["limit"],
        })

    @app.route("/api/jobs/<job_id>")
    def api_job_detail(job_id: str):
        if not is_valid_id(job_id, config):
            return api_error(error_code="INVALID_JOB_ID", config=config)
        job = job_manager.get_job(job_id)
        if not job:
            return api_error(status=404, error_code="JOB_NOT_FOUND", config=config)
        return api_success({"job": job})

    @app.route("/api/sessions")
    def api_sessions():
        page, limit = parse_pagination_params(request, config)
        sessions = []
        output_path = Path(config.output_dir)
        if output_path.is_dir():
            for d in output_path.iterdir():
                if d.is_dir() and d.name.startswith("session_"):
                    session_id = d.name.replace("session_", "")
                    info = _get_session_info(d, config)
                    if info:
                        info["session_id"] = session_id
                        info["dir_name"] = d.name
                        sessions.append(info)
        sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        page_info = paginate(sessions, page, limit)
        return api_success({
            "sessions": page_info["items"],
            "count": page_info["count"],
            "total": page_info["total"],
            "page": page_info["page"],
            "limit": page_info["limit"],
        })

    @app.route("/api/session/<session_id>")
    def api_session_detail(session_id: str):
        if not is_valid_id(session_id, config):
            return api_error(error_code="INVALID_SESSION_ID", config=config)

        session_dir = Path(config.output_dir) / f"session_{session_id}"
        if not session_dir.is_dir():
            return api_error(status=404, error_code="SESSION_NOT_FOUND", config=config)

        manifest_path = session_dir / "podcast_package" / "podcast_manifest.json"
        rss_path = session_dir / "podcast_package" / "podcast.rss.xml"
        script_path = session_dir / "podcast_script.html"
        episodes_dir = session_dir / "episodes"

        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read manifest for session {session_id}: {e}")

        episode_files = []
        if episodes_dir.exists():
            for f in sorted(episodes_dir.iterdir()):
                if f.is_file() and f.suffix in (".wav", ".mp3"):
                    # Skip temp files and 0-byte files (failed TTS outputs)
                    if f.name.startswith("_tmp_") or f.stat().st_size == 0:
                        continue
                    episode_files.append({
                        "name": f.name,
                        "path": str(f),
                        "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
                        "url": f"/api/download/{session_id}/{f.name}",
                    })

        return jsonify({
            "success": True,
            "session_id": session_id,
            "title": extract_manifest_field(
                manifest, config.manifest_title_fields, default=session_id
            ),
            "manifest": manifest,
            "episodes": episode_files,
            "has_rss": rss_path.exists(),
            "rss_url": f"/api/rss/{session_id}" if rss_path.exists() else None,
            "script_url": f"/podcast-output/session_{session_id}/podcast_script.html"
                          if script_path.exists() else None,
        })

    @app.route("/api/rss/<session_id>")
    def api_rss(session_id: str):
        if not is_valid_id(session_id, config):
            return api_error(error_code="INVALID_SESSION_ID", config=config)
        rss_path = Path(config.output_dir) / f"session_{session_id}" / "podcast_package" / "podcast.rss.xml"
        if not rss_path.exists():
            return api_error(status=404, error_code="RSS_NOT_FOUND", config=config)
        return send_file(str(rss_path), as_attachment=True,
                        download_name="podcast.rss.xml", mimetype="application/rss+xml")

    @app.route("/api/download/<session_id>/<filename>")
    def api_download(session_id: str, filename: str):
        if not is_valid_id(session_id, config):
            return api_error(error_code="INVALID_SESSION_ID", config=config)
        safe_filename = Path(filename).name
        if safe_filename != filename:
            return api_error(error_code="INVALID_FILENAME", config=config)
        episodes_dir = Path(config.output_dir) / f"session_{session_id}" / "episodes"
        file_path = episodes_dir / safe_filename
        if not file_path.exists():
            return api_error(status=404, error_code="FILE_NOT_FOUND", config=config)
        return send_file(str(file_path), as_attachment=True, download_name=safe_filename)


def _safe_remove_file(path: str, job_manager) -> None:
    """Remove a file if it exists, logging any errors."""
    try:
        if path and os.path.isfile(path):
            os.remove(path)
            job_manager.add_log("cleanup", f"Removed: {Path(path).name}")
    except OSError as e:
        logger.warning(f"Failed to remove {path}: {e}")


def _run_pipeline_async(job_id, book_path, output_dir, max_episodes,
                        preferred_engine, enable_eq, export_format,
                        script_only, enable_noise_reduction,
                        enable_pedalboard, generate_rss, embed_id3,
                        job_manager=None, config=None):
    """Run the book-to-podcast pipeline in a background thread.

    This function is called by JobManager.start_job. It uses the
    job_manager to log progress and cleans up the uploaded file on failure.
    """
    if job_manager is None:
        raise RuntimeError("job_manager is required")
    if config is None:
        raise RuntimeError("config is required")

    if not config.has_pipeline:
        job_manager.add_log(job_id, "Pipeline source not available", "error")
        _safe_remove_file(book_path, job_manager)
        raise RuntimeError("Pipeline source code is not available")

    import importlib.util
    btp_path = Path(config.pipeline_src) / "book_to_podcast.py"
    btp_spec = importlib.util.spec_from_file_location("pipeline_book_to_podcast", btp_path)
    btp_mod = importlib.util.module_from_spec(btp_spec)
    btp_spec.loader.exec_module(btp_mod)
    run_book_pipeline = btp_mod.run_book_pipeline

    job_manager.add_log(job_id, f"Starting pipeline: {Path(book_path).name}")
    job_manager.update_job(job_id, progress=5, stage="reading_book")

    try:
        summary = run_book_pipeline(
            book_path=book_path,
            output_dir=output_dir,
            max_episodes=max_episodes,
            preferred_engine=preferred_engine,
            enable_eq=enable_eq,
            export_format=export_format,
            script_only=script_only,
            enable_noise_reduction=enable_noise_reduction,
            enable_pedalboard=enable_pedalboard,
            generate_rss=generate_rss,
            embed_id3=embed_id3,
        )
    except Exception:
        _safe_remove_file(book_path, job_manager)
        raise

    job_manager.add_log(job_id, "Pipeline complete", "success")
    return summary


def _get_session_info(session_dir: Path, config: Config | None = None) -> dict | None:
    """Extract session metadata from a session directory.

    Returns None for incomplete sessions (no manifest and no episodes),
    so they are filtered out from session listings.

    Uses :func:`extract_manifest_field` with field-name constants from
    :class:`Config` to handle manifest schema changes gracefully.
    """
    manifest_path = session_dir / "podcast_package" / "podcast_manifest.json"
    rss_path = session_dir / "podcast_package" / "podcast.rss.xml"
    script_path = session_dir / "podcast_script.html"
    episodes_dir = session_dir / "episodes"

    # Use Config defaults if not provided (for backward compatibility)
    if config is None:
        config = Config()

    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read manifest for {session_dir.name}: {e}")

    # Collect actual episode files on disk (exclude temp files and 0-byte files)
    episode_files = []
    if episodes_dir.exists():
        episode_files = [
            f for f in episodes_dir.iterdir()
            if f.is_file() and f.suffix in (".wav", ".mp3")
            and not f.name.startswith("_tmp_")
            and f.stat().st_size > 0
        ]

    # Filter out incomplete sessions: must have at least a manifest or episodes
    has_episodes = bool(episode_files)
    has_manifest = bool(manifest)

    if not has_episodes and not has_manifest:
        return None  # Incomplete session, skip

    # Extract episode metadata from manifest using compatibility layer
    manifest_episodes = extract_manifest_field(
        manifest, config.manifest_episodes_fields, default=[]
    )
    if not isinstance(manifest_episodes, list):
        manifest_episodes = []

    # Episode count: prefer manifest episodes array, fall back to file count
    episode_count = len(manifest_episodes)
    if episode_count == 0 and has_episodes:
        episode_count = len(episode_files)

    # Total duration: sum duration from manifest episodes, convert to minutes
    total_duration_sec = 0
    for ep in manifest_episodes:
        if isinstance(ep, dict):
            dur = extract_manifest_field(
                ep, config.manifest_episode_duration_fields, default=0
            )
            # If duration_min is found, convert to seconds; else assume seconds
            total_duration_sec += dur if dur else 0
    duration_min = round(total_duration_sec / 60, 1)

    # Total file size: sum from manifest, fall back to actual files
    total_bytes = 0
    for ep in manifest_episodes:
        if isinstance(ep, dict):
            size = extract_manifest_field(
                ep, config.manifest_episode_filesize_fields, default=0
            )
            # Handle file_size_mb (convert back to bytes) vs file_size (bytes)
            if size and size < 100000:  # Likely MB
                total_bytes += size * 1024 * 1024
            else:
                total_bytes += size if size else 0
    if total_bytes == 0 and has_episodes:
        total_bytes = sum(f.stat().st_size for f in episode_files)

    # Extract title and created_at using compatibility layer
    title = extract_manifest_field(
        manifest, config.manifest_title_fields, default=session_dir.name
    )
    created_at = extract_manifest_field(
        manifest, config.manifest_created_at_fields, default=""
    )

    return {
        "title": title,
        "episodes": episode_count,
        "duration_min": duration_min,
        "file_size_mb": round(total_bytes / 1024 / 1024, 2),
        "has_rss": rss_path.exists(),
        "has_script": script_path.exists(),
        "created_at": created_at,
    }
