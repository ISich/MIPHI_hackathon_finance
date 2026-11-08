"""Command line: serve | worker | register-dataset | export-openapi."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .settings import LOOPBACK_HOSTS, load_settings


def _serve(args) -> int:
    import os

    import uvicorn
    settings = load_settings()
    if args.host not in LOOPBACK_HOSTS:
        if settings.execution_mode == "trusted-local":
            print("refusing to start: trusted-local execution is allowed on loopback only", file=sys.stderr)
            return 2
        if not args.allow_non_loopback:
            print("refusing to bind a non-loopback host without --allow-non-loopback (operator decision)", file=sys.stderr)
            return 2
    if settings.execution_mode == "trusted-local":
        print("WARNING: trusted-local mode: user Python runs with this server user's rights. "
              "Not a sandbox. Do not expose.", file=sys.stderr)
    if settings.sandboxed:
        print("NOTE: sandboxed mode: user Python runs under Landlock + seccomp (no network/exec/fork, "
              "own run files only); self-test runs at startup", file=sys.stderr)
    if not settings.cookie_secure:
        print("NOTE: local HTTP mode: session cookie without Secure flag (set DD_COOKIE_SECURE=1 behind TLS)", file=sys.stderr)
    os.environ["DD_BIND_HOST"] = args.host
    uvicorn.run("dd_backend.app:create_app", factory=True, host=args.host, port=args.port, log_level="info",
                proxy_headers=False, server_header=False)
    return 0


def _worker(args) -> int:
    from .db import Database
    from .registry import Registry
    from .worker import Worker
    settings = load_settings()
    if settings.sandboxed:
        from . import sandbox
        try:
            sandbox.require_working(settings.home / "sandbox-selftest")
        except sandbox.SandboxError as exc:
            print(f"refusing to start: {exc}", file=sys.stderr)
            return 2
    db = Database(settings.db_path)
    db.init()
    Registry(settings, db).sync_builtin_scripts()
    logging.basicConfig(level=logging.INFO)
    print(f"worker started (mode={settings.execution_mode})", file=sys.stderr, flush=True)
    Worker(settings, db).run_forever()
    return 0


def _register(args) -> int:
    from .db import Database
    from .errors import ApiError
    from .registry import Registry
    settings = load_settings()
    db = Database(settings.db_path)
    db.init()
    try:
        ds = Registry(settings, db).create_dataset(None, args.name, args.root, args.mode, args.before, args.after)
    except ApiError as exc:
        print(json.dumps({"code": exc.code, "message": exc.message, "details": exc.details}), file=sys.stderr)
        return 1
    print(json.dumps(ds, indent=1, ensure_ascii=False))
    return 0


def _release(args) -> int:
    """Operator escape hatch for a fail-closed job (EXECUTION_UNCONTAINED)."""
    from .db import Database
    from .runs import append_event
    from .worker import Worker, kill_marked
    if not args.confirm_no_processes:
        print("refusing: verify on the host that no process of this execution is alive, then pass "
              "--confirm-no-processes", file=sys.stderr)
        return 2
    settings = load_settings()
    db = Database(settings.db_path)
    db.init()
    job = db.one("SELECT * FROM jobs WHERE ref_id = ? AND status = 'RUNNING'", (args.ref,))
    if job is None:
        print("no RUNNING job with this ref", file=sys.stderr)
        return 1
    if job["exec_mark"]:
        left = kill_marked(job["exec_mark"], None)
        if left:
            print(f"refusing: {left} processes with this execution mark are still alive", file=sys.stderr)
            return 1
    w = Worker(settings, db)
    msg = "Released by operator after manual verification that no execution process is alive"
    with db.tx() as con:
        table, key = ("runs", "run_id") if job["kind"] == "DATA_RUN" else ("check_runs", "check_run_id")
        status = con.execute(f"SELECT status FROM {table} WHERE {key} = ?", (args.ref,)).fetchone()[0]
        if status not in ("COMPLETED", "FAILED"):
            if job["kind"] == "DATA_RUN":
                w._fail_run_tx(con, args.ref, "EXECUTION_UNCONTAINED", msg)
            else:
                w._fail_check_run_tx(con, args.ref, "EXECUTION_UNCONTAINED", msg)
        con.execute("UPDATE jobs SET status = 'DONE' WHERE job_seq = ?", (job["job_seq"],))
        run_id = args.ref if job["kind"] == "DATA_RUN" else con.execute(
            "SELECT run_id FROM check_runs WHERE check_run_id = ?", (args.ref,)).fetchone()[0]
        append_event(con, run_id, "WARN", msg)
    print(f"released {args.ref}")
    return 0


def _openapi(args) -> int:
    from .app import create_app
    spec = create_app().openapi()
    text = json.dumps(spec, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m dd_backend")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="HTTP API (with embedded worker unless DD_EMBEDDED_WORKER=0)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--allow-non-loopback", action="store_true")
    s.set_defaults(fn=_serve)
    w = sub.add_parser("worker", help="standalone worker process (use with DD_EMBEDDED_WORKER=0 on the server)")
    w.set_defaults(fn=_worker)
    r = sub.add_parser("register-dataset", help="register a shared (system) dataset from an allowlisted root")
    r.add_argument("--name", required=True)
    r.add_argument("--root", required=True)
    r.add_argument("--mode", choices=["files", "dirs"], required=True)
    r.add_argument("--before", required=True)
    r.add_argument("--after", required=True)
    r.set_defaults(fn=_register)
    rel = sub.add_parser("release-job", help="release a fail-closed job after manually verifying no process survives")
    rel.add_argument("--ref", required=True, help="run_id or check_run_id")
    rel.add_argument("--confirm-no-processes", action="store_true")
    rel.set_defaults(fn=_release)
    o = sub.add_parser("export-openapi")
    o.add_argument("--out")
    o.set_defaults(fn=_openapi)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
