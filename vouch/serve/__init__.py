"""Server-side profile generation: the state the web app writes and the worker reads.

Split in two on purpose. ``db`` is the shared table — the only thing Next.js and Python
agree on — and ``worker`` is the loop that drains it. Nothing here judges, extracts or
renders; it queues, runs ``vouch.pipeline``, and records what came out.
"""
from vouch.serve.db import JobStatus, connect, db_path
from vouch.serve.worker import run_job, serve_forever

__all__ = ["JobStatus", "connect", "db_path", "run_job", "serve_forever"]
