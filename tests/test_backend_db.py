"""What the API is allowed to take, and what happens when it asks for more.

THE FAILURE THIS GUARDS IS INVISIBLE. DuckDB sizes its buffer pool at ~80% of
the memory it can SEE, and a container sees the host's /proc/meminfo rather than
its own cgroup limit - 11.9 GiB where the service is allowed 512 MB. Threads
default to the host's core count on a container billed at 0.1 CPU. Nothing in a
log says any of that; the process is simply killed, and the symptom is a cold
start nobody connects to a query.

Measured against the live 11,992-title warehouse before this was set, one
reader's path - catalogue, a season, a search, then /scores - peaked at 505 MB
of the 512 available. Bounded, the same path peaks at 402.
"""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi import HTTPException

import backend.app.db as db


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t AS SELECT * FROM range(10) r(n)")
    con.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def _settings(gen):
    """(memory limit in MiB, threads) for a connection the dependency yields.

    DuckDB echoes the limit in its own units - "192MB" of decimal megabytes
    comes back as "183.1 MiB" - so the number is parsed rather than the string
    compared. Asserting the rendering would make this a test of DuckDB's
    formatter, which is not what is in danger here.
    """
    con = next(gen)
    try:
        limit, threads = con.execute(
            "SELECT current_setting('memory_limit'), current_setting('threads')"
        ).fetchone()
    finally:
        gen.close()
    return float(limit.split()[0]), threads


def test_every_connection_is_bounded(warehouse, monkeypatch):
    """Per connection, because that is the only scope DuckDB has for these.
    Every request opens its own, so one unbounded path is unbounded everywhere."""
    monkeypatch.setattr(db, "MEMORY_LIMIT", "123MB")
    monkeypatch.setattr(db, "THREADS", "3")

    # Both doors into the warehouse, not just the one most endpoints use.
    assert _settings(db.get_db()) == _settings(db.get_db_optional())
    limit, threads = _settings(db.get_db())
    assert threads == 3
    assert 115 < limit < 120, f"123MB should land near 117 MiB, got {limit}"


def test_the_default_is_well_under_the_containers_budget(warehouse):
    """512 MB total, of which the Python process and the ONNX embedder take
    roughly 240 before DuckDB asks for anything."""
    limit, threads = _settings(db.get_db())

    assert threads == 2
    # Well under 512, and nowhere near the unbounded default, which on the
    # machine this was written on was 11.9 GiB.
    assert 150 < limit < 256, f"expected a couple of hundred MiB, got {limit}"


def test_the_limit_can_be_moved_without_a_deploy(warehouse, monkeypatch):
    """A running service that starts logging the warning below needs a lever
    that is not a code change."""
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "64MB")
    monkeypatch.setenv("DUCKDB_THREADS", "1")
    import importlib

    reloaded = importlib.reload(db)
    try:
        assert (reloaded.MEMORY_LIMIT, reloaded.THREADS) == ("64MB", "1")
    finally:
        monkeypatch.delenv("DUCKDB_MEMORY_LIMIT")
        monkeypatch.delenv("DUCKDB_THREADS")
        importlib.reload(db)


def test_running_out_of_memory_is_a_503_not_a_500(warehouse):
    """The limit stops the container being killed; this makes hitting it
    survivable. 503 is what the frontend already treats as "this block has
    nothing to say" (getScoreSettling), so the heavy endpoint goes quiet and the
    page stays up. As a 500 it would be an error boundary instead."""
    con = duckdb.connect(str(warehouse), read_only=True)
    con.execute("SET memory_limit='16MB'")
    con.execute("SET threads=2")
    try:
        with pytest.raises(HTTPException) as raised:
            # Wide enough to not fit: a self-join over a generated range.
            # Smallest shape that reliably exceeds 16MB: a sort it cannot
            # stream. Tuned down from 400000x400, which took 20s to fail.
            db.run_query(con, "SELECT a.range, b.range FROM range(200000) a, range(50) b "
                              "ORDER BY a.range DESC, b.range DESC")
    finally:
        con.close()

    assert raised.value.status_code == 503
    assert "memory" in raised.value.detail.lower()
