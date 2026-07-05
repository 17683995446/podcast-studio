"""
Shared utility functions for Podcast Studio API Server.

Provides:
  - api_success() / api_error()  — unified response builders
  - paginate()                    — generic pagination helper
  - is_valid_id()                 — session/job ID format validation
  - parse_pagination_params()     — extract page/limit from Flask request args
  - sanitize_filename()           — prevent path traversal in filenames
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

from flask import jsonify

from config import Config


def api_success(data: dict | None = None, status: int = 200) -> tuple:
    """Build a successful JSON response.

    Args:
        data: Additional fields to include alongside ``success: True``.
        status: HTTP status code (default 200).

    Returns:
        (jsonify response, status_code) tuple.
    """
    payload = {"success": True}
    if data:
        payload.update(data)
    return jsonify(payload), status


def api_error(
    message: str | None = None,
    status: int = 400,
    error_code: str | None = None,
    config: Config | None = None,
) -> tuple:
    """Build an error JSON response.

    Args:
        message: Human-readable error message. If None, looked up from
            config.error_codes using error_code.
        status: HTTP status code (default 400).
        error_code: Machine-readable error code for frontend i18n.
        config: Config instance for error code lookup (optional).

    Returns:
        (jsonify response, status_code) tuple.
    """
    payload = {"success": False}

    if error_code:
        payload["error_code"] = error_code
        if message is None and config is not None:
            message = config.error_codes.get(error_code, error_code)

    if message is None:
        message = error_code or "Unknown error"

    payload["error"] = message
    return jsonify(payload), status


def paginate(
    items: list,
    page: int,
    limit: int,
) -> dict:
    """Slice a list into a page and return pagination metadata.

    Args:
        items: Full list of items (already sorted/filtered).
        page: 1-based page number.
        limit: Items per page.

    Returns:
        Dict with ``items``, ``count``, ``total``, ``page``, ``limit``.
    """
    total = len(items)
    start = (page - 1) * limit
    paginated = items[start:start + limit]
    return {
        "items": paginated,
        "count": len(paginated),
        "total": total,
        "page": page,
        "limit": limit,
    }


def parse_pagination_params(request, config: Config) -> tuple[int, int]:
    """Extract page/limit from Flask request.args with clamping.

    Args:
        request: Flask request object.
        config: Config instance for defaults and limits.

    Returns:
        (page, limit) tuple with safe values.
    """
    page = max(1, request.args.get("page", 1, type=int))
    limit = min(
        config.max_page_size,
        max(1, request.args.get("limit", config.default_page_size, type=int)),
    )
    return page, limit


def is_valid_id(value: str, config: Config) -> bool:
    """Check if a string is a valid session/job ID (12 hex chars).

    Args:
        value: The string to validate.
        config: Config instance containing the regex pattern.

    Returns:
        True if the value matches the ID format.
    """
    return bool(config.session_id_re.match(value))


def sanitize_filename(filename: str) -> str | None:
    """Return a safe filename or None if it contains path separators.

    Uses ``Path(filename).name`` to strip any directory components.
    If the original filename differs from the sanitized version,
    it means path traversal was attempted and None is returned.

    Args:
        filename: The raw filename from user input.

    Returns:
        Safe filename string, or None if traversal was detected.
    """
    safe = Path(filename).name
    if safe != filename:
        return None
    return safe


def generate_id() -> str:
    """Generate a 12-character hex ID from uuid4."""
    import uuid
    return uuid.uuid4().hex[:12]


def redact_params(params: dict, sensitive: frozenset) -> dict:
    """Remove sensitive keys from a params dict.

    Args:
        params: The original params dict.
        sensitive: Set of key names to remove.

    Returns:
        A new dict with sensitive keys excluded.
    """
    return {k: v for k, v in params.items() if k not in sensitive}


def extract_manifest_field(
    data: dict,
    field_names: tuple,
    default=None,
) -> Any:
    """Extract a field from a manifest dict using a priority-ordered list of names.

    This compatibility layer tries each field name in order, returning the
    first non-None value found. This allows the system to handle manifest
    schema changes gracefully without code modifications.

    Args:
        data: The manifest dict (or episode dict) to extract from.
        field_names: Tuple of field names to try, in priority order.
        default: Value to return if no field is found.

    Returns:
        The first matching field value, or ``default`` if none found.

    Examples:
        >>> extract_manifest_field({"title": "Hello"}, Config().manifest_title_fields)
        'Hello'
        >>> extract_manifest_field({"podcast_title": "World"}, Config().manifest_title_fields)
        'World'
        >>> extract_manifest_field({}, Config().manifest_title_fields, "fallback")
        'fallback'
    """
    if not isinstance(data, dict):
        return default
    for name in field_names:
        val = data.get(name)
        if val is not None:
            return val
    return default
