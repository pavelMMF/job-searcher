from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
CORE = ROOT / "core"
STATIC = ROOT / "static"
AUTOMATION_RUNS = ROOT.parent / "output" / "automation_runs"
sys.path.insert(0, str(CORE))

from agents import create_job, draft_job, run_agent  # noqa: E402
from apply_assistant import assisted_apply_status, launch_assisted_apply, launch_auto_apply_queue, launch_next_assisted_apply  # noqa: E402
from calendar_tools import build_ics, google_calendar_connector_status  # noqa: E402
from forms import build_fill_plan, build_filler_script  # noqa: E402
from llm_generator import openai_generation_status  # noqa: E402
from resume_generator import generate_resume_for_job  # noqa: E402
from storage import Store  # noqa: E402


def safe_console_write(message: str) -> None:
    try:
        print(message)
    except Exception:  # noqa: BLE001
        pass


def open_external_url(url: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(url)  # type: ignore[attr-defined]
        return
    webbrowser.open(url, new=2)


class JobCockpitHandler(BaseHTTPRequestHandler):
    server_version = "JobCockpit/0.1"

    @property
    def store(self) -> Store:
        return self.server.store  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.respond_json({"ok": True})
            return
        if parsed.path == "/api/state":
            self.respond_json(self.get_state())
            return
        if parsed.path == "/api/export/jobs.csv":
            self.respond_text(
                self.store.export_jobs_csv(),
                content_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="job-cockpit-jobs.csv"'},
            )
            return
        if parsed.path == "/api/calendar/interviews.ics":
            self.respond_text(
                build_ics(self.store.list_meetings()),
                content_type="text/calendar; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="job-cockpit-interviews.ics"'},
            )
            return
        if parsed.path.startswith("/api/resumes/"):
            self.serve_resume(parsed.path)
            return
        if parsed.path.startswith("/api/automation-runs/"):
            self.serve_automation_run(parsed.path)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            body = self.read_json()
            if path == "/api/open-url":
                self.handle_open_url(body)
                return
            if path == "/api/profile":
                self.store.set_json_setting("profile", body)
                self.store.log("info", "Updated profile")
                self.respond_json(self.get_state())
                return
            if path == "/api/workflow":
                self.store.set_json_setting("workflow", body)
                self.store.log("info", "Updated workflow settings")
                self.respond_json(self.get_state())
                return
            if path == "/api/sources":
                self.store.set_json_setting("sources", body.get("sources", []))
                self.store.log("info", "Updated job sources")
                self.respond_json(self.get_state())
                return
            if path == "/api/jobs":
                job = create_job(self.store, body)
                self.respond_json({"job": job, "state": self.get_state()}, status=HTTPStatus.CREATED)
                return
            if path.startswith("/api/jobs/"):
                self.handle_job_action(path, body)
                return
            if path == "/api/agents/run":
                result = run_agent(self.store, body.get("mode", "daily_review"))
                self.respond_json({"ok": result.ok, "message": result.message, "payload": result.payload, "state": self.get_state()})
                return
            if path == "/api/apply/next":
                self.handle_assisted_apply_next()
                return
            if path == "/api/apply/auto_queue":
                self.handle_auto_apply_queue()
                return
            if path == "/api/meetings":
                meeting = self.store.create_meeting(body)
                self.store.log("info", f"Added meeting: {meeting['title']}", {"meeting_id": meeting["id"]})
                self.respond_json({"meeting": meeting, "state": self.get_state()}, status=HTTPStatus.CREATED)
                return
            if path == "/api/activity/clear":
                self.store.clear_activity()
                self.respond_json(self.get_state())
                return
            self.respond_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except KeyError as exc:
            self.respond_error(HTTPStatus.NOT_FOUND, str(exc))
        except json.JSONDecodeError:
            self.respond_error(HTTPStatus.BAD_REQUEST, "Invalid JSON body")
        except Exception as exc:  # noqa: BLE001
            self.store.log("error", "Request failed", {"error": str(exc), "path": path})
            self.respond_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def handle_open_url(self, body: dict) -> None:
        url = str(body.get("url", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.respond_error(HTTPStatus.BAD_REQUEST, "Only http/https URLs can be opened")
            return
        open_external_url(url)
        self.store.log("info", "Opened job URL in default browser", {"url": url})
        self.respond_json({"ok": True})

    def handle_job_action(self, path: str, body: dict) -> None:
        parts = path.split("/")
        if len(parts) < 4:
            self.respond_error(HTTPStatus.NOT_FOUND, "Missing job id")
            return
        job_id = int(parts[3])
        action = parts[4] if len(parts) > 4 else ""
        if action == "draft":
            job = draft_job(self.store, job_id, force_generate=bool(body.get("force_generate", False)))
            self.respond_json({"job": job, "state": self.get_state()})
            return
        if action == "status":
            status = body.get("status", "reviewed")
            job = self.store.update_job(job_id, {"status": status})
            self.store.log("info", f"Set job #{job_id} status to {status}", {"job_id": job_id, "status": status})
            self.respond_json({"job": job, "state": self.get_state()})
            return
        if action == "filler":
            profile = self.store.get_json_setting("profile", {})
            job = self.store.get_job(job_id)
            self.respond_json(
                {
                    "plan": build_fill_plan(profile, job),
                    "script": build_filler_script(profile, job),
                }
            )
            return
        if action == "assist_apply":
            self.handle_assisted_apply_job(job_id, body)
            return
        if action == "resume":
            result = generate_resume_for_job(self.store, job_id)
            self.respond_json({"resume": result, "state": self.get_state()})
            return
        self.respond_error(HTTPStatus.NOT_FOUND, "Unknown job action")

    def handle_assisted_apply_job(self, job_id: int, body: dict) -> None:
        try:
            result = launch_assisted_apply(self.store, job_id, force=bool(body.get("force")))
        except RuntimeError as exc:
            self.respond_json({"ok": False, "error": str(exc), "state": self.get_state()}, status=HTTPStatus.CONFLICT)
            return
        except ValueError as exc:
            self.respond_json({"ok": False, "error": str(exc), "state": self.get_state()}, status=HTTPStatus.BAD_REQUEST)
            return
        self.respond_json({**result, "state": self.get_state()})

    def handle_assisted_apply_next(self) -> None:
        try:
            result = launch_next_assisted_apply(self.store)
        except RuntimeError as exc:
            self.respond_json({"ok": False, "error": str(exc), "state": self.get_state()}, status=HTTPStatus.CONFLICT)
            return
        except LookupError as exc:
            self.respond_json({"ok": False, "error": str(exc), "state": self.get_state()}, status=HTTPStatus.NOT_FOUND)
            return
        except ValueError as exc:
            self.respond_json({"ok": False, "error": str(exc), "state": self.get_state()}, status=HTTPStatus.BAD_REQUEST)
            return
        self.respond_json({**result, "state": self.get_state()})

    def handle_auto_apply_queue(self) -> None:
        try:
            result = launch_auto_apply_queue(self.store)
        except RuntimeError as exc:
            self.respond_json({"ok": False, "error": str(exc), "state": self.get_state()}, status=HTTPStatus.CONFLICT)
            return
        except ValueError as exc:
            self.respond_json({"ok": False, "error": str(exc), "state": self.get_state()}, status=HTTPStatus.BAD_REQUEST)
            return
        self.respond_json({**result, "state": self.get_state()})

    def get_state(self) -> dict:
        workflow = self.store.get_json_setting("workflow", {})
        return {
            "profile": self.store.get_json_setting("profile", {}),
            "workflow": workflow,
            "sources": self.store.get_json_setting("sources", []),
            "jobs": self.store.list_jobs(),
            "meetings": self.store.list_meetings(),
            "activity": self.store.list_activity(),
            "auto_applications": self.store.list_auto_applications(),
            "calendar": google_calendar_connector_status(),
            "assisted_apply": assisted_apply_status(),
            "openai_generation": openai_generation_status(self.store),
            "safety": {
                "captcha": "human_handoff",
                "auto_submit": bool(workflow.get("auto_submit_allowed", False)),
                "message": "The cockpit can safe-submit only fully recognized forms. CAPTCHA, security, consent, demographic, and unknown required fields still stop automation.",
            },
        }

    def serve_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            target = STATIC / "index.html"
        else:
            target = (STATIC / request_path.lstrip("/")).resolve()
            try:
                target.relative_to(STATIC.resolve())
            except ValueError:
                self.respond_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
        if not target.exists() or not target.is_file():
            self.respond_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_resume(self, request_path: str) -> None:
        filename = request_path.rsplit("/", 1)[-1]
        target = (ROOT.parent / "output" / "pdf" / filename).resolve()
        allowed = (ROOT.parent / "output" / "pdf").resolve()
        try:
            target.relative_to(allowed)
        except ValueError:
            self.respond_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not target.exists() or not target.is_file():
            self.respond_error(HTTPStatus.NOT_FOUND, "Resume not found")
            return
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_automation_run(self, request_path: str) -> None:
        filename = request_path.rsplit("/", 1)[-1]
        target = (AUTOMATION_RUNS / filename).resolve()
        allowed = AUTOMATION_RUNS.resolve()
        try:
            target.relative_to(allowed)
        except ValueError:
            self.respond_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not target.exists() or not target.is_file():
            self.respond_error(HTTPStatus.NOT_FOUND, "Automation run not found")
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/json"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if target.suffix.lower() == ".json":
            self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def respond_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def respond_text(self, text: str, content_type: str = "text/plain; charset=utf-8", headers: dict | None = None) -> None:
        payload = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def respond_error(self, status: HTTPStatus, message: str) -> None:
        self.respond_json({"ok": False, "error": message}, status=status)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        try:
            sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))
        except Exception:  # noqa: BLE001
            pass


class JobCockpitServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], store: Store) -> None:
        super().__init__(server_address, handler_class)
        self.store = store


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Job Cockpit local dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(ROOT / "cockpit.db"))
    args = parser.parse_args()

    store = Store(args.db)
    server = JobCockpitServer((args.host, args.port), JobCockpitHandler, store)
    safe_console_write(f"Job Cockpit running at http://{args.host}:{args.port}")
    safe_console_write("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        safe_console_write("\nStopping Job Cockpit.")
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        try:
            import traceback

            (ROOT / "server.crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise
