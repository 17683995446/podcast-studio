"""
Static file serving Blueprint for Podcast Studio.

Serves:
  - HTML/CSS/JS/static assets from web root (whitelist-only)
  - Podcast output files (with path traversal protection)
  - Clean URL routing (e.g., /studio → /studio.html)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    Flask,
    request,
    send_from_directory,
)

from config import Config
from utils import api_error

logger = logging.getLogger(__name__)

bp = Blueprint("static_files", __name__)


def init_static_routes(app: Flask, config: Config) -> None:
    """Register static file serving routes on the app.

    Args:
        app: Flask application instance.
        config: Application configuration.
    """

    @app.route("/<path:filename>")
    def serve_static(filename: str) -> Any:
        """Serve static files from web root — whitelist only known extensions."""
        # Check clean URL mapping
        mapped = config.route_map.get(f"/{filename}")
        if mapped:
            filename = mapped.lstrip("/")

        ext = Path(filename).suffix.lower()
        if ext not in config.allowed_static_ext:
            return api_error("Forbidden", 403)

        file_path = Path(config.web_root) / filename
        if file_path.exists() and file_path.is_file():
            return send_from_directory(config.web_root, filename)
        return api_error("Not found", 404)

    @app.route("/")
    def serve_index() -> Any:
        """Serve the index page (knowledge card feed) as default."""
        return send_from_directory(config.web_root, "index.html")

    @app.route("/podcast-output/<path:filename>")
    def serve_podcast_output(filename: str) -> Any:
        """Serve files from the podcast output directory.

        Security: resolves the path and verifies it stays within
        OUTPUT_DIR to prevent directory traversal attacks.
        """
        target = (Path(config.output_dir) / filename).resolve()
        try:
            target.relative_to(Path(config.output_dir).resolve())
        except ValueError:
            return api_error("Forbidden", 403)
        if not target.is_file():
            return api_error("Not found", 404)
        return send_from_directory(config.output_dir, filename)
