from __future__ import annotations

import gc
import json
import tempfile
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from server import JobCockpitHandler, JobCockpitServer
from storage import Store


def request(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    payload = json.dumps(body or {}).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "smoke.db"
        store = Store(db_path)
        workflow = store.get_json_setting("workflow", {})
        workflow["always_generate_score"] = 999
        workflow["auto_generate_for_auto_apply_candidates"] = False
        store.set_json_setting("workflow", workflow)
        server = JobCockpitServer(("127.0.0.1", 0), JobCockpitHandler, store)
        port = server.server_address[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(port, "GET", "/api/state")
            assert status == 200, data
            state = json.loads(data)
            assert "profile" in state

            status, data = request(
                port,
                "POST",
                "/api/jobs",
                {
                    "title": "Data Analyst",
                    "company": "Acme",
                    "location": "Remote",
                    "raw_text": "Data Analyst role requiring Python, SQL, Tableau, and A/B testing experience.",
                },
            )
            assert status == 201, data
            created = json.loads(data)
            job_id = created["job"]["id"]

            status, data = request(port, "POST", f"/api/jobs/{job_id}/draft", {})
            assert status == 200, data
            drafted = json.loads(data)
            assert drafted["job"]["cover_letter"]

            status, data = request(port, "POST", f"/api/jobs/{job_id}/filler", {})
            assert status == 200, data
            filler = json.loads(data)
            assert "CAPTCHA" in filler["script"]

            status, data = request(port, "POST", f"/api/jobs/{job_id}/resume", {})
            assert status == 200, data
            resume = json.loads(data)
            assert resume["resume"]["relative_path"].endswith(".pdf")

            status, data = request(port, "GET", "/")
            assert status == 200, data
            assert b"Job Cockpit" in data
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            del server
            del store
            gc.collect()

    print("Smoke test passed")


if __name__ == "__main__":
    main()
