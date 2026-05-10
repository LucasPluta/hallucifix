"""Tests for demo 4: concurrent job queue with adverse conditions.

These tests simulate real-world failure scenarios:
  - Concurrent job processing with thread contention
  - Transient I/O failures (disk contention / network blips)
  - Result aggregation after partial failures
  - Pipeline end-to-end under stress

The tests are designed to surface all three bugs in worker.py:
  Bug 1: Race condition in _in_flight tracking (concurrent test)
  Bug 2: Schema mismatch in aggregate_results (aggregation test)
  Bug 3: Retry sleep using cumulative timeout (I/O failure test)
"""

import importlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_demo_dir = str(Path(__file__).resolve().parent)
if _demo_dir not in sys.path:
    sys.path.insert(0, _demo_dir)

import models
import worker


def _reset():
    """Reinitialize DB and reload worker to pick up any patches."""
    # Use a unique temp DB for each test
    db_path = f"/tmp/hallucifix_demo4_test_{os.getpid()}.db"
    os.environ["DEMO4_DB"] = db_path

    # Clean DB
    if os.path.exists(db_path):
        os.unlink(db_path)

    importlib.reload(models)
    importlib.reload(worker)
    worker.reload_models()
    worker._in_flight.clear()
    models.init_db()


@pytest.fixture(autouse=True)
def setup_teardown():
    _reset()
    yield
    # Cleanup temp DB
    db_path = os.environ.get("DEMO4_DB", "")
    if db_path and os.path.exists(db_path):
        os.unlink(db_path)


# ── Test 1: Basic transformation correctness ───────────────────

def test_transform_value():
    """Each value V should produce transformed = V * 2 + 1."""
    for v in [0, 1, 5, 100, -3]:
        result = json.loads(worker.transform_value(json.dumps({"op": "transform", "value": v})))
        assert result["transformed"] == v * 2 + 1, (
            f"transform({v}) = {result['transformed']}, expected {v * 2 + 1}"
        )


# ── Test 2: Concurrent processing with race detection ──────────

def test_concurrent_processing_no_lost_jobs():
    """Process 20 jobs across 4 threads — every job must complete.

    Surfaces Bug 1: the unprotected _completed_count has a read-modify-
    write race. With time.sleep(0) yield points, concurrent threads lose
    increments, so get_completed_count() < n_jobs.
    """
    n_jobs = 40
    job_ids = []
    for i in range(n_jobs):
        payload = json.dumps({"op": "transform", "value": i})
        jid = models.enqueue_job(payload)
        job_ids.append(jid)

    jobs = models.claim_pending_jobs(limit=n_jobs)
    assert len(jobs) == n_jobs

    result = worker.process_batch(jobs, max_workers=8, max_retries=1, delay=0.01)

    assert result["succeeded"] == n_jobs, (
        f"Expected {n_jobs} succeeded, got {result['succeeded']} "
        f"(failed: {result['failed']})"
    )
    assert result["failed"] == 0

    # Verify all tracked in-flight are cleared
    assert worker.get_in_flight_count() == 0, (
        f"Leaked {worker.get_in_flight_count()} in-flight entries"
    )

    # Verify completed counter matches (surfaces Bug 1)
    assert worker.get_completed_count() == n_jobs, (
        f"Completed counter is {worker.get_completed_count()}, expected {n_jobs}. "
        f"Race condition in _completed_count increment."
    )

    # Verify DB state
    counts = models.count_by_status()
    assert counts.get("done", 0) == n_jobs, (
        f"Expected {n_jobs} done in DB, got {counts}"
    )


# ── Test 3: Aggregation correctness ────────────────────────────

def test_aggregate_results_after_processing():
    """After processing N jobs, aggregate_results must find them all.

    Surfaces Bug 2: aggregate_results queries status = 0 (int) instead
    of status = 'done' (str), so it always returns count=0.
    """
    values = [10, 20, 30]
    for v in values:
        payload = json.dumps({"op": "transform", "value": v})
        jid = models.enqueue_job(payload)

    jobs = models.claim_pending_jobs(limit=len(values))
    worker.process_batch(jobs, max_workers=2, max_retries=1, delay=0.01)

    summary = worker.aggregate_results()

    assert summary["count"] == len(values), (
        f"Expected {len(values)} results, got {summary['count']}. "
        f"DB status counts: {models.count_by_status()}"
    )

    expected_total = sum(v * 2 + 1 for v in values)
    assert summary["total_transformed"] == expected_total, (
        f"Expected total {expected_total}, got {summary['total_transformed']}"
    )


# ── Test 4: Retry under I/O failures respects timing ───────────

def test_retry_timing_under_io_failures():
    """Inject transient I/O failures and verify retries complete promptly.

    Surfaces Bug 3: _process_with_retry sleeps `attempt * delay` instead
    of just `delay`, making later retries far too slow.

    With 3 retries at delay=0.05, correct total sleep = 3 * 0.05 = 0.15s per job.
    With the bug, total sleep = 0.05 + 0.10 + 0.15 = 0.30s per job.
    Across 12 jobs with 4 workers (3 waves), bug: ~0.9s, correct: ~0.45s.
    """
    n_jobs = 16
    delay = 0.1
    max_retries = 4

    for i in range(n_jobs):
        payload = json.dumps({"op": "transform", "value": i})
        models.enqueue_job(payload)

    jobs = models.claim_pending_jobs(limit=n_jobs)

    # Every attempt fails except the last retry
    attempt_counts: dict[int, int] = {}
    count_lock = threading.Lock()

    def flaky_io(job_id: int, result_str: str):
        with count_lock:
            attempt_counts.setdefault(job_id, 0)
            attempt_counts[job_id] += 1
            current = attempt_counts[job_id]
        if current < max_retries:
            raise IOError(f"Simulated I/O failure for job {job_id} (attempt {current})")
        worker._get_models().mark_done(job_id, result_str)

    # 16 jobs / 2 workers = 8 waves of 2 concurrent jobs
    # Correct total sleep per job: 4 retries × 0.1s = 0.4s
    # Correct wall time: 8 waves × 0.4s = 3.2s
    # Buggy sleep per job: 0.1+0.2+0.3+0.4 = 1.0s
    # Buggy wall time: 8 waves × 1.0s = 8.0s
    deadline = 4.5
    start = time.monotonic()

    result = worker.process_batch(
        jobs,
        max_workers=2,
        max_retries=max_retries,
        delay=delay,
        io_callback=flaky_io,
    )

    elapsed = time.monotonic() - start

    assert result["succeeded"] == n_jobs, (
        f"Expected all {n_jobs} to succeed after retries, "
        f"got {result['succeeded']} succeeded / {result['failed']} failed"
    )
    assert elapsed < deadline, (
        f"Retries took {elapsed:.2f}s, expected < {deadline}s. "
        f"Retry sleep may be using cumulative timeout instead of fixed delay."
    )


# ── Test 5: Full pipeline end-to-end under stress ──────────────

def test_full_pipeline_stress():
    """Run the full pipeline with 15 values and verify aggregation.

    This is the integration test that exercises all three bugs together:
    race condition, schema mismatch, and retry timing.
    """
    values = list(range(1, 16))  # 1..15

    summary = worker.run_pipeline(
        values,
        max_workers=4,
        max_retries=2,
        delay=0.01,
    )

    assert summary["count"] == len(values), (
        f"Pipeline produced {summary['count']} results, expected {len(values)}. "
        f"DB counts: {models.count_by_status()}"
    )

    expected_total = sum(v * 2 + 1 for v in values)
    assert summary["total_transformed"] == expected_total, (
        f"Expected total {expected_total}, got {summary['total_transformed']}"
    )
