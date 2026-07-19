from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from storage import Store


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf"
AURORA_HEADER_LIGHT = PROJECT_ROOT / "job_cockpit" / "static" / "assets" / "aurora_resume_header_light.png"
AURORA_HEADER_ORIGINAL = PROJECT_ROOT / "job_cockpit" / "static" / "assets" / "aurora_resume_header.png"
AURORA_HEADER = AURORA_HEADER_LIGHT if AURORA_HEADER_LIGHT.exists() else AURORA_HEADER_ORIGINAL
AURORA_HEADER_RATIO = 180 / 900
RESUME_RULES_PATH = PROJECT_ROOT / "job_cockpit" / "docs" / "RESUME_GENERATION_RULES.md"
REQUIRED_EXPERIENCE_PERIODS = ("Apr 2025 - Present", "Apr 2023 - Mar 2025")
FORBIDDEN_RESUME_MARKERS = (
    "Tailored for",
    "Generated 20",
    "job-cockpit",
    "agent notes",
    "Product Analyst | Retention Analyst | Data Scientist",
)
FORBIDDEN_AI_STYLE_PHRASES = (
    "proven track record",
    "results-oriented",
    "dynamic",
    "innovative",
    "cutting-edge",
    "tech-savvy",
    "excellent communicator",
    "team player",
    "leveraging my expertise",
    "fast-paced environment",
    "i am excited to apply",
    "i am thrilled to apply",
    "add numbers here",
    "insert metric",
    "as an ai",
)

KEYWORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}")


def load_master_resume(store: Store) -> dict[str, Any]:
    master = store.get_json_setting("resume_master")
    if master:
        return master
    config_path = Path(__file__).resolve().parents[1] / "config" / "master_resume.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {}


def job_keywords(job: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(job.get(key, ""))
        for key in ("title", "company", "location", "description", "requirements", "match_notes")
    )
    raw = {match.group(0).lower() for match in KEYWORD_RE.finditer(text)}
    aliases = {
        "ab": "a/b",
        "bi": "business",
        "ml": "machine",
    }
    normalized = set(raw)
    for key, value in aliases.items():
        if key in raw:
            normalized.add(value)
    return normalized


def text_score(text: str, keywords: set[str]) -> int:
    lowered = text.lower()
    score = 0
    for keyword in keywords:
        if len(keyword) < 3:
            continue
        if keyword in lowered:
            score += 3
    impact_markers = ["%", "saved", "improved", "automated", "optimized", "built", "developed"]
    score += sum(2 for marker in impact_markers if marker in lowered)
    return score


def choose_headline(master: dict[str, Any], job: dict[str, Any]) -> str:
    title = str(job.get("title", "")).lower()
    text = " ".join(
        str(job.get(key, ""))
        for key in ("title", "description", "requirements", "match_notes")
    ).lower()
    variants = master.get("headline_variants", {})

    def pick(key: str) -> str:
        return variants.get(key, variants.get("default", master.get("base_headline", "Senior Product Analyst")))

    if ("marketing" in text or "campaign" in text or "martech" in text or "traffic" in text) and (
        "analytics engineer" in title or "data analytics engineer" in title
    ):
        return pick("marketing_analytics_engineer")
    if "analytics engineer" in title or "data analytics engineer" in title:
        if "senior" in title or "sr" in title:
            return pick("senior_analytics_engineer")
        return pick("analytics_engineer")
    if "scientist" in title or "machine learning" in title or "ml" in title:
        return variants.get("data_scientist", variants.get("default", master.get("base_headline", "")))
    if "marketing" in text or "campaign" in text or "growth" in text or "traffic" in text:
        return pick("marketing_analyst")
    if "affiliate" in text:
        return pick("affiliate_analyst")
    if "product" in title and "data analyst" in title:
        return pick("product_data_analyst")
    if "product" in title or "affiliate" in title:
        return pick("product_analyst")
    if "bi" in title or "business intelligence" in title or "tableau" in title or "power bi" in title:
        return pick("bi_analyst")
    if "analyst" in title:
        if "senior" in title or "sr" in title:
            return pick("senior_data_analyst")
        return pick("data_analyst")
    return variants.get("default", master.get("base_headline", "Senior Product Analyst"))


def tailor_summary(master: dict[str, Any], job: dict[str, Any], keywords: set[str]) -> str:
    title = job.get("title") or "data role"
    company = job.get("company") or "the team"
    focus_terms = prioritized_skills(master, keywords, limit=7)
    focus = ", ".join(focus_terms)
    return (
        f"I work across product analytics, data science and practical automation, with 3+ years of hands-on experience in iGaming and digital products. "
        f"For the {title} role at {company}, I would bring {focus} and turn messy product questions into clear metrics, dashboards, experiments and decisions."
    )


def prioritized_skills(master: dict[str, Any], keywords: set[str], limit: int = 24) -> list[str]:
    all_skills: list[str] = []
    for values in master.get("skills", {}).values():
        all_skills.extend(str(item) for item in values)
    for item in experience_bank_items(master):
        all_skills.extend(str(skill) for skill in item.get("skills", []) if str(skill).strip())
    ranked = sorted(
        all_skills,
        key=lambda item: (text_score(item, keywords), item.lower()),
        reverse=True,
    )
    selected: list[str] = []
    for skill in ranked:
        if skill not in selected:
            selected.append(skill)
        if len(selected) >= limit:
            break
    return selected


def experience_bank_items(master: dict[str, Any]) -> list[dict[str, Any]]:
    bank = master.get("experience_bank", [])
    return [item for item in bank if isinstance(item, dict)]


def matching_experience_bank_bullets(master: dict[str, Any], keywords: set[str], limit: int = 8) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for item in experience_bank_items(master):
        tags = " ".join(str(tag) for tag in item.get("tags", []))
        skills = " ".join(str(skill) for skill in item.get("skills", []))
        role_period = str(item.get("role_period", "")).strip()
        source = str(item.get("source", "")).strip()
        for raw in item.get("bullets", []):
            bullet = str(raw).strip()
            if not bullet:
                continue
            score = text_score(" ".join([bullet, tags, skills, source]), keywords)
            if score <= 0:
                continue
            if role_period and role_period not in bullet:
                bullet = f"{bullet}"
            matches.append((score, bullet))
    return sorted(matches, reverse=True)[:limit]


def tailored_experience(
    master: dict[str, Any],
    keywords: set[str],
    max_bullets: int = 14,
    min_bullets_per_role: int = 2,
) -> list[dict[str, Any]]:
    roles = list(master.get("experience", []))
    if not roles:
        return []

    ranked_by_role: list[tuple[dict[str, Any], list[str]]] = []
    for role in roles:
        bullets = [str(bullet) for bullet in role.get("bullets", []) if str(bullet).strip()]
        ranked_by_role.append((role, sorted(bullets, key=lambda item: text_score(item, keywords), reverse=True)))

    max_bullets = max(max_bullets, len(ranked_by_role))
    base_take = max(1, min_bullets_per_role)
    selected_by_role: list[list[str]] = []
    remaining = max_bullets
    for _, ranked in ranked_by_role:
        take = min(base_take, len(ranked), remaining)
        selected_by_role.append(ranked[:take])
        remaining -= take

    # Reserve early space for additional real experience so it can surface when
    # the base CV is shorter than the candidate's actual project history.
    bank_bullets = matching_experience_bank_bullets(master, keywords, limit=8)
    for _, bullet in bank_bullets:
        if remaining <= 0:
            break
        best_role = 0
        best_score = -1
        for index, (role, _ranked) in enumerate(ranked_by_role):
            role_text = " ".join(str(role.get(key, "")) for key in ("title", "period", "context"))
            score = text_score(role_text, keywords)
            if score > best_score:
                best_score = score
                best_role = index
        if bullet not in selected_by_role[best_role]:
            selected_by_role[best_role].append(bullet)
            remaining -= 1

    # Use the remaining space for the strongest job-specific achievements, while
    # preserving every role so older experience never disappears from the resume.
    candidates: list[tuple[int, int, str]] = []
    for role_index, (_, ranked) in enumerate(ranked_by_role):
        used = set(selected_by_role[role_index])
        for bullet in ranked:
            if bullet not in used:
                candidates.append((text_score(bullet, keywords), role_index, bullet))
    for _, role_index, bullet in sorted(candidates, reverse=True):
        if remaining <= 0:
            break
        selected_by_role[role_index].append(bullet)
        remaining -= 1

    return [
        {**role, "bullets": selected}
        for (role, _), selected in zip(ranked_by_role, selected_by_role)
    ]


def matching_highlights(master: dict[str, Any], keywords: set[str], limit: int = 3) -> list[str]:
    bullets: list[str] = []
    for role in master.get("experience", []):
        bullets.extend(str(bullet) for bullet in role.get("bullets", []))
    bullets.extend(bullet for _score, bullet in matching_experience_bank_bullets(master, keywords, limit=12))
    ranked = sorted(bullets, key=lambda item: text_score(item, keywords), reverse=True)
    return ranked[:limit]


def build_resume_payload(master: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    keywords = job_keywords(job)
    payload = {
        "name": master.get("name", ""),
        "headline": choose_headline(master, job),
        "contacts": master.get("contacts", {}),
        "summary": tailor_summary(master, job, keywords),
        "highlights": matching_highlights(master, keywords),
        "skills": prioritized_skills(master, keywords),
        "experience": tailored_experience(master, keywords),
        "education": master.get("education", []),
        "training": master.get("training", []),
        "target": {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }
    validate_resume_payload(payload)
    return payload


def validate_resume_payload(payload: dict[str, Any]) -> None:
    periods = {str(role.get("period", "")).strip() for role in payload.get("experience", [])}
    missing = [period for period in REQUIRED_EXPERIENCE_PERIODS if period not in periods]
    if missing:
        raise ValueError(f"Resume payload is missing required experience periods: {', '.join(missing)}")

    for role in payload.get("experience", []):
        bullets = [bullet for bullet in role.get("bullets", []) if str(bullet).strip()]
        if len(bullets) < 2:
            raise ValueError(f"Resume role has too few bullets: {role.get('period', '')} {role.get('title', '')}")

    visible_text_parts: list[str] = [
        str(payload.get("name", "")),
        str(payload.get("headline", "")),
        str(payload.get("summary", "")),
        " ".join(str(item) for item in payload.get("highlights", [])),
        " ".join(str(item) for item in payload.get("skills", [])),
    ]
    for role in payload.get("experience", []):
        visible_text_parts.extend([str(role.get("period", "")), str(role.get("title", "")), str(role.get("company", ""))])
        visible_text_parts.extend(str(bullet) for bullet in role.get("bullets", []))
    visible_text = "\n".join(visible_text_parts)
    leaked = [marker for marker in FORBIDDEN_RESUME_MARKERS if marker.lower() in visible_text.lower()]
    leaked.extend(marker for marker in FORBIDDEN_AI_STYLE_PHRASES if marker.lower() in visible_text.lower())
    if leaked:
        raise ValueError(f"Resume payload contains forbidden internal markers: {', '.join(leaked)}")


def generate_resume_for_job(store: Store, job_id: int, preserve_status: bool = False) -> dict[str, Any]:
    master = load_master_resume(store)
    job = store.get_job(job_id)
    payload = build_resume_payload(master, job)
    return generate_resume_from_payload(store, job_id, payload, preserve_status=preserve_status, source="rules")


def generate_resume_from_payload(
    store: Store,
    job_id: int,
    payload: dict[str, Any],
    preserve_status: bool = False,
    source: str = "custom",
) -> dict[str, Any]:
    job = store.get_job(job_id)
    validate_resume_payload(payload)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = build_filename(job, payload)
    output_path = OUTPUT_DIR / filename
    write_resume_pdf(payload, output_path)
    relative = output_path.relative_to(PROJECT_ROOT).as_posix()
    update = {
        "resume_variant": relative,
        "resume_attachment": str(output_path),
    }
    if not preserve_status and job.get("status") not in {"applied", "skipped", "rejected"}:
        update["status"] = "ready_to_apply"
    store.update_job(job_id, update)
    store.log(
        "info",
        f"Generated tailored resume for {job.get('title', 'job')}",
        {"job_id": job_id, "file": relative, "source": source},
    )
    return {
        "path": str(output_path),
        "relative_path": relative,
        "filename": filename,
        "payload": payload,
    }


def build_filename(job: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    title = slug(job.get("title") or "data-role")
    raw_company = str(job.get("company") or "").strip()
    if raw_company.lower() in {"name", "company", "unknown"}:
        raw_company = ""
    company = slug(raw_company or "company")
    # Candidate name comes from the local (git-ignored) master_resume.json, not the code.
    candidate = slug(str((payload or {}).get("name") or "").strip()) if payload else ""
    candidate = candidate or "candidate"
    return f"{candidate}_{company}_{title}_tailored.pdf"[:150]


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "role"


def write_resume_pdf(payload: dict[str, Any], output_path: Path) -> None:
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=8 * mm,
        bottomMargin=11 * mm,
        title=f"{payload.get('name', 'Resume')} - tailored resume",
        author=payload.get("name", ""),
    )

    story: list[Any] = []
    contacts = payload.get("contacts", {})
    contact_line = " | ".join(
        item
        for item in [
            contacts.get("phone", ""),
            contacts.get("email", ""),
            contacts.get("preferred_contact", ""),
            contacts.get("location", ""),
        ]
        if item
    )

    if AURORA_HEADER.exists():
        story.append(Image(str(AURORA_HEADER), width=doc.width, height=doc.width * AURORA_HEADER_RATIO))
        story.append(Spacer(1, 7))

    story.append(Paragraph(esc(payload.get("name", "")), styles["Name"]))
    story.append(Paragraph(esc(payload.get("headline", "")), styles["Headline"]))
    story.append(Paragraph(esc(contact_line), styles["Contact"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#D8D2C7")))
    story.append(Spacer(1, 6))

    add_section(story, "Summary", styles)
    story.append(Paragraph(esc(payload.get("summary", "")), styles["Body"]))
    story.append(Spacer(1, 6))

    add_section(story, "Highlights", styles)
    for highlight in payload.get("highlights", []):
        story.append(Paragraph(esc(f"- {highlight}"), styles["Bullet"]))
    story.append(Spacer(1, 6))

    add_section(story, "Key skills", styles)
    story.append(Paragraph(esc(" | ".join(payload.get("skills", []))), styles["SkillLine"]))
    story.append(Spacer(1, 6))

    add_section(story, "Experience", styles)
    for role in payload.get("experience", []):
        role_title = f"{role.get('period', '')} - {role.get('title', '')}, {role.get('company', '')}"
        story.append(KeepTogether([Paragraph(esc(role_title), styles["Role"]), Paragraph(esc(role.get("duration", "")), styles["Muted"])]))
        if role.get("context"):
            story.append(Paragraph(esc(role.get("context", "")), styles["Muted"]))
        for bullet in role.get("bullets", []):
            story.append(Paragraph(esc(f"- {bullet}"), styles["Bullet"]))
        story.append(Spacer(1, 3))

    add_section(story, "Education and training", styles)
    for education in payload.get("education", []):
        text = f"{education.get('period', '')} - {education.get('school', '')}: {education.get('degree', '')}"
        story.append(Paragraph(esc(text), styles["Body"]))
    if payload.get("training"):
        story.append(Paragraph(esc(" | ".join(payload.get("training", []))), styles["Body"]))

    doc.build(story)


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Name": ParagraphStyle(
            "Name",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#232323"),
            spaceAfter=2,
        ),
        "Headline": ParagraphStyle(
            "Headline",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.8,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#3F5E4B"),
            spaceAfter=2,
        ),
        "Contact": ParagraphStyle(
            "Contact",
            parent=base["BodyText"],
            fontSize=7.8,
            leading=9.5,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#635F58"),
        ),
        "Section": ParagraphStyle(
            "Section",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=8.8,
            leading=11,
            textColor=colors.HexColor("#6D5F49"),
            spaceBefore=2,
            spaceAfter=3,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontSize=8.2,
            leading=10.2,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#232323"),
        ),
        "SkillLine": ParagraphStyle(
            "SkillLine",
            parent=base["BodyText"],
            fontSize=7.8,
            leading=9.7,
            textColor=colors.HexColor("#232323"),
        ),
        "Role": ParagraphStyle(
            "Role",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=10.2,
            textColor=colors.HexColor("#232323"),
            spaceBefore=2,
        ),
        "Muted": ParagraphStyle(
            "Muted",
            parent=base["BodyText"],
            fontSize=7.4,
            leading=8.8,
            textColor=colors.HexColor("#766F65"),
        ),
        "Bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontSize=7.7,
            leading=9.2,
            leftIndent=8,
            firstLineIndent=-5,
            textColor=colors.HexColor("#232323"),
        ),
        "Footer": ParagraphStyle(
            "Footer",
            parent=base["BodyText"],
            fontSize=6.8,
            leading=8,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#766F65"),
        ),
    }


def add_section(story: list[Any], title: str, styles: dict[str, ParagraphStyle]) -> None:
    story.append(Paragraph(title, styles["Section"]))


def esc(value: Any) -> str:
    return (
        str(value)
        .replace("–", "-")
        .replace("—", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
