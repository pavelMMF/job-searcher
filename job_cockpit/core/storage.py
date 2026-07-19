from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "cockpit.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


DEFAULT_PROFILE: dict[str, Any] = {
    "first_name": "",
    "last_name": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin_url": "",
    "github_url": "",
    "portfolio_url": "",
    "resume_path": "",
    "target_titles": [
        "Data Analyst",
        "Middle Data Analyst",
        "Mid Data Analyst",
        "Senior Data Analyst",
        "Product Analyst",
        "Middle Product Analyst",
        "Product Affiliate Analyst",
        "Senior Product Analyst",
        "Affiliate Data Analyst",
        "Middle Affiliate Data Analyst",
        "Senior Affiliate Data Analyst",
        "Growth Analyst",
        "Retention Analyst",
        "BI Analyst",
        "Senior BI Analyst",
        "Analytics Engineer",
        "Data Scientist",
        "Middle Data Scientist",
        "Mid Data Scientist",
    ],
    "target_locations": ["Remote", "Germany", "Netherlands", "United Kingdom", "United States"],
    "skills": [
        "Python",
        "SQL",
        "pandas",
        "statistics",
        "A/B testing",
        "Tableau",
        "Power BI",
        "machine learning",
    ],
    "avoid_keywords": ["unpaid", "commission only", "door to door"],
    "work_authorization": "",
    "salary_expectation": "",
    "notice_period": "",
    "summary": "",
}


# Fallback only; the real path comes from standard_resume_path in master_resume.json.
DEFAULT_STANDARD_RESUME_PATH = ""


DEFAULT_WORKFLOW: dict[str, Any] = {
    "min_score_to_prepare": 68,
    "max_new_jobs_per_run": 35,
    "submit_mode": "manual_final_submit",
    "captcha_policy": "human_handoff",
    "auto_fill_allowed": True,
    "auto_submit_allowed": False,
    "auto_submit_safe_only": True,
    "auto_submit_max_per_run": 5,
    "auto_generate_resume": True,
    "auto_generate_cover_letter": True,
    "llm_generate_application_package": True,
    "llm_model": "gpt-4.1-nano",
    "llm_timeout_seconds": 45,
    "llm_max_description_chars": 4500,
    "llm_autofill_screening_questions": True,
    "llm_autofill_mode": "aggressive_safe",
    "llm_autofill_min_confidence": 0.65,
    "llm_autofill_max_fields": 8,
    "auto_fill_eeo_from_answers": True,
    "auto_fill_legal_consent_from_answers": True,
    "auto_generate_for_auto_apply_candidates": True,
    "always_generate_score": 100,
    "auto_package_ready_jobs": True,
    "search_queries": [
        "data analyst",
        "middle data analyst",
        "mid data analyst",
        "senior data analyst",
        "product analyst",
        "middle product analyst",
        "mid product analyst",
        "product affiliate analyst",
        "senior product analyst",
        "product data analyst",
        "affiliate data analyst",
        "middle affiliate data analyst",
        "mid affiliate data analyst",
        "senior affiliate data analyst",
        "affiliate analyst",
        "growth analyst",
        "retention analyst",
        "crm analyst",
        "lifecycle analyst",
        "monetization analyst",
        "customer analytics analyst",
        "traffic analyst",
        "traffic data analyst",
        "traffic analytics analyst",
        "marketing analyst",
        "marketing analytics analyst",
        "marketing data analyst",
        "performance marketing analyst",
        "bi analyst",
        "analytics engineer",
        "product data scientist",
        "growth data scientist",
        "middle data scientist",
        "mid data scientist",
        "data scientist mid",
        "data scientist middle",
    ],
    "target_seniority": [
        "mid",
        "senior",
        "lead",
        "principal",
        "staff",
    ],
    "exclude_entry_level": True,
    "demote_ready_below_threshold": True,
    "focus_role_families": [
        "data_analytics",
        "data_science",
    ],
    "remote_only": True,
    "search_locations": [
        "remote",
    ],
    "blocked_source_domains": [
        "weworkremotely.com",
        "remoteok.com",
    ],
    "blocked_source_names": [
        "We Work Remotely RSS",
        "RemoteOK",
    ],
}


DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "name": "Remotive remote jobs",
        "kind": "remotive_api",
        "enabled": True,
        "url": "https://remotive.com/api/remote-jobs",
        "notes": "Public remote job API. Uses workflow search_queries.",
    },
    {
        "name": "Arbeitnow job board",
        "kind": "arbeitnow_api",
        "enabled": True,
        "url": "https://www.arbeitnow.com/api/job-board-api",
        "notes": "Public job API with remote and Europe-friendly roles.",
    },
    {
        "name": "Jobicy remote jobs",
        "kind": "jobicy_api",
        "enabled": True,
        "url": "https://jobicy.com/api/v2/remote-jobs",
        "notes": "Public remote jobs API. Good for Europe/EMEA and Data Science & Analytics.",
    },
    {
        "name": "Himalayas remote jobs",
        "kind": "himalayas_api",
        "enabled": True,
        "url": "https://himalayas.app/jobs/api",
        "notes": "Public remote jobs API. Filters locally by target role and geography.",
    },
    {
        "name": "RemoteOK",
        "kind": "remoteok_api",
        "enabled": False,
        "url": "https://remoteok.com/api",
        "notes": "Disabled by preference. Enable manually only if you want RemoteOK roles.",
    },
    {
        "name": "We Work Remotely RSS",
        "kind": "rss",
        "enabled": False,
        "url": "https://weworkremotely.com/remote-jobs.rss",
        "notes": "Disabled by preference. Enable manually only if you want We Work Remotely roles.",
    },
    {
        "name": "Jobicy Data Science RSS",
        "kind": "rss",
        "enabled": True,
        "url": "https://jobicy.com/feed/job_feed?job_categories=data-science&job_types=full-time",
        "notes": "Jobicy RSS focused on Data Science & Analytics.",
    },
    {
        "name": "LinkedIn assisted search",
        "kind": "linkedin_assisted",
        "enabled": False,
        "url": "https://www.linkedin.com/jobs/search/",
        "notes": "Use automation/linkedin_collect.py. You log in locally; the server does not scrape LinkedIn in the background.",
    },
    {
        "name": "HiringCafe manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://hiring.cafe/",
        "notes": "Large remote/international job search. Use manually or as browser-assisted target.",
    },
    {
        "name": "FlexJobs manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://www.flexjobs.com/",
        "notes": "Remote-focused board, account/subscription based.",
    },
    {
        "name": "Working Nomads manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://www.workingnomads.com/jobs",
        "notes": "Remote/digital-nomad roles.",
    },
    {
        "name": "NoDesk manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://nodesk.co/remote-jobs/",
        "notes": "Remote-first job board.",
    },
    {
        "name": "Remote.co manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://remote.co/remote-jobs/data/",
        "notes": "Remote job board. Enable if HTML access works reliably.",
    },
    {
        "name": "DailyRemote data jobs",
        "kind": "public_html",
        "enabled": True,
        "url": "https://dailyremote.com/remote-data-jobs",
        "notes": "Remote-focused board with data roles. Uses generic public HTML link discovery.",
    },
    {
        "name": "EU Remote Jobs data",
        "kind": "public_html",
        "enabled": True,
        "url": "https://euremotejobs.com/remote-data-jobs",
        "notes": "Europe-friendly remote roles. Uses generic public HTML link discovery.",
    },
    {
        "name": "Startup Jobs remote data",
        "kind": "public_html",
        "enabled": True,
        "url": "https://startup.jobs/remote-data-jobs",
        "notes": "Startup-focused remote data listings. Uses generic public HTML link discovery.",
    },
    {
        "name": "Built In remote data analytics",
        "kind": "career_page",
        "enabled": False,
        "url": "https://builtin.com/jobs/remote/data-analytics",
        "notes": "Remote data and analytics jobs. Enable if HTML access works reliably.",
    },
    {
        "name": "JustRemote data jobs",
        "kind": "career_page",
        "enabled": False,
        "url": "https://justremote.co/remote-data-jobs",
        "notes": "Remote job board; may require manual review depending on page rendering.",
    },
    {
        "name": "Remote Rocketship data jobs",
        "kind": "career_page",
        "enabled": False,
        "url": "https://www.remoterocketship.com/jobs/data-analyst",
        "notes": "Remote/international job board. Enable if HTML access works reliably.",
    },
    {
        "name": "PowerToFly data jobs",
        "kind": "career_page",
        "enabled": False,
        "url": "https://powertofly.com/jobs/",
        "notes": "International tech board; best used manually or with site search filters.",
    },
    {
        "name": "YC Work at a Startup",
        "kind": "career_page",
        "enabled": False,
        "url": "https://www.ycombinator.com/jobs",
        "notes": "Startup jobs with remote filters available on-site; generic discovery may be limited.",
    },
    {
        "name": "Landing.Jobs remote data",
        "kind": "career_page",
        "enabled": False,
        "url": "https://landing.jobs/jobs?remote=true",
        "notes": "Europe-friendly tech jobs. Use manually or enable for public HTML discovery.",
    },
    {
        "name": "Honeypot remote jobs",
        "kind": "career_page",
        "enabled": False,
        "url": "https://www.honeypot.io/jobs",
        "notes": "Europe tech jobs; mostly account-based, useful as a manual/assisted source.",
    },
    {
        "name": "Arc.dev manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://arc.dev/remote-jobs",
        "notes": "Remote tech jobs, often account-based.",
    },
    {
        "name": "Turing manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://www.turing.com/jobs",
        "notes": "Global remote tech marketplace, account-based.",
    },
    {
        "name": "Contra manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://contra.com/jobs",
        "notes": "Remote freelance/contract marketplace.",
    },
    {
        "name": "Wellfound manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://wellfound.com/jobs",
        "notes": "Startup jobs, often needs login; use as manual/assisted target.",
    },
    {
        "name": "Otta manual",
        "kind": "career_page",
        "enabled": False,
        "url": "https://app.otta.com/",
        "notes": "International tech jobs, account-based; use manually.",
    },
    {
        "name": "Manual intake",
        "kind": "manual",
        "enabled": True,
        "notes": "Paste job URLs or descriptions into the cockpit.",
    }
]


def load_default_resume_master() -> dict[str, Any]:
    path = ROOT_DIR / "config" / "master_resume.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def profile_from_resume_master(master: dict[str, Any]) -> dict[str, Any]:
    profile = dict(DEFAULT_PROFILE)
    name_parts = str(master.get("name", "")).split()
    contacts = master.get("contacts", {})
    skills = master.get("skills", {})
    profile.update(
        {
            "first_name": name_parts[0] if name_parts else "",
            "last_name": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
            "email": contacts.get("email", ""),
            "phone": contacts.get("phone", ""),
            "location": contacts.get("location", ""),
            "resume_path": master.get("standard_resume_path", DEFAULT_STANDARD_RESUME_PATH),
            "work_authorization": contacts.get("work_authorization", ""),
            "summary": master.get("summary", ""),
            "skills": list(
                dict.fromkeys(
                    list(skills.get("tools", []))
                    + list(skills.get("analytics", []))
                    + list(skills.get("engineering", []))
                    + list(skills.get("data_science", []))
                )
            ),
        }
    )
    return profile


class Store:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT DEFAULT '',
                    source_url TEXT DEFAULT '',
                    title TEXT NOT NULL,
                    company TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    remote TEXT DEFAULT '',
                    salary TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    requirements TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'new',
                    match_score INTEGER DEFAULT 0,
                    match_notes TEXT DEFAULT '',
                    draft_text TEXT DEFAULT '',
                    cover_letter TEXT DEFAULT '',
                    resume_variant TEXT DEFAULT '',
                    resume_attachment TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    title TEXT NOT NULL,
                    company TEXT DEFAULT '',
                    starts_at TEXT NOT NULL,
                    ends_at TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    status TEXT DEFAULT 'scheduled',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );

                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    meta TEXT DEFAULT '{}'
                );
                """
            )
            self.ensure_job_columns(conn)
        self.ensure_defaults()
        self.ensure_resume_attachments()

    def ensure_job_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "resume_attachment" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN resume_attachment TEXT DEFAULT ''")

    def ensure_resume_attachments(self) -> None:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, resume_variant
                FROM jobs
                WHERE COALESCE(resume_variant, '') != ''
                  AND COALESCE(resume_attachment, '') = ''
                """
            ).fetchall()
            for row in rows:
                attachment = str((ROOT_DIR.parent / row["resume_variant"]).resolve())
                conn.execute("UPDATE jobs SET resume_attachment = ?, updated_at = ? WHERE id = ?", (attachment, now_iso(), row["id"]))

    def ensure_defaults(self) -> None:
        master = self.get_json_setting("resume_master") or load_default_resume_master()
        if self.get_setting("resume_master") is None:
            self.set_json_setting("resume_master", master)
        if self.get_setting("profile") is None:
            self.set_json_setting("profile", profile_from_resume_master(master) if master else DEFAULT_PROFILE)
        elif master:
            profile = self.get_json_setting("profile", {})
            hydrated = profile_from_resume_master(master)
            changed = False
            for key in ("first_name", "last_name", "email", "phone", "location", "work_authorization", "summary"):
                if not profile.get(key) and hydrated.get(key):
                    profile[key] = hydrated[key]
                    changed = True
            if not profile.get("skills") and hydrated.get("skills"):
                profile["skills"] = hydrated["skills"]
                changed = True
            if changed:
                self.set_json_setting("profile", profile)
        if self.get_setting("workflow") is None:
            self.set_json_setting("workflow", DEFAULT_WORKFLOW)
        else:
            workflow = self.get_json_setting("workflow", {})
            merged = {**DEFAULT_WORKFLOW, **workflow}
            if workflow.get("min_score_to_prepare") in {60, 72}:
                merged["min_score_to_prepare"] = DEFAULT_WORKFLOW["min_score_to_prepare"]
            old_query_defaults = {"data analyst", "product analyst", "bi analyst", "data scientist"}
            current_queries = {str(item).lower() for item in merged.get("search_queries", [])}
            if current_queries and current_queries.issubset(old_query_defaults):
                merged["search_queries"] = DEFAULT_WORKFLOW["search_queries"]
            old_region_defaults = {"remote", "emea", "europe", "germany", "netherlands", "united kingdom"}
            current_locations = {str(item).lower() for item in merged.get("search_locations", [])}
            if current_locations and current_locations.issubset(old_region_defaults):
                merged["search_locations"] = DEFAULT_WORKFLOW["search_locations"]
            if workflow.get("llm_model") in {"", "gpt-5.4-nano"}:
                merged["llm_model"] = DEFAULT_WORKFLOW["llm_model"]
            if workflow.get("llm_max_description_chars") in {7000, None}:
                merged["llm_max_description_chars"] = DEFAULT_WORKFLOW["llm_max_description_chars"]
            if workflow.get("llm_autofill_max_fields") in {12, None}:
                merged["llm_autofill_max_fields"] = DEFAULT_WORKFLOW["llm_autofill_max_fields"]
            if merged != workflow:
                self.set_json_setting("workflow", merged)
        if self.get_setting("sources") is None:
            self.set_json_setting("sources", DEFAULT_SOURCES)
        else:
            sources = self.get_json_setting("sources", [])
            existing_names = {str(source.get("name", "")) for source in sources}
            merged_sources = list(sources)
            changed = False
            for source in DEFAULT_SOURCES:
                if source["name"] not in existing_names:
                    merged_sources.append(source)
                    changed = True
            if changed:
                self.set_json_setting("sources", merged_sources)

    def get_setting(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now_iso()),
            )

    def get_json_setting(self, key: str, default: Any = None) -> Any:
        value = self.get_setting(key)
        if value is None:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def set_json_setting(self, key: str, value: Any) -> None:
        self.set_setting(key, json.dumps(value, ensure_ascii=False, indent=2))

    def create_job(self, data: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_iso()
        fields = {
            "source": data.get("source", ""),
            "source_url": data.get("source_url", ""),
            "title": data.get("title") or "Untitled role",
            "company": data.get("company", ""),
            "location": data.get("location", ""),
            "remote": data.get("remote", ""),
            "salary": data.get("salary", ""),
            "url": data.get("url", ""),
            "description": data.get("description", ""),
            "requirements": json.dumps(data.get("requirements", []), ensure_ascii=False),
            "status": data.get("status", "new"),
            "match_score": int(data.get("match_score", 0) or 0),
            "match_notes": data.get("match_notes", ""),
            "draft_text": data.get("draft_text", ""),
            "cover_letter": data.get("cover_letter", ""),
            "resume_variant": data.get("resume_variant", ""),
            "resume_attachment": data.get("resume_attachment", ""),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        columns = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        with self.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO jobs({columns}) VALUES({placeholders})",
                tuple(fields.values()),
            )
            job_id = int(cursor.lastrowid)
        return self.get_job(job_id)

    def update_job(self, job_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if not data:
            return self.get_job(job_id)

        writable = {
            "source",
            "source_url",
            "title",
            "company",
            "location",
            "remote",
            "salary",
            "url",
            "description",
            "requirements",
            "status",
            "match_score",
            "match_notes",
            "draft_text",
            "cover_letter",
            "resume_variant",
            "resume_attachment",
        }
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if key not in writable:
                continue
            if key == "requirements" and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            clean[key] = value
        clean["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        values = list(clean.values()) + [job_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)
        return self.get_job(job_id)

    def get_job(self, job_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Job {job_id} not found")
        return self._row_to_job(row)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                ORDER BY match_score DESC, updated_at DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def _row_to_job(self, row: sqlite3.Row) -> dict[str, Any]:
        job = dict(row)
        try:
            job["requirements"] = json.loads(job.get("requirements") or "[]")
        except json.JSONDecodeError:
            job["requirements"] = []
        return job

    def create_meeting(self, data: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_iso()
        fields = {
            "job_id": data.get("job_id"),
            "title": data.get("title") or "Interview",
            "company": data.get("company", ""),
            "starts_at": data.get("starts_at") or timestamp,
            "ends_at": data.get("ends_at", ""),
            "location": data.get("location", ""),
            "source": data.get("source", ""),
            "status": data.get("status", "scheduled"),
            "notes": data.get("notes", ""),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        columns = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        with self.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO meetings({columns}) VALUES({placeholders})",
                tuple(fields.values()),
            )
            meeting_id = int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return dict(row)

    def list_meetings(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM meetings ORDER BY starts_at ASC").fetchall()
        return [dict(row) for row in rows]

    def log(self, level: str, message: str, meta: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO activity(ts, level, message, meta) VALUES(?, ?, ?, ?)",
                (now_iso(), level, message, json.dumps(meta or {}, ensure_ascii=False)),
            )

    def list_activity(self, limit: int = 80) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM activity ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        activity = []
        for row in rows:
            item = dict(row)
            try:
                item["meta"] = json.loads(item.get("meta") or "{}")
            except json.JSONDecodeError:
                item["meta"] = {}
            activity.append(item)
        return activity

    def list_auto_applications(self, limit: int = 250) -> list[dict[str, Any]]:
        jobs = {int(job["id"]): job for job in self.list_jobs()}
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM activity ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        applications: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            message = str(item.get("message") or "")
            if message.startswith("Auto-applied job #"):
                outcome = "submitted"
            elif message.startswith("Auto-apply needs review for job #"):
                outcome = "needs_review"
            else:
                continue
            try:
                meta = json.loads(item.get("meta") or "{}")
            except json.JSONDecodeError:
                meta = {}
            job_id = int(meta.get("job_id") or 0)
            job = jobs.get(job_id, {})
            audit_path = str(meta.get("audit_path") or "")
            audit_url = f"/api/automation-runs/{Path(audit_path).name}" if audit_path else ""
            applications.append(
                {
                    "activity_id": item.get("id"),
                    "ts": item.get("ts"),
                    "level": item.get("level"),
                    "outcome": outcome,
                    "job_id": job_id,
                    "title": meta.get("title") or job.get("title", ""),
                    "company": meta.get("company") or job.get("company", ""),
                    "reason": meta.get("reason", ""),
                    "url": job.get("url", ""),
                    "match_score": job.get("match_score", 0),
                    "job_status": job.get("status", ""),
                    "audit_path": audit_path,
                    "audit_url": audit_url,
                }
            )
        return applications

    def clear_activity(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM activity")

    def export_jobs_csv(self) -> str:
        buffer = io.StringIO()
        fieldnames = [
            "id",
            "status",
            "match_score",
            "title",
            "company",
            "location",
            "remote",
            "salary",
            "url",
            "source",
            "updated_at",
            "resume_attachment",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for job in self.list_jobs():
            writer.writerow({key: job.get(key, "") for key in fieldnames})
        return buffer.getvalue()
