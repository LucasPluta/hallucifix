"""Demo 4 worker: concurrent job processor with retry logic.

Processes jobs from the SQLite-backed queue using a thread pool.
Each job payload is a JSON object like {"op": "transform", "value": N}.
The worker transforms the value, stores the result, and handles retries
for transient I/O failures.

⚠️  THIS FILE CONTAINS THREE INTENTIONAL BUGS ⚠️

Bug 1 (Race condition):
    _in_flight is a plain dict shared across threads with no lock.
    register_in_flight() checks if a job is already tracked before
    inserting. Between the check and the insert, a thread yield
    (time.sleep(0)) creates a window where another thread can
    double-register, causing the completion counter to be wrong.
    complete_in_flight() then decrements a shared counter without
    a lock, so concurrent decrements can lose updates.
    Under concurrency this causes KeyError or silently drops tracking.

Bug 2 (Schema mismatch):
    aggregate_results() queries for jobs WHERE status = 0 (integer)
    instead of status = 'done' (string). The DB stores status as TEXT,
    so this query always returns zero rows, making the aggregator think
    no jobs completed.

Bug 3 (Retry sleep bug):
    In _process_with_retry(), on failure the code sleeps for `timeout`
    (which is retries * delay — cumulative) instead of `delay`
    (per-attempt). This causes the 3rd retry to sleep 3× the intended
    delay, easily exceeding test timeouts and causing spurious failures.
"""

import json
import logging
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

LOG_FILE = "/tmp/hallucifix_demo4_worker.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
log = logging.getLogger("worker")

# ── In-flight tracking (shared across threads) ─────────────────
_in_flight: dict[int, str] = {}
_completed_count = 0  # Track how many jobs completed

# ── Import models lazily to allow test monkeypatching ──────────
_models = None


def _get_models():
    global _models
    if _models is None:
        import models as m  # noqa: local import for reloadability
        _models = m
    return _models


def reload_models():
    """Force re-import of models (used after importlib.reload)."""
    global _models, _completed_count
    _models = None
    _completed_count = 0


# ── In-flight tracking ─────────────────────────────────────────

def register_in_flight(job_id: int, payload: str) -> None:
    """Track a job as being processed.

    BUG 1: Check-then-act without a lock. The time.sleep(0) between
    the check and the insert yields to other threads, creating a race
    window where concurrent registrations can collide.
    """
    if job_id in _in_flight:
        log.warning("Job %d already in-flight, skipping", job_id)
        return
    time.sleep(0.001)  # yield — widens the race window
    _in_flight[job_id] = payload
    log.debug("Registered in-flight: job %d", job_id)


def complete_in_flight(job_id: int) -> str | None:
    """Remove a job from in-flight tracking and return its payload.

    BUG 1 (continued): Increments a shared counter without a lock.
    Under concurrent access, two threads reading _completed_count
    simultaneously will both see the same value, so one increment
    is lost.
    """
    global _completed_count
    val = _in_flight.pop(job_id, None)
    if val is None:
        log.warning("Job %d was not in _in_flight (race?)", job_id)
    # BUG: read-modify-write without lock
    current = _completed_count
    time.sleep(0.001)  # yield — widens the race window
    _completed_count = current + 1
    return val


def get_in_flight_count() -> int:
    return len(_in_flight)


def get_completed_count() -> int:
    return _completed_count


# ── Job transformation logic ──────────────────────────────────

def transform_value(payload_str: str) -> str:
    """Parse a job payload and compute the result.

    Payload: {"op": "transform", "value": N}
    Result:  {"original": N, "transformed": N * 2 + 1}
    """
    data = json.loads(payload_str)
    value = data["value"]
    result = value * 2 + 1
    log.info("transform(%s) = %s", value, result)
    return json.dumps({"original": value, "transformed": result})


# ── Retry wrapper ──────────────────────────────────────────────

def _process_with_retry(
    job_id: int,
    payload: str,
    max_retries: int = 3,
    delay: float = 0.1,
    io_callback=None,
) -> bool:
    """Process a single job, retrying on transient failures.

    *io_callback* is called after transformation to simulate I/O
    (writing result to DB). If it raises, we retry.

    BUG 3: On failure, sleeps for `timeout` (= retries * delay,
    cumulative) instead of `delay` (per-attempt constant).
    On retry 3 with delay=0.1 this sleeps 0.3s instead of 0.1s —
    tolerable alone but catastrophic in aggregate under concurrency.
    """
    models = _get_models()
    register_in_flight(job_id, payload)

    for attempt in range(1, max_retries + 1):
        try:
            result_str = transform_value(payload)

            # Simulate I/O (the test injects failures here)
            if io_callback is not None:
                io_callback(job_id, result_str)
            else:
                models.mark_done(job_id, result_str)

            complete_in_flight(job_id)
            log.info("Job %d completed on attempt %d", job_id, attempt)
            return True

        except Exception as exc:
            # BUG 3: should be `delay`, not `timeout`
            timeout = attempt * delay
            log.warning(
                "Job %d attempt %d failed (%s), sleeping %.2fs",
                job_id, attempt, exc, timeout,
            )
            time.sleep(timeout)  # ← BUG: should be time.sleep(delay)

    # Exhausted retries
    complete_in_flight(job_id)
    models.mark_failed(job_id, max_retries)
    log.error("Job %d failed after %d retries", job_id, max_retries)
    return False


# ── Worker pool ────────────────────────────────────────────────

def process_batch(
    jobs: list[dict],
    max_workers: int = 4,
    max_retries: int = 3,
    delay: float = 0.1,
    io_callback=None,
) -> dict:
    """Process a batch of jobs concurrently.

    Returns {"succeeded": int, "failed": int}.
    """
    succeeded = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _process_with_retry,
                job["id"],
                job["payload"],
                max_retries,
                delay,
                io_callback,
            ): job["id"]
            for job in jobs
        }

        for future in as_completed(futures):
            job_id = futures[future]
            try:
                ok = future.result()
                if ok:
                    succeeded += 1
                else:
                    failed += 1
            except Exception as exc:
                log.error("Job %d raised: %s", job_id, exc)
                failed += 1

    return {"succeeded": succeeded, "failed": failed}


# ── Result aggregation ─────────────────────────────────────────

def aggregate_results() -> dict:
    """Fetch all completed results and compute summary statistics.

    BUG 2: Queries with status = 0 (integer) instead of status = 'done'
    (string). SQLite stores status as TEXT, so `WHERE status = 0` matches
    nothing, and aggregate_results() always reports zero completed jobs.
    """
    models = _get_models()
    conn = models.get_connection()
    # BUG 2: should be status = 'done', not status = 0
    rows = conn.execute(
        "SELECT id, payload, result FROM jobs WHERE status = 0"
    ).fetchall()
    conn.close()

    results = []
    total = 0
    for row in rows:
        data = json.loads(row["result"])
        results.append(data)
        total += data.get("transformed", 0)

    return {
        "count": len(results),
        "total_transformed": total,
        "results": results,
    }


# ── Pipeline: enqueue → process → aggregate ───────────────────

def run_pipeline(
    values: list[int],
    max_workers: int = 4,
    max_retries: int = 3,
    delay: float = 0.1,
    io_callback=None,
) -> dict:
    """End-to-end pipeline: enqueue values, process them, aggregate.

    Returns the aggregation summary.
    """
    models = _get_models()
    models.init_db()

    # Enqueue
    job_ids = []
    for v in values:
        payload = json.dumps({"op": "transform", "value": v})
        jid = models.enqueue_job(payload)
        job_ids.append(jid)

    # Claim and process
    jobs = models.claim_pending_jobs(limit=len(values))
    batch_result = process_batch(
        jobs,
        max_workers=max_workers,
        max_retries=max_retries,
        delay=delay,
        io_callback=io_callback,
    )

    log.info("Batch result: %s", batch_result)

    # Aggregate
    summary = aggregate_results()
    return summary
