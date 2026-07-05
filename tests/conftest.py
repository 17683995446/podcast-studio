"""
Pytest configuration and shared fixtures for Podcast Studio API tests.

This file provides:
  - `client` — Flask test client with isolated state
  - `job_mgr` — Fresh JobManager instance per test
  - `tmp_output_dir` — Temporary OUTPUT_DIR (autouse, prevents workspace pollution)
  - `reset_rate_limit` — Clears rate limiter state (autouse)
  - `reset_health_cache` — Clears health cache (autouse)

All autouse fixtures ensure tests are fully isolated: no global state
leaks between tests, no files written to the real workspace.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

# Ensure /workspace is on the path
sys.path.insert(0, "/workspace")

import api_server


# ── Autouse: Reset global state before each test ────────────────

@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Clear rate limiter store before each test."""
    rl_store = api_server.app.extensions.get("rate_limit_store", {})
    rl_store.clear()
    # Reset config to defaults
    rl_config = api_server.app.extensions.get("rate_limit_config", {})
    rl_config["max"] = api_server.cfg.rate_limit_max
    rl_config["window"] = api_server.cfg.rate_limit_window
    rl_config["cleanup_threshold"] = api_server.cfg.rate_limit_cleanup_threshold
    yield
    rl_store.clear()
    rl_config["max"] = api_server.cfg.rate_limit_max
    rl_config["window"] = api_server.cfg.rate_limit_window


@pytest.fixture(autouse=True)
def reset_health_cache():
    """Clear health check cache before each test."""
    health_cache = api_server.app.extensions.get("health_cache", {})
    health_cache["result"] = None
    health_cache["timestamp"] = 0
    yield
    health_cache["result"] = None
    health_cache["timestamp"] = 0


@pytest.fixture(autouse=True)
def reset_job_manager():
    """Clear the module-level job_manager before each test."""
    api_server.job_manager._jobs.clear()
    yield
    api_server.job_manager._jobs.clear()


@pytest.fixture(autouse=True)
def reset_job_class_attrs():
    """Reset JobManager class attributes to defaults before each test."""
    # Save originals
    orig_max = api_server.JobManager.MAX_JOBS
    orig_logs = api_server.JobManager.MAX_LOGS_PER_JOB
    orig_ttl = api_server.JobManager.JOB_TTL_SEC
    yield
    # Restore
    api_server.JobManager.MAX_JOBS = orig_max
    api_server.JobManager.MAX_LOGS_PER_JOB = orig_logs
    api_server.JobManager.JOB_TTL_SEC = orig_ttl


# ── Shared fixtures ─────────────────────────────────────────────

@pytest.fixture
def client():
    """Flask test client."""
    api_server.app.config["TESTING"] = True
    with api_server.app.test_client() as c:
        yield c


@pytest.fixture
def job_mgr():
    """Fresh JobManager instance for unit tests."""
    return api_server.JobManager()


@pytest.fixture
def valid_id():
    """A valid 12-hex-char ID format (non-existent)."""
    return "a1b2c3d4e5f6"


@pytest.fixture
def fake_session_id():
    """A valid 12-hex-char ID for creating fake session dirs."""
    return "abcdef123456"


@pytest.fixture
def create_session_dir(tmp_path):
    """Factory that creates a session directory under OUTPUT_DIR.

    Returns the session_dir Path. Automatically cleans up.
    """
    created_dirs = []

    def _create(session_id="abcdef123456", with_manifest=False, with_script=False,
                with_episodes=False, with_rss=False):
        session_dir = Path(api_server.OUTPUT_DIR) / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)

        if with_manifest:
            pkg_dir = session_dir / "podcast_package"
            pkg_dir.mkdir(exist_ok=True)
            # Use actual pipeline manifest field names
            manifest = {
                "title": f"Test Podcast {session_id}",
                "episodes": [
                    {
                        "title": "Episode 1",
                        "duration_sec": 315,
                        "file_size": 524288,
                        "audio_path": f"/workspace/podcast-output/session_{session_id}/episodes/episode_01.wav",
                    },
                    {
                        "title": "Episode 2",
                        "duration_sec": 315,
                        "file_size": 524288,
                        "audio_path": f"/workspace/podcast-output/session_{session_id}/episodes/episode_02.wav",
                    },
                ],
                "created_at": "2026-07-04T12:00:00",
            }
            (pkg_dir / "podcast_manifest.json").write_text(
                __import__("json").dumps(manifest)
            )

        if with_script:
            (session_dir / "podcast_script.html").write_text("<html></html>")

        if with_episodes:
            ep_dir = session_dir / "episodes"
            ep_dir.mkdir(exist_ok=True)
            (ep_dir / "episode_01.wav").write_bytes(b"\x00" * 100)

        if with_rss:
            pkg_dir = session_dir / "podcast_package"
            pkg_dir.mkdir(exist_ok=True)
            (pkg_dir / "podcast.rss.xml").write_text("<rss></rss>")

        created_dirs.append(session_dir)
        return session_dir

    yield _create

    # Cleanup
    import shutil
    for d in created_dirs:
        shutil.rmtree(d, ignore_errors=True)
