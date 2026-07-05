"""
Centralized configuration for Podcast Studio API Server.

All paths, limits, regexes, and constants are defined here as a single
source of truth. Environment variables override defaults; pipeline config
is used when available.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _check_pipeline() -> bool:
    """Detect whether the pipeline source directory is importable.

    Uses importlib.util.spec_from_file_location to check directly,
    avoiding conflicts with the web app's own utils module.
    """
    pipeline_src = os.environ.get(
        "PODCAST_PIPELINE_SRC", "/data/user/work/podcast_pipeline/src"
    )
    pipeline_utils = os.path.join(pipeline_src, "utils.py")
    if os.path.isfile(pipeline_utils):
        import sys
        if pipeline_src not in sys.path:
            sys.path.insert(0, pipeline_src)
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "pipeline_utils", pipeline_utils
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "get_config"):
                    return True
        except Exception:
            pass
    return False


@dataclass(frozen=True)
class Config:
    """Immutable application configuration.

    All fields have sensible defaults and can be overridden via
    environment variables or the pipeline's own config.
    """

    # ── Network ──────────────────────────────────────────────
    port: int = field(default_factory=lambda: int(os.environ.get("PORT", "8080")))
    host: str = "0.0.0.0"

    # ── Paths ────────────────────────────────────────────────
    web_root: str = field(default_factory=lambda: os.environ.get("PODCAST_WEB_ROOT", "/workspace"))
    upload_dir: str = field(default_factory=lambda: os.environ.get("PODCAST_UPLOAD_DIR", "/workspace/.uploads"))
    output_dir: str = field(default_factory=lambda: os.environ.get("PODCAST_OUTPUT_DIR", "/workspace/podcast-output"))
    pipeline_src: str = field(default_factory=lambda: os.environ.get("PODCAST_PIPELINE_SRC", "/data/user/work/podcast_pipeline/src"))

    # ── Limits ──────────────────────────────────────────────
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("PODCAST_MAX_UPLOAD_MB", "100")))
    max_filename_len: int = 255
    max_engine_name_len: int = 50
    max_episodes_limit: int = 1000
    max_form_field_len: int = 10  # for short fields like format

    # ── Rate Limiting ───────────────────────────────────────
    rate_limit_window: int = 60       # seconds
    rate_limit_max: int = 60          # requests per window per IP
    rate_limit_cleanup_threshold: int = 1000  # IP count to trigger cleanup

    # ── Job Manager ─────────────────────────────────────────
    job_max_count: int = 200
    job_max_logs: int = 500
    job_ttl_sec: int = 3600  # 1 hour

    # ── Health Check ────────────────────────────────────────
    health_cache_ttl: int = 30  # seconds

    # ── Pagination ──────────────────────────────────────────
    default_page_size: int = 50
    max_page_size: int = 200

    # ── Validation ──────────────────────────────────────────
    # Accepts 12-hex-char IDs (generate_id), legacy numeric timestamp IDs,
    # and mixed alphanumeric IDs. Rejects path-traversal chars (/, \, .).
    session_id_re: re.Pattern = field(default_factory=lambda: re.compile(r"^[a-zA-Z0-9_-]{8,32}$"))

    # ── Allowed file extensions ─────────────────────────────
    allowed_static_ext: frozenset = frozenset({
        ".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif",
        ".svg", ".ico", ".woff", ".woff2",
    })

    allowed_book_ext: frozenset = frozenset({
        ".txt", ".pdf", ".epub", ".docx", ".html", ".htm",
    })

    allowed_audio_ext: frozenset = frozenset({".wav", ".mp3"})

    allowed_export_formats: frozenset = frozenset({"wav", "mp3"})

    # ── Route map for clean URLs ─────────────────────────────
    route_map: dict = field(default_factory=lambda: {
        "/studio": "/studio.html",
        "/home": "/index.html",
        "/library": "/library.html",
        "/player": "/player.html",
        "/docs": "/docs.html",
    })

    # ── Sensitive params to redact in list views ────────────
    sensitive_params: frozenset = frozenset({"book_path", "session_output"})

    # ── Pipeline availability ───────────────────────────────
    has_pipeline: bool = field(default_factory=_check_pipeline)

    # ── Health check modules ─────────────────────────────────
    health_check_modules: tuple = (
        "noisereduce", "pedalboard", "feedgen",
        "mutagen", "langdetect", "markdown",
    )

    # ── Manifest field name contracts ─────────────────────────
    # Canonical field names used by the pipeline's podcast_manifest.json.
    # These constants serve as a single source of truth for the manifest
    # schema, preventing field-name mismatches between pipeline output
    # and API/frontend consumers.
    manifest_title_fields: tuple = ("title", "podcast_title")
    manifest_episodes_fields: tuple = ("episodes",)
    manifest_episode_duration_fields: tuple = ("duration_sec", "duration_min", "duration_seconds")
    manifest_episode_filesize_fields: tuple = ("file_size", "file_size_bytes", "file_size_mb")
    manifest_episode_title_fields: tuple = ("title", "name", "episode_title")
    manifest_episode_audiopath_fields: tuple = ("audio_path", "audio_file", "file_path")
    manifest_created_at_fields: tuple = ("created_at", "created", "timestamp")
    manifest_episode_format_fields: tuple = ("format", "audio_format")
    manifest_episode_samplerate_fields: tuple = ("sample_rate", "samplerate")
    manifest_episode_channels_fields: tuple = ("channels", "channel_count")

    # ── Error codes ──────────────────────────────────────────
    # Machine-readable error codes for i18n on the frontend.
    # Frontend maps these codes to localized messages via getErrorMessage().
    error_codes: dict = field(default_factory=lambda: {
        "PIPELINE_UNAVAILABLE": "Pipeline source not available. TTS engines cannot be listed.",
        "NO_FILE_UPLOADED": "No file uploaded",
        "EMPTY_FILENAME": "Empty filename",
        "UNSUPPORTED_FORMAT": "Unsupported file format",
        "FILENAME_TOO_LONG": "Filename too long",
        "INVALID_JOB_ID": "Invalid job ID",
        "JOB_NOT_FOUND": "Job not found",
        "INVALID_SESSION_ID": "Invalid session ID",
        "SESSION_NOT_FOUND": "Session not found",
        "RSS_NOT_FOUND": "RSS feed not found",
        "INVALID_FILENAME": "Invalid filename",
        "FILE_NOT_FOUND": "File not found",
        "RATE_LIMITED": "Rate limit exceeded",
    })


def load_config() -> Config:
    """Create a Config instance, merging pipeline config if available."""
    cfg = Config()

    # When pipeline source is available, use its output_dir and max_upload
    if cfg.has_pipeline:
        try:
            import importlib.util
            pipeline_utils = os.path.join(cfg.pipeline_src, "utils.py")
            spec = importlib.util.spec_from_file_location(
                "pipeline_utils", pipeline_utils
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                pipeline_cfg = mod.get_config()
                # Create a new Config with pipeline values (frozen dataclass)
                return Config(
                    output_dir=pipeline_cfg.output_dir,
                    max_upload_mb=pipeline_cfg.max_upload_size_mb,
                    has_pipeline=True,
                )
        except (ImportError, AttributeError, Exception):
            pass

    return cfg
