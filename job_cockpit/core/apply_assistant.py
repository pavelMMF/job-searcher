from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agents import draft_job, workflow_from_store
from storage import Store


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
VENDOR = ROOT / "vendor"
BROWSERS = ROOT / "ms-playwright"
AUTOMATION_PYTHON = ROOT / ".automation_venv" / "Scripts" / "python.exe"
AUTOMATION_SCRIPT = ROOT / "automation" / "fill_application.py"
AUTO_QUEUE_SCRIPT = ROOT / "automation" / "auto_apply_queue.py"
PROFILE_DIR = ROOT / "browser_profiles" / "applications"
OUT_LOG = ROOT / "assist_apply.out.log"
ERR_LOG = ROOT / "assist_apply.err.log"
QUEUE_OUT_LOG = ROOT / "auto_apply_queue.out.log"
QUEUE_ERR_LOG = ROOT / "auto_apply_queue.err.log"
TERMINAL_STATUSES = {"applied", "skipped", "rejected"}

if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))


def playwright_installed() -> bool:
    if AUTOMATION_PYTHON.exists():
        try:
            result = subprocess.run(
                [str(AUTOMATION_PYTHON), "-c", "from playwright.async_api import async_playwright; print('ok')"],
                cwd=str(PROJECT_ROOT),
                text=True,
                capture_output=True,
                timeout=15,
            )
            return result.returncode == 0
        except Exception:  # noqa: BLE001
            return False
    return importlib.util.find_spec("playwright") is not None


def automation_python() -> str:
    return str(AUTOMATION_PYTHON if AUTOMATION_PYTHON.exists() else sys.executable)


def assisted_apply_status() -> dict[str, Any]:
    return {
        "playwright_installed": playwright_installed(),
        "profile_dir": str(PROFILE_DIR),
        "python": automation_python(),
        "logs": {
            "stdout": str(OUT_LOG),
            "stderr": str(ERR_LOG),
        },
        "mode": "visible_browser_human_final_submit",
    }


def next_apply_candidate(store: Store) -> dict[str, Any] | None:
    for job in store.list_jobs():
        if job.get("status") != "ready_to_apply":
            continue
        if not str(job.get("url") or "").strip():
            continue
        return job
    return None


def ensure_application_package(store: Store, job_id: int, *, force: bool = False) -> dict[str, Any]:
    job = store.get_job(job_id)
    status = str(job.get("status") or "new")
    if status in TERMINAL_STATUSES and not force:
        raise ValueError(f"Job #{job_id} is already {status}. Mark it Ready first if you want to reopen it.")

    has_text = bool(job.get("cover_letter") and job.get("draft_text"))
    has_resume = bool(job.get("resume_variant") or job.get("resume_attachment"))
    if force or not (has_text and has_resume):
        return draft_job(store, job_id, force_generate=force)
    return job


def launch_assisted_apply(store: Store, job_id: int, *, force: bool = False) -> dict[str, Any]:
    workflow = workflow_from_store(store)
    if not workflow.get("auto_fill_allowed", True):
        raise ValueError("Auto-fill is disabled in Workflow settings.")
    if not playwright_installed():
        raise RuntimeError(
            "Playwright is not installed. Run: python -m pip install -r job_cockpit/requirements-optional.txt "
            "and then: python -m playwright install chromium"
        )

    job = ensure_application_package(store, job_id, force=force)
    url = str(job.get("url") or "").strip()
    if not url:
        raise ValueError("This job has no application URL.")

    auto_submit = bool(workflow.get("auto_submit_allowed", False))
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        automation_python(),
        str(AUTOMATION_SCRIPT),
        "--db",
        str(ROOT / "cockpit.db"),
        "--job-id",
        str(job_id),
        "--url",
        url,
        "--user-data-dir",
        str(PROFILE_DIR),
        "--wait-mode",
        "none" if auto_submit else "browser",
        "--auto-open-apply",
    ]
    if auto_submit:
        command.extend(["--auto-submit-safe", "--mark-applied-on-submit"])
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS)
    with OUT_LOG.open("a", encoding="utf-8") as stdout, ERR_LOG.open("a", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            env=env,
            close_fds=False,
        )

    store.log(
        "info",
        f"Started assisted apply for {job.get('title', 'job')}",
        {"job_id": job_id, "pid": process.pid, "url": url, "profile_dir": str(PROFILE_DIR), "auto_submit": auto_submit},
    )
    message = (
        "Safe auto-submit launched. The job will be marked Applied only if the final submit click passes strict checks."
        if auto_submit
        else "Assisted apply browser launched. Review the page, solve CAPTCHA if shown, and click final submit yourself."
    )
    return {
        "ok": True,
        "pid": process.pid,
        "job": store.get_job(job_id),
        "profile_dir": str(PROFILE_DIR),
        "logs": {"stdout": str(OUT_LOG), "stderr": str(ERR_LOG)},
        "auto_submit": auto_submit,
        "message": message,
    }


def launch_next_assisted_apply(store: Store) -> dict[str, Any]:
    job = next_apply_candidate(store)
    if not job:
        raise LookupError("No Ready jobs with a URL are available. Run Wide Search, Draft, or mark a job Ready first.")
    return launch_assisted_apply(store, int(job["id"]))


def launch_auto_apply_queue(store: Store) -> dict[str, Any]:
    workflow = workflow_from_store(store)
    if not workflow.get("auto_fill_allowed", True):
        raise ValueError("Auto-fill is disabled in Workflow settings.")
    if not workflow.get("auto_submit_allowed", False):
        raise ValueError("Auto-submit is disabled in Workflow settings.")
    if not playwright_installed():
        raise RuntimeError(
            "Playwright is not installed. Run: python -m pip install --target job_cockpit/vendor "
            "-r job_cockpit/requirements-optional.txt"
        )
    limit = int(workflow.get("auto_submit_max_per_run", 5) or 5)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        automation_python(),
        str(AUTO_QUEUE_SCRIPT),
        "--db",
        str(ROOT / "cockpit.db"),
        "--user-data-dir",
        str(PROFILE_DIR),
        "--limit",
        str(max(1, min(limit, 25))),
    ]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS)
    with QUEUE_OUT_LOG.open("a", encoding="utf-8") as stdout, QUEUE_ERR_LOG.open("a", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            env=env,
            close_fds=False,
        )
    store.log(
        "info",
        "Started safe auto-apply queue",
        {"pid": process.pid, "limit": limit, "profile_dir": str(PROFILE_DIR)},
    )
    return {
        "ok": True,
        "pid": process.pid,
        "limit": limit,
        "profile_dir": str(PROFILE_DIR),
        "logs": {"stdout": str(QUEUE_OUT_LOG), "stderr": str(QUEUE_ERR_LOG)},
        "message": f"Safe auto-apply queue started for up to {limit} Ready jobs.",
    }
