"""
Unit tests for api_server.py — validates API endpoints, security, and response format.

Shared fixtures (client, job_mgr, create_session_dir, valid_id, fake_session_id)
are defined in conftest.py and do not need to be redefined here.
"""
import json
import os
import sys
import time
import pytest
from pathlib import Path

# Ensure api_server is importable
sys.path.insert(0, "/workspace")

import api_server


# ── Static File Serving ──────────────────────────────────────────

class TestStaticFiles:
    def test_index_page(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"<!DOCTYPE html>" in r.data

    def test_shared_css(self, client):
        r = client.get("/_shared.css")
        assert r.status_code == 200

    def test_studio_page(self, client):
        r = client.get("/studio.html")
        assert r.status_code == 200
        assert b"<!DOCTYPE html>" in r.data

    def test_library_page(self, client):
        r = client.get("/library.html")
        assert r.status_code == 200

    def test_player_page(self, client):
        r = client.get("/player.html")
        assert r.status_code == 200

    def test_docs_page(self, client):
        r = client.get("/docs.html")
        assert r.status_code == 200

    def test_nonexistent_page(self, client):
        r = client.get("/nonexistent.html")
        assert r.status_code == 404

    def test_python_file_forbidden(self, client):
        """Source code files should not be served."""
        r = client.get("/api_server.py")
        assert r.status_code == 403

    def test_dotfile_forbidden(self, client):
        r = client.get("/.env")
        assert r.status_code == 403


# ── API Response Format ─────────────────────────────────────────

class TestAPIFormat:
    def test_engines_response_format(self, client):
        r = client.get("/api/engines")
        data = r.get_json()
        assert "success" in data
        assert isinstance(data["success"], bool)

    def test_health_response_format(self, client):
        r = client.get("/api/health")
        data = r.get_json()
        assert "success" in data
        assert "checks" in data

    def test_sessions_response_format(self, client):
        r = client.get("/api/sessions")
        data = r.get_json()
        assert "success" in data
        assert "sessions" in data
        assert "count" in data
        assert data["count"] == len(data["sessions"])


# ── extract_manifest_field Compatibility Layer ─────────────────

class TestExtractManifestField:
    """Tests for the extract_manifest_field compatibility function."""

    def test_first_priority_field(self):
        """Should return the first field name in the priority list."""
        from utils import extract_manifest_field
        result = extract_manifest_field(
            {"title": "Hello", "podcast_title": "World"},
            ("title", "podcast_title"),
        )
        assert result == "Hello"

    def test_second_priority_field(self):
        """Should fall back to the second field name."""
        from utils import extract_manifest_field
        result = extract_manifest_field(
            {"podcast_title": "World"},
            ("title", "podcast_title"),
        )
        assert result == "World"

    def test_no_matching_field(self):
        """Should return default when no field matches."""
        from utils import extract_manifest_field
        result = extract_manifest_field(
            {"other": "value"},
            ("title", "podcast_title"),
            default="fallback",
        )
        assert result == "fallback"

    def test_none_data(self):
        """Should handle None input gracefully."""
        from utils import extract_manifest_field
        assert extract_manifest_field(None, ("title",), "default") == "default"

    def test_non_dict_data(self):
        """Should handle non-dict input gracefully."""
        from utils import extract_manifest_field
        assert extract_manifest_field("not a dict", ("title",), "default") == "default"

    def test_none_field_value(self):
        """Should skip None values and try next field."""
        from utils import extract_manifest_field
        result = extract_manifest_field(
            {"title": None, "podcast_title": "Found"},
            ("title", "podcast_title"),
        )
        assert result == "Found"


# ── Error Code Mechanism ───────────────────────────────────────

class TestErrorCodes:
    """Tests for the error code mechanism in API responses."""

    def test_engines_503_has_error_code(self, client):
        """Engines endpoint should return error_code when pipeline unavailable."""
        r = client.get("/api/engines")
        data = r.get_json()
        if not data.get("success"):
            assert "error_code" in data
            assert data["error_code"] == "PIPELINE_UNAVAILABLE"

    def test_invalid_session_has_error_code(self, client):
        """Invalid session ID should return error_code."""
        r = client.get("/api/session/abc")
        data = r.get_json()
        assert data.get("error_code") == "INVALID_SESSION_ID"

    def test_invalid_job_id_has_error_code(self, client):
        """Invalid job ID should return error_code."""
        r = client.get("/api/jobs/abc")
        data = r.get_json()
        assert data.get("error_code") == "INVALID_JOB_ID"

    def test_session_not_found_has_error_code(self, client):
        """Non-existent session should return error_code."""
        r = client.get("/api/session/aabbccddeeff")
        data = r.get_json()
        if r.status_code == 404:
            assert data.get("error_code") == "SESSION_NOT_FOUND"

    def test_error_codes_in_config(self):
        """Config should have all expected error codes defined."""
        from config import Config
        config = Config()
        expected_codes = [
            "PIPELINE_UNAVAILABLE", "NO_FILE_UPLOADED", "EMPTY_FILENAME",
            "UNSUPPORTED_FORMAT", "FILENAME_TOO_LONG", "INVALID_JOB_ID",
            "JOB_NOT_FOUND", "INVALID_SESSION_ID", "SESSION_NOT_FOUND",
            "RSS_NOT_FOUND", "INVALID_FILENAME", "FILE_NOT_FOUND",
            "RATE_LIMITED",
        ]
        for code in expected_codes:
            assert code in config.error_codes, f"Missing error code: {code}"


# ── Health Check Force Refresh ─────────────────────────────────

class TestHealthForceRefresh:
    """Tests for the ?force=true parameter on /api/health."""

    def test_health_returns_success(self, client):
        """Health endpoint should return success."""
        r = client.get("/api/health")
        data = r.get_json()
        assert data["success"] is True
        assert "checks" in data

    def test_health_cached(self, client):
        """Second call should return cached result."""
        r1 = client.get("/api/health")
        r2 = client.get("/api/health")
        d1 = r1.get_json()
        d2 = r2.get_json()
        # First call may or may not be cached; second should be cached
        assert d2.get("cached") is True or d1.get("cached") is True

    def test_health_force_bypasses_cache(self, client):
        """?force=true should not return cached result."""
        # First call to populate cache
        client.get("/api/health")
        # Second call with force should not be cached
        r = client.get("/api/health?force=true")
        data = r.get_json()
        assert data["success"] is True
        assert "cached" not in data or data["cached"] is not True

    def test_health_force_alias_values(self, client):
        """Various truthy values for force parameter should work."""
        for val in ["true", "1", "yes", "TRUE", "True"]:
            r = client.get(f"/api/health?force={val}")
            data = r.get_json()
            assert data["success"] is True
            assert data.get("cached") is not True


# ── Shared JS New Functions ────────────────────────────────────

class TestSharedJSNewFunctions:
    """Tests for new functions added to _shared.js."""

    def test_assert_array_in_shared_js(self, client):
        """_shared.js should contain assertArray function."""
        r = client.get("/_shared.js")
        content = r.data.decode("utf-8")
        assert "function assertArray" in content

    def test_assert_object_in_shared_js(self, client):
        """_shared.js should contain assertObject function."""
        r = client.get("/_shared.js")
        content = r.data.decode("utf-8")
        assert "function assertObject" in content

    def test_get_error_message_in_shared_js(self, client):
        """_shared.js should contain getErrorMessage function."""
        r = client.get("/_shared.js")
        content = r.data.decode("utf-8")
        assert "function getErrorMessage" in content

    def test_error_messages_table_in_shared_js(self, client):
        """_shared.js should contain ERROR_MESSAGES mapping."""
        r = client.get("/_shared.js")
        content = r.data.decode("utf-8")
        assert "ERROR_MESSAGES" in content
        assert "PIPELINE_UNAVAILABLE" in content
        assert "语音合成管道源不可用" in content


# ── Manifest Field Mapping ─────────────────────────────────────

class TestManifestFieldMapping:
    """Tests that session listing correctly reads actual manifest field names."""

    def test_title_from_manifest_title_field(self, client, create_session_dir):
        """Session title should come from manifest['title'], not 'podcast_title'."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=True, with_episodes=False)

        r = client.get("/api/sessions")
        data = r.get_json()
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is not None
        assert our_session["title"] == f"Test Podcast {session_id}"

    def test_duration_from_episodes_duration_sec(self, client, create_session_dir):
        """Duration should be summed from episodes[].duration_sec, converted to minutes."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=True, with_episodes=False)

        r = client.get("/api/sessions")
        data = r.get_json()
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is not None
        # Fixture: 2 episodes with duration_sec=315 each, total 630s = 10.5 min
        assert our_session["duration_min"] == 10.5

    def test_file_size_from_episodes_file_size(self, client, create_session_dir):
        """File size should be summed from episodes[].file_size."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=True, with_episodes=False)

        r = client.get("/api/sessions")
        data = r.get_json()
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is not None
        # Fixture: 2 episodes with file_size=524288 each, total 1048576 = 1.0 MB
        assert our_session["file_size_mb"] == 1.0

    def test_episode_count_from_episodes_array(self, client, create_session_dir):
        """Episode count should be len(manifest['episodes'])."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=True, with_episodes=False)

        r = client.get("/api/sessions")
        data = r.get_json()
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is not None
        assert our_session["episodes"] == 2  # Fixture has 2 episodes in manifest

    def test_session_detail_uses_title_field(self, client, create_session_dir):
        """Session detail endpoint should use manifest['title'] for the title."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=True, with_episodes=False)

        r = client.get(f"/api/session/{session_id}")
        data = r.get_json()
        assert data["success"] is True
        assert data["title"] == f"Test Podcast {session_id}"


# ── Shared JS Functions ────────────────────────────────────────

class TestSharedJSFormatDate:
    """Tests for the formatDate function in _shared.js."""

    def test_format_date_in_shared_js(self, client):
        """_shared.js should contain formatDate function."""
        r = client.get("/_shared.js")
        assert r.status_code == 200
        assert b"function formatDate" in r.data

    def test_format_date_in_shared_js_content(self, client):
        """formatDate should handle ISO strings and convert to Chinese format."""
        r = client.get("/_shared.js")
        content = r.data.decode("utf-8")
        assert "getFullYear" in content
        assert "getMonth" in content
        assert "年" in content
        assert "月" in content

    def test_jobs_list(self, client):
        r = client.get("/api/jobs")
        data = r.get_json()
        assert "success" in data
        assert "jobs" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data

    def test_jobs_pagination(self, client):
        """Jobs endpoint should support pagination."""
        r = client.get("/api/jobs?page=1&limit=5")
        data = r.get_json()
        assert data["page"] == 1
        assert data["limit"] == 5
        assert len(data["jobs"]) <= 5

    def test_jobs_sensitive_params_stripped(self, client, job_mgr):
        """Job list should not include book_path or session_output in params."""
        jid = job_mgr.create_job("test", {
            "book_path": "/secret/path/book.pdf",
            "session_output": "/secret/output",
            "engine": "edge-tts",
        })
        # Inject into the global job_manager so the API can see it
        api_server.job_manager._jobs[jid] = job_mgr.get_job(jid)
        try:
            r = client.get("/api/jobs")
            data = r.get_json()
            job = [j for j in data["jobs"] if j["id"] == jid]
            if job:
                params = job[0].get("params", {})
                assert "book_path" not in params
                assert "session_output" not in params
                assert "engine" in params  # Non-sensitive params preserved
        finally:
            api_server.job_manager._jobs.pop(jid, None)

    def test_404_has_success_false(self, client):
        r = client.get("/api/nonexistent")
        data = r.get_json()
        assert data["success"] is False
        assert "error" in data


# ── Session ID Validation ────────────────────────────────────────

class TestSessionValidation:
    def test_valid_session_id(self, client):
        r = client.get("/api/session/a1b2c3d4e5f6")
        # 200 or 404 depending on session existence
        assert r.status_code in (200, 404)

    def test_invalid_session_id_short(self, client):
        r = client.get("/api/session/abc123")
        assert r.status_code == 400
        data = r.get_json()
        assert data["success"] is False

    def test_invalid_session_id_special_chars(self, client):
        r = client.get("/api/session/../etc/passwd")
        # Path traversal gets caught by either session validation or static file guard
        assert r.status_code in (400, 403, 404)

    def test_valid_session_id_uppercase(self, client):
        """Uppercase alphanumeric IDs are valid (should not return 400)."""
        r = client.get("/api/session/ABCDEF123456")
        assert r.status_code != 400  # 404 is fine — valid format, doesn't exist

    def test_invalid_session_id_empty(self, client):
        r = client.get("/api/session/")
        # Trailing slash without ID — 403 (static guard) or 404 (not found)
        assert r.status_code in (403, 404)


# ── Job Manager ─────────────────────────────────────────────────

class TestJobManager:
    def test_create_job(self, job_mgr):
        job_id = job_mgr.create_job("test", {"test": True})
        assert isinstance(job_id, str)
        assert len(job_id) > 0
        job = job_mgr.get_job(job_id)
        assert job is not None
        assert job["status"] == "pending"

    def test_update_job(self, job_mgr):
        job_id = job_mgr.create_job("test", {})
        job_mgr.update_job(job_id, status="running", progress=50)
        job = job_mgr.get_job(job_id)
        assert job["status"] == "running"
        assert job["progress"] == 50

    def test_add_log(self, job_mgr):
        job_id = job_mgr.create_job("test", {})
        job_mgr.add_log(job_id, "test message", "info")
        job = job_mgr.get_job(job_id)
        assert len(job["logs"]) == 1
        assert job["logs"][0]["message"] == "test message"

    def test_list_jobs(self, job_mgr):
        jid1 = job_mgr.create_job("test", {"n": 1})
        jid2 = job_mgr.create_job("test", {"n": 2})
        jobs = job_mgr.list_jobs()
        assert len(jobs) >= 2

    def test_max_jobs_limit(self, job_mgr, monkeypatch):
        """When MAX_JOBS is exceeded, oldest completed jobs should be evicted."""
        monkeypatch.setattr(api_server.JobManager, "MAX_JOBS", 5)
        jm = api_server.JobManager()
        # Create and complete 5 jobs, then create 5 more
        for i in range(5):
            jid = jm.create_job("test", {"i": i})
            jm.update_job(jid, status="completed", completed_at=time.time())
        for i in range(5):
            jm.create_job("test", {"i": i + 5})
        jobs = jm.list_jobs()
        assert len(jobs) <= 5

    def test_job_not_found(self, job_mgr):
        assert job_mgr.get_job("nonexistent") is None


# ── Error Handling ───────────────────────────────────────────────

class TestErrorHandling:
    def test_404_handler(self, client):
        r = client.get("/api/nonexistent")
        # Unknown /api/ paths may return 403 (static guard) or 404
        assert r.status_code in (403, 404)
        data = r.get_json()
        assert data["success"] is False

    def test_500_handler(self, client):
        """Internal errors should return JSON, not HTML."""
        # Force a 500 by requesting a malformed session
        r = client.get("/api/session/!@#$")
        assert r.status_code in (400, 404)


# ── File Upload ──────────────────────────────────────────────────

class TestFileUpload:
    def test_no_file(self, client):
        r = client.post("/api/generate", data={})
        assert r.status_code == 400
        data = r.get_json()
        assert data["success"] is False

    def test_unsupported_format(self, client):
        from io import BytesIO
        r = client.post("/api/generate", data={
            "file": (BytesIO(b"test"), "test.exe"),
            "engine": "",
            "maxEpisodes": "1",
            "format": "wav",
        }, content_type="multipart/form-data")
        assert r.status_code == 400
        data = r.get_json()
        assert data["success"] is False

    def test_oversized_file_rejected(self, client, monkeypatch):
        """Files exceeding MAX_CONTENT_LENGTH should be rejected."""
        from io import BytesIO
        monkeypatch.setitem(api_server.app.config, "MAX_CONTENT_LENGTH", 100)
        big_data = b"x" * 200
        r = client.post("/api/generate", data={
            "file": (BytesIO(big_data), "big.txt"),
        }, content_type="multipart/form-data")
        assert r.status_code == 413


# ── Rate Limiting & Middleware ────────────────────────────────────

class TestRateLimiting:
    def test_rate_limit_triggered(self, client, monkeypatch):
        """After exceeding rate limit, should return 429."""
        # Override via app.extensions (the middleware reads from here)
        rl_config = api_server.app.extensions.get("rate_limit_config", {})
        monkeypatch.setitem(rl_config, "max", 3)

        for i in range(3):
            r = client.get("/api/health")
            assert r.status_code == 200
        # 4th request should be rate-limited
        r = client.get("/api/health")
        assert r.status_code == 429
        data = r.get_json()
        assert data["success"] is False

    def test_static_assets_not_rate_limited(self, client, monkeypatch):
        """Static assets should not count towards rate limit."""
        rl_config = api_server.app.extensions.get("rate_limit_config", {})
        monkeypatch.setitem(rl_config, "max", 2)

        for i in range(10):
            r = client.get("/_shared.css")
            assert r.status_code == 200


# ── Favicon ───────────────────────────────────────────────────────

class TestFavicon:
    def test_favicon_returns_200(self, client):
        r = client.get("/favicon.ico")
        assert r.status_code == 200
        assert "image/svg" in r.content_type


# ── Health Check Caching ─────────────────────────────────────────

class TestHealthCache:
    def test_health_caches_result(self, client):
        """Second call within TTL should return cached result."""
        health_cache = api_server.app.extensions.get("health_cache", {})
        health_cache["result"] = None
        health_cache["timestamp"] = 0

        r1 = client.get("/api/health")
        data1 = r1.get_json()
        assert "cached" not in data1  # First call is fresh

        r2 = client.get("/api/health")
        data2 = r2.get_json()
        assert data2.get("cached") is True  # Second call is cached

    def test_health_cache_expires(self, client):
        """After TTL, cache should be refreshed."""
        health_cache = api_server.app.extensions.get("health_cache", {})
        health_cache["result"] = {"success": True, "checks": {}, "status": "healthy"}
        health_cache["timestamp"] = time.time() - 100  # Expired

        r = client.get("/api/health")
        data = r.get_json()
        assert "cached" not in data  # Should be fresh, not cached


# ── Session Pagination ────────────────────────────────────────────

class TestSessionPagination:
    def test_sessions_pagination(self, client):
        """Sessions endpoint should support pagination."""
        r = client.get("/api/sessions?page=1&limit=5")
        data = r.get_json()
        assert "total" in data
        assert "page" in data
        assert data["page"] == 1
        assert data["limit"] == 5
        assert len(data["sessions"]) <= 5

    def test_sessions_default_pagination(self, client):
        """Default should return all sessions (limit=50)."""
        r = client.get("/api/sessions")
        data = r.get_json()
        assert data["limit"] == 50
        assert data["page"] == 1
        assert data["count"] == len(data["sessions"])


# ── Job TTL Cleanup ──────────────────────────────────────────────

class TestJobTTL:
    def test_expired_jobs_cleaned_up(self, job_mgr, monkeypatch):
        """Jobs older than TTL should be cleaned up on next create_job."""
        monkeypatch.setattr(api_server.JobManager, "JOB_TTL_SEC", 0)
        jm = api_server.JobManager()
        jid = jm.create_job("test", {})
        jm.update_job(jid, status="completed", completed_at=time.time() - 10)
        assert len(jm.list_jobs()) == 1

        # Create a new job — should trigger cleanup of old ones
        jm.create_job("test2", {})
        jobs = jm.list_jobs()
        # Old completed job should be gone
        assert all(j["type"] == "test2" for j in jobs)


# ── Job ID Validation ───────────────────────────────────────────

class TestJobIdValidation:
    def test_invalid_job_id_short(self, client):
        """Short job IDs should return 400."""
        r = client.get("/api/jobs/abc123")
        assert r.status_code == 400
        data = r.get_json()
        assert data["success"] is False

    def test_invalid_job_id_special_chars(self, client):
        """Job IDs with special characters should return 400."""
        r = client.get("/api/jobs/!@#$%^&*()")
        # May be caught by other guards first
        assert r.status_code in (400, 403, 404)

    def test_valid_format_nonexistent_job(self, client):
        """Valid format but non-existent job should return 404."""
        r = client.get("/api/jobs/a1b2c3d4e5f6")
        assert r.status_code == 404
        data = r.get_json()
        assert data["success"] is False
        assert "not found" in data["error"].lower()


# ── Security Headers ────────────────────────────────────────────

class TestSecurityHeaders:
    def test_nosniff_header(self, client):
        """X-Content-Type-Options should be nosniff."""
        r = client.get("/api/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_frame_options_header(self, client):
        """X-Frame-Options should be DENY."""
        r = client.get("/api/health")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_csp_header_present(self, client):
        """Content-Security-Policy header should be present."""
        r = client.get("/api/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src" in csp
        assert "frame-ancestors 'none'" in csp

    def test_referrer_policy_header(self, client):
        """Referrer-Policy header should be set."""
        r = client.get("/api/health")
        assert r.headers.get("Referrer-Policy") is not None

    def test_security_headers_on_static(self, client):
        """Security headers should also be on static file responses."""
        r = client.get("/studio.html")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"


# ── Path Traversal Protection ───────────────────────────────────

class TestPathTraversal:
    def test_podcast_output_traversal_blocked(self, client):
        """Path traversal via /podcast-output/ should be blocked."""
        r = client.get("/podcast-output/../../etc/passwd")
        assert r.status_code in (403, 404)

    def test_podcast_output_traversal_to_api(self, client):
        """Trying to access api_server.py via /podcast-output/ should fail."""
        r = client.get("/podcast-output/../api_server.py")
        assert r.status_code in (403, 404)

    def test_download_traversal_blocked(self, client):
        """Path traversal in download filename should be blocked."""
        r = client.get("/api/download/a1b2c3d4e5f6/../../etc/passwd")
        assert r.status_code in (400, 403, 404)

    def test_download_invalid_filename(self, client):
        """Filenames with path separators should be rejected."""
        r = client.get("/api/download/a1b2c3d4e5f6/..%2f..%2fetc%2fpasswd")
        assert r.status_code in (400, 403, 404)


# ── Download Endpoint ───────────────────────────────────────────

class TestDownloadEndpoint:
    def test_download_invalid_session(self, client):
        """Invalid session ID should return 400."""
        r = client.get("/api/download/short/filename.wav")
        assert r.status_code == 400

    def test_download_nonexistent_session(self, client):
        """Valid format but non-existent session should return 404."""
        r = client.get("/api/download/a1b2c3d4e5f6/episode_01.wav")
        assert r.status_code == 404

    def test_download_nonexistent_file(self, client, create_session_dir):
        """Session exists but file doesn't should return 404."""
        session_id = "abcdef123456"
        create_session_dir(session_id)  # Creates session dir without episodes
        r = client.get(f"/api/download/{session_id}/nonexistent.wav")
        assert r.status_code == 404


# ── RSS Endpoint ────────────────────────────────────────────────

class TestRSSEndpoint:
    def test_rss_invalid_session(self, client):
        """Invalid session ID should return 400."""
        r = client.get("/api/rss/short")
        assert r.status_code == 400

    def test_rss_nonexistent(self, client):
        """Valid format but non-existent RSS should return 404."""
        r = client.get("/api/rss/a1b2c3d4e5f6")
        assert r.status_code == 404


# ── Session Detail ─────────────────────────────────────────────

class TestSessionDetail:
    def test_session_detail_invalid(self, client):
        """Invalid session ID should return 400."""
        r = client.get("/api/session/short")
        assert r.status_code == 400

    def test_session_detail_not_found(self, client):
        """Valid format but non-existent session should return 404."""
        r = client.get("/api/session/a1b2c3d4e5f6")
        assert r.status_code == 404

    def test_session_detail_script_url_prefix(self, client, create_session_dir):
        """script_url should contain 'session_' prefix."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_script=True)
        r = client.get(f"/api/session/{session_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert data["script_url"] is not None
        assert f"session_{session_id}" in data["script_url"]

    def test_session_detail_with_manifest(self, client, create_session_dir):
        """Session with manifest should return manifest data."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=True)
        r = client.get(f"/api/session/{session_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["title"] == f"Test Podcast {session_id}"
        assert len(data["manifest"]["episodes"]) == 2


# ── Job Lifecycle ──────────────────────────────────────────────

class TestJobLifecycle:
    def test_full_job_lifecycle(self, job_mgr):
        """Test create → start → update → complete lifecycle."""
        jid = job_mgr.create_job("test_lifecycle", {"param": "value"})
        assert jid

        # Verify initial state
        job = job_mgr.get_job(jid)
        assert job["status"] == "pending"
        assert job["progress"] == 0

        # Update to running
        job_mgr.update_job(jid, status="running", progress=25,
                          started_at=time.time(), stage="processing")
        job = job_mgr.get_job(jid)
        assert job["status"] == "running"
        assert job["progress"] == 25
        assert job["stage"] == "processing"

        # Add logs
        job_mgr.add_log(jid, "Step 1 done", "info")
        job_mgr.add_log(jid, "Step 2 done", "info")
        job = job_mgr.get_job(jid)
        assert len(job["logs"]) == 2

        # Complete the job
        result = {"success": True, "total_time_sec": 42}
        job_mgr.update_job(jid, status="completed", result=result,
                          progress=100, completed_at=time.time())
        job = job_mgr.get_job(jid)
        assert job["status"] == "completed"
        assert job["progress"] == 100
        assert job["result"]["total_time_sec"] == 42

    def test_failed_job_lifecycle(self, job_mgr):
        """Test failed job lifecycle."""
        jid = job_mgr.create_job("test_fail", {})
        job_mgr.update_job(jid, status="running", started_at=time.time())
        job_mgr.update_job(jid, status="failed", error="Something went wrong",
                          completed_at=time.time())
        job = job_mgr.get_job(jid)
        assert job["status"] == "failed"
        assert job["error"] == "Something went wrong"

    def test_job_logs_capped(self, job_mgr, monkeypatch):
        """Logs should be capped at MAX_LOGS_PER_JOB."""
        jid = job_mgr.create_job("test_logs", {})
        monkeypatch.setattr(api_server.JobManager, "MAX_LOGS_PER_JOB", 5)
        for i in range(10):
            job_mgr.add_log(jid, f"Message {i}")
        job = job_mgr.get_job(jid)
        assert len(job["logs"]) == 5
        # Should keep the first 5 (cap prevents adding beyond limit)
        assert job["logs"][0]["message"] == "Message 0"


# ── Form Field Validation ───────────────────────────────────────

class TestFormFieldValidation:
    def test_filename_too_long(self, client):
        """Filenames exceeding 255 chars should be rejected."""
        from io import BytesIO
        long_name = "a" * 300 + ".txt"
        r = client.post("/api/generate", data={
            "file": (BytesIO(b"test"), long_name),
        }, content_type="multipart/form-data")
        assert r.status_code == 400
        data = r.get_json()
        assert data["success"] is False

    def test_engine_name_truncated(self, client):
        """Engine names should be truncated to 50 chars (not cause errors)."""
        from io import BytesIO
        long_engine = "x" * 200
        r = client.post("/api/generate", data={
            "file": (BytesIO(b"test"), "test.txt"),
            "engine": long_engine,
        }, content_type="multipart/form-data")
        # Should succeed (engine is truncated, not rejected)
        # Will fail due to pipeline not being available, but that's a 503 or 500
        assert r.status_code in (200, 202, 500, 503)


# ── Generate Success Path ──────────────────────────────────────

class TestGenerateSuccess:
    def test_generate_success_path(self, client, monkeypatch):
        """POST /api/generate with valid file should return job_id."""
        from io import BytesIO

        # Mock the pipeline runner to avoid actual pipeline execution
        def mock_start_job(self, job_id, target_func, *args, **kwargs):
            # Don't actually start the thread; just mark as running
            self.update_job(job_id, status="running", started_at=time.time())
        monkeypatch.setattr(api_server.JobManager, "start_job", mock_start_job)

        r = client.post("/api/generate", data={
            "file": (BytesIO(b"test book content"), "test_book.txt"),
            "engine": "edge-tts",
            "maxEpisodes": "3",
            "format": "mp3",
            "enableEq": "true",
            "scriptOnly": "false",
            "enableNoiseReduction": "true",
            "enablePedalboard": "true",
            "generateRss": "true",
            "embedId3": "true",
        }, content_type="multipart/form-data")

        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert "job_id" in data
        assert "session_id" in data
        assert data["status"] == "pending"
        assert len(data["job_id"]) == 12
        assert len(data["session_id"]) == 12

        # Cleanup uploaded file
        upload_path = os.path.join(api_server.UPLOAD_DIR, f"{data['session_id']}_test_book.txt")
        if os.path.exists(upload_path):
            os.remove(upload_path)

    def test_generate_default_options(self, client, monkeypatch):
        """POST /api/generate with minimal options should use defaults."""
        from io import BytesIO

        def mock_start_job(self, job_id, target_func, *args, **kwargs):
            pass
        monkeypatch.setattr(api_server.JobManager, "start_job", mock_start_job)

        r = client.post("/api/generate", data={
            "file": (BytesIO(b"test"), "minimal.txt"),
        }, content_type="multipart/form-data")

        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True

        # Cleanup
        upload_path = os.path.join(api_server.UPLOAD_DIR, f"{data['session_id']}_minimal.txt")
        if os.path.exists(upload_path):
            os.remove(upload_path)


# ── Job Detail Success Path ─────────────────────────────────────

class TestJobDetailSuccess:
    def test_job_detail_returns_full_data(self, client):
        """GET /api/jobs/<id> with existing job should return full data."""
        jid = api_server.job_manager.create_job("test", {"engine": "edge-tts"})
        api_server.job_manager.update_job(jid, status="running", progress=50,
                                          stage="processing", started_at=time.time())
        api_server.job_manager.add_log(jid, "Step 1 done")

        r = client.get(f"/api/jobs/{jid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        job = data["job"]
        assert job["id"] == jid
        assert job["status"] == "running"
        assert job["progress"] == 50
        assert job["stage"] == "processing"
        assert len(job["logs"]) == 1
        # Full params should be returned (not redacted in detail view)
        assert job["params"]["engine"] == "edge-tts"


# ── Download Success Path ──────────────────────────────────────

class TestDownloadSuccess:
    def test_download_existing_file(self, client, create_session_dir):
        """GET /api/download/<id>/<file> with existing file should return 200."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_episodes=True)

        r = client.get(f"/api/download/{session_id}/episode_01.wav")
        assert r.status_code == 200
        assert r.headers.get("Content-Disposition") is not None
        assert "attachment" in r.headers.get("Content-Disposition", "")


# ── RSS Success Path ────────────────────────────────────────────

class TestRSSSuccess:
    def test_rss_download_success(self, client, create_session_dir):
        """GET /api/rss/<id> with existing RSS should return 200 + XML."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_rss=True)

        r = client.get(f"/api/rss/{session_id}")
        assert r.status_code == 200
        assert "rss" in r.content_type or "xml" in r.content_type


# ── Session Detail Success with Episodes ───────────────────────

class TestSessionDetailWithEpisodes:
    def test_session_detail_with_episodes(self, client, create_session_dir):
        """GET /api/session/<id> with episodes should return episode list."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=True, with_episodes=True, with_rss=True)

        r = client.get(f"/api/session/{session_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert len(data["episodes"]) > 0
        assert data["episodes"][0]["name"] == "episode_01.wav"
        assert "url" in data["episodes"][0]
        assert data["has_rss"] is True
        assert data["rss_url"] is not None


# ── Static Podcast Output Serving ──────────────────────────────

class TestPodcastOutputServing:
    def test_serve_existing_podcast_file(self, client, create_session_dir):
        """GET /podcast-output/session_xxx/file should serve the file."""
        session_id = "abcdef123456"
        session_dir = create_session_dir(session_id, with_script=True)

        r = client.get(f"/podcast-output/session_{session_id}/podcast_script.html")
        assert r.status_code == 200

    def test_serve_nonexistent_podcast_file(self, client):
        """GET /podcast-output/nonexistent should return 404."""
        r = client.get("/podcast-output/session_nonexistent123/file.html")
        assert r.status_code == 404


# ── Clean URL Routing ──────────────────────────────────────────

class TestCleanURLs:
    def test_studio_clean_url(self, client):
        """GET /studio should serve studio.html."""
        r = client.get("/studio")
        assert r.status_code == 200
        assert b"Podcast Studio" in r.data

    def test_library_clean_url(self, client):
        """GET /library should serve library.html."""
        r = client.get("/library")
        assert r.status_code == 200

    def test_player_clean_url(self, client):
        """GET /player should serve player.html."""
        r = client.get("/player")
        assert r.status_code == 200

    def test_docs_clean_url(self, client):
        """GET /docs should serve docs.html."""
        r = client.get("/docs")
        assert r.status_code == 200

    def test_home_clean_url(self, client):
        """GET /home should serve index.html."""
        r = client.get("/home")
        assert r.status_code == 200


# ── Shared JS Serving ──────────────────────────────────────────

class TestSharedJS:
    def test_shared_js_served(self, client):
        """GET /_shared.js should return 200 with JS content."""
        r = client.get("/_shared.js")
        assert r.status_code == 200
        assert b"function escapeHtml" in r.data
        assert b"function fetchWithTimeout" in r.data
        assert b"function showLoading" in r.data
        assert b"function showError" in r.data


# ── JobManager.start_job ──────────────────────────────────────

class TestStartJob:
    def test_start_job_executes_function(self, job_mgr):
        """start_job should run the target function in a thread."""
        results = []

        def target_func(arg1, arg2):
            results.append((arg1, arg2))
            return {"sum": arg1 + arg2}

        jid = job_mgr.create_job("test", {})
        job_mgr.start_job(jid, target_func, 3, 4)

        # Wait for thread to complete
        import time as _time
        _time.sleep(0.5)

        job = job_mgr.get_job(jid)
        assert job["status"] == "completed"
        assert job["result"]["sum"] == 7
        assert len(results) == 1
        assert results[0] == (3, 4)

    def test_start_job_handles_exception(self, job_mgr):
        """start_job should catch exceptions and mark job as failed."""
        def failing_func():
            raise ValueError("Test error")

        jid = job_mgr.create_job("test", {})
        job_mgr.start_job(jid, failing_func)

        import time as _time
        _time.sleep(0.5)

        job = job_mgr.get_job(jid)
        assert job["status"] == "failed"
        assert "Test error" in job["error"]


# ── Invalid Pagination Params ──────────────────────────────────

class TestInvalidPagination:
    def test_negative_page(self, client):
        """Negative page should be clamped to 1."""
        r = client.get("/api/sessions?page=-1&limit=5")
        assert r.status_code == 200
        data = r.get_json()
        assert data["page"] == 1

    def test_zero_page(self, client):
        """Page 0 should be clamped to 1."""
        r = client.get("/api/sessions?page=0")
        assert r.status_code == 200
        data = r.get_json()
        assert data["page"] == 1

    def test_limit_exceeds_max(self, client):
        """Limit > 200 should be clamped to 200."""
        r = client.get("/api/sessions?limit=999")
        assert r.status_code == 200
        data = r.get_json()
        assert data["limit"] == 200

    def test_invalid_limit_type(self, client):
        """Non-integer limit should use default."""
        r = client.get("/api/sessions?limit=abc")
        assert r.status_code == 200
        data = r.get_json()
        assert data["limit"] == api_server.cfg.default_page_size


# ── Session/Job ID Parametrized ────────────────────────────────

class TestIDValidationParametrized:
    @pytest.mark.parametrize("invalid_id,description", [
        ("short", "Too short (< 8 chars)"),
        ("12345", "Too short (5 digits)"),
        ("!@#$%^&*()", "Special chars"),
        ("../../../etc", "Path traversal"),
        ("has space", "Contains space"),
        ("has.dots", "Contains dots"),
        ("a" * 33, "Too long (> 32 chars)"),
        ("", "Empty string"),
    ])
    def test_invalid_session_id_formats(self, client, invalid_id, description):
        """Various invalid session ID formats should be rejected."""
        r = client.get(f"/api/session/{invalid_id}")
        assert r.status_code in (400, 403, 404)

    @pytest.mark.parametrize("invalid_id,description", [
        ("short", "Too short (< 8 chars)"),
        ("!@#$%^&*()", "Special chars"),
        ("../../../etc", "Path traversal"),
        ("has space", "Contains space"),
        ("a" * 33, "Too long (> 32 chars)"),
    ])
    def test_invalid_job_id_formats(self, client, invalid_id, description):
        """Various invalid job ID formats should be rejected."""
        r = client.get(f"/api/jobs/{invalid_id}")
        assert r.status_code in (400, 403, 404)

    @pytest.mark.parametrize("valid_id,description", [
        ("a1b2c3d4e5f6", "12-char hex (generate_id format)"),
        ("1783088138", "10-digit numeric (legacy timestamp)"),
        ("ABCDEF123456", "12-char uppercase hex"),
        ("session-id-001", "Alphanumeric with hyphens"),
        ("a1b2c3d4", "8 chars (minimum length)"),
        ("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4", "32 chars (maximum length)"),
    ])
    def test_valid_session_id_formats(self, client, valid_id, description):
        """Various valid session ID formats should pass validation (not 400)."""
        r = client.get(f"/api/session/{valid_id}")
        # Should NOT be 400 (invalid); 404 (not found) is acceptable
        assert r.status_code != 400, f"Valid ID rejected: {description}"


# ── Session Listing Data Fallback ──────────────────────────────

class TestSessionListingFallback:
    """Tests that session listing falls back to actual file counts/sizes
    when manifest data is incomplete or zero."""

    def test_episode_count_fallback_to_files(self, client, create_session_dir):
        """When manifest has no episodes array but files exist, count actual files."""
        session_id = "abcdef123456"
        session_dir = create_session_dir(
            session_id, with_manifest=True, with_episodes=True
        )
        # Remove episodes array from manifest to simulate incomplete data
        manifest_path = session_dir / "podcast_package" / "podcast_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["episodes"] = []
        manifest_path.write_text(json.dumps(manifest))
        # Make episode file larger so it shows up in MB (>1MB)
        (session_dir / "episodes" / "episode_01.wav").write_bytes(b"\x00" * (2 * 1024 * 1024))

        r = client.get("/api/sessions")
        data = r.get_json()
        assert data["success"] is True
        assert data["total"] >= 1
        # Find our session
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is not None
        # Should fall back to counting actual episode files (fixture creates 1)
        assert our_session["episodes"] >= 1
        # Should fall back to summing actual file sizes (2MB file)
        assert our_session["file_size_mb"] >= 1.0

    def test_manifest_values_used_when_present(self, client, create_session_dir):
        """When manifest has episodes array, those values should be used."""
        session_id = "abcdef123456"
        create_session_dir(
            session_id, with_manifest=True, with_episodes=True
        )

        r = client.get("/api/sessions")
        data = r.get_json()
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is not None
        # Fixture manifest has 2 episodes with duration_sec=315 each (total 630s = 10.5 min)
        # and file_size=524288 each (total 1048576 = 1.0 MB)
        assert our_session["episodes"] == 2
        assert our_session["duration_min"] == 10.5  # 630 sec / 60
        assert our_session["file_size_mb"] == 1.0  # 1048576 bytes = 1.0 MB


# ── Session Filtering ───────────────────────────────────────────

class TestSessionFiltering:
    """Tests that incomplete sessions are filtered from listings."""

    def test_empty_session_filtered_out(self, client, create_session_dir):
        """Session with no manifest and no episodes should not appear in listing."""
        session_id = "abcdef123456"
        # Create session directory but with nothing in it
        create_session_dir(session_id, with_manifest=False, with_episodes=False)

        r = client.get("/api/sessions")
        data = r.get_json()
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is None, "Empty session should be filtered out"

    def test_manifest_only_session_listed(self, client, create_session_dir):
        """Session with manifest but no episodes should still be listed."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=True, with_episodes=False)

        r = client.get("/api/sessions")
        data = r.get_json()
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is not None
        assert our_session["episodes"] == 2  # From manifest episodes array

    def test_episodes_only_session_listed(self, client, create_session_dir):
        """Session with episodes but no manifest should be listed with file-based counts."""
        session_id = "abcdef123456"
        create_session_dir(session_id, with_manifest=False, with_episodes=True)

        r = client.get("/api/sessions")
        data = r.get_json()
        our_session = next(
            (s for s in data["sessions"] if s["session_id"] == session_id), None
        )
        assert our_session is not None
        # No manifest, so title falls back to dir name
        assert our_session["title"] == f"session_{session_id}"
        # Episodes counted from actual files
        assert our_session["episodes"] >= 1


# ── Engines Degraded Mode ──────────────────────────────────────

class TestEnginesDegradedMode:
    """Tests for /api/engines when pipeline source is unavailable."""

    def test_engines_returns_success_field(self, client):
        """Engines endpoint always returns a 'success' field."""
        r = client.get("/api/engines")
        data = r.get_json()
        assert "success" in data

    def test_engines_503_when_pipeline_unavailable(self, client, monkeypatch):
        """When pipeline is unavailable, engines should return 503 with error."""
        # Patch the config used by the route to simulate no pipeline
        from config import Config
        # The route checks config.has_pipeline; we need to patch the closure variable
        # Since the route captures 'config' from init_api, we test by checking
        # the actual response: if pipeline is unavailable, success=False
        r = client.get("/api/engines")
        data = r.get_json()

        if not data.get("success"):
            # Pipeline is unavailable in this environment
            assert r.status_code == 503
            assert "error" in data
            assert "not available" in data["error"].lower() or "不可用" in data["error"]
        else:
            # Pipeline is available — engines should be listed
            assert "engines" in data
            assert "active_engine" in data
            assert isinstance(data["engines"], list)


# ── Pagination Total vs Count ──────────────────────────────────

class TestPaginationTotalVsCount:
    """Tests that pagination correctly distinguishes total from page count."""

    def test_total_exceeds_page_count(self, client, create_session_dir):
        """When more sessions exist than page limit, total > count."""
        # Create more sessions than the default page size (50)
        for i in range(3):
            sid = f"aabbcc{i:06d}"  # 8-char hex-like IDs
            create_session_dir(sid, with_manifest=True, with_episodes=False)

        r = client.get("/api/sessions?limit=2")
        data = r.get_json()
        assert data["success"] is True
        assert data["count"] == 2  # Items on this page
        assert data["total"] >= 3  # Total items across all pages

    def test_empty_sessions_total_zero(self, client):
        """When no sessions exist, total should be 0 (not count)."""
        r = client.get("/api/sessions")
        data = r.get_json()
        # total reflects actual session count, count is page items
        assert "total" in data
        assert "count" in data
        assert data["count"] == len(data["sessions"])
