from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
VENDOR = ROOT / "vendor"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "ms-playwright"))
sys.path.insert(0, str(CORE))

from storage import Store  # noqa: E402


TERMINAL_STATUSES = {"applied", "skipped", "rejected"}
FILL_APPLICATION = ROOT / "automation" / "fill_application.py"


def ready_jobs(store: Store, limit: int) -> list[dict[str, Any]]:
    jobs = []
    for job in store.list_jobs():
        if len(jobs) >= limit:
            break
        if job.get("status") in TERMINAL_STATUSES:
            continue
        if job.get("status") != "ready_to_apply":
            continue
        if not str(job.get("url") or "").strip():
            continue
        jobs.append(job)
    return jobs


async def run_queue(args: argparse.Namespace) -> int:
    store = Store(args.db)
    workflow = store.get_json_setting("workflow", {})
    if not workflow.get("auto_submit_allowed", False):
        print("Auto-submit is disabled in Workflow settings.")
        return 2

    jobs = ready_jobs(store, args.limit)
    if not jobs:
        print("No Ready jobs with URL.")
        return 0

    submitted = 0
    skipped = 0
    print(f"Python: {sys.executable}")
    print(f"Vendor: {VENDOR} exists={VENDOR.exists()}")
    print(f"Browsers: {os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')}")
    print("Runner mode: subprocess-per-job")
    print(f"Safe auto-apply queue started: {len(jobs)} candidate(s).")
    for job in jobs:
        job_id = int(job["id"])
        print(f"Processing #{job_id}: {job.get('title', '')} at {job.get('company', '')}")
        before = store.get_job(job_id).get("status")
        code, output = run_fill_application(args, job)
        after = store.get_job(job_id).get("status")
        audit_path = extract_audit_path(output)
        if code == 0 and after == "applied" and before != "applied":
            submitted += 1
            if not args.dry_run_import_only:
                store.log(
                    "info",
                    f"Auto-applied job #{job_id}",
                    {
                        "job_id": job_id,
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "audit_path": audit_path,
                    },
                )
        else:
            skipped += 1
            if not args.dry_run_import_only:
                store.log(
                    "warning",
                    f"Auto-apply needs review for job #{job_id}",
                    {
                        "job_id": job_id,
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "reason": summarize_output(output) or f"exit code {code}",
                        "audit_path": audit_path,
                    },
                )
        await asyncio.sleep(max(1, args.pause_seconds))

    activity_message = "Playwright dry-run import check finished" if args.dry_run_import_only else "Safe auto-apply queue finished"
    store.log("info", activity_message, {"submitted": submitted, "skipped": skipped, "dry_run": bool(args.dry_run_import_only)})
    print(f"Safe auto-apply queue finished. submitted={submitted}, skipped_or_needs_human={skipped}")
    return 0


def run_fill_application(args: argparse.Namespace, job: dict[str, Any]) -> tuple[int, str]:
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "ms-playwright")
    if args.dry_run_import_only:
        command = [
            sys.executable,
            "-c",
            "import playwright; import playwright.async_api; print(playwright.__file__)",
        ]
        completed = subprocess.run(command, cwd=str(ROOT.parent), env=env, text=True, capture_output=True, timeout=30)
        if completed.stdout:
            print(completed.stdout.rstrip())
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr)
        return int(completed.returncode), "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    command = [
        sys.executable,
        str(FILL_APPLICATION),
        "--db",
        args.db,
        "--job-id",
        str(job["id"]),
        "--url",
        str(job.get("url") or ""),
        "--user-data-dir",
        args.user_data_dir,
        "--wait-mode",
        "none",
        "--no-wait",
        "--auto-open-apply",
        "--auto-submit-safe",
        "--mark-applied-on-submit",
    ]
    if args.headless:
        command.append("--headless")
    if args.slow_mo:
        command.extend(["--slow-mo", str(args.slow_mo)])
    print("Child command:", " ".join(command))
    completed = subprocess.run(
        command,
        cwd=str(ROOT.parent),
        env=env,
        text=True,
        capture_output=True,
        timeout=args.job_timeout_seconds,
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    return int(completed.returncode), "\n".join(part for part in [completed.stdout, completed.stderr] if part)


def summarize_output(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if "Auto-submit:" in line:
            return line.split("Auto-submit:", 1)[1].strip()
    for line in reversed(lines):
        if line.startswith("Navigation failed:"):
            return line
    for line in reversed(lines):
        if "TargetClosedError" in line or "Target page" in line:
            return "browser/page closed during navigation"
        if "net::ERR_ABORTED" in line:
            return "navigation aborted by target site"
    for line in reversed(lines):
        if "Page.goto:" in line or "Traceback" in line or "Import error:" in line:
            return line[:220]
    return lines[-1][:220] if lines else ""


def extract_audit_path(output: str) -> str:
    for line in reversed([line.strip() for line in output.splitlines() if line.strip()]):
        if line.startswith("AUDIT_PATH:"):
            return line.split("AUDIT_PATH:", 1)[1].strip()
    return ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run safe auto-submit over Ready jobs.")
    parser.add_argument("--db", default=str(ROOT / "cockpit.db"))
    parser.add_argument("--user-data-dir", default=str(ROOT / "browser_profiles" / "applications"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--pause-seconds", type=int, default=2)
    parser.add_argument("--job-timeout-seconds", type=int, default=120)
    parser.add_argument("--dry-run-import-only", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--slow-mo", type=int, default=0)
    return parser


def main() -> None:
    raise SystemExit(asyncio.run(run_queue(build_parser().parse_args())))


if __name__ == "__main__":
    main()
