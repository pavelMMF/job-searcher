from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def parse_dt(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_ics_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(meetings: list[dict[str, Any]]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Job Cockpit//Interview Planner//EN",
        "CALSCALE:GREGORIAN",
    ]
    for meeting in meetings:
        start = parse_dt(str(meeting.get("starts_at", "")))
        end = parse_dt(str(meeting.get("ends_at", ""))) if meeting.get("ends_at") else start + timedelta(hours=1)
        uid = f"job-cockpit-{meeting.get('id', 'meeting')}@local"
        summary = meeting.get("title") or "Interview"
        company = meeting.get("company")
        if company and company.lower() not in summary.lower():
            summary = f"{summary} - {company}"
        description = meeting.get("notes") or "Interview created from Job Cockpit."
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{ics_escape(uid)}",
                f"DTSTAMP:{format_ics_dt(datetime.now(timezone.utc))}",
                f"DTSTART:{format_ics_dt(start)}",
                f"DTEND:{format_ics_dt(end)}",
                f"SUMMARY:{ics_escape(summary)}",
                f"DESCRIPTION:{ics_escape(description)}",
                f"LOCATION:{ics_escape(str(meeting.get('location', '')))}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def google_calendar_connector_status() -> dict[str, Any]:
    return {
        "available": False,
        "reason": "Google Calendar write access needs OAuth credentials and optional google-api-python-client dependencies.",
        "safe_mode": "The cockpit can export .ics now; direct Google sync is intentionally opt-in.",
    }
