from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

from llm_generator import LLMGenerationUnavailable, generate_llm_application_package
from resume_generator import generate_resume_for_job, generate_resume_from_payload
from storage import Store


WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}")
LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
TITLE_HINT_RE = re.compile(
    r"\b(data analyst|product analyst|affiliate analyst|affiliate data analyst|bi analyst|business intelligence|analytics engineer|data scientist|machine learning)\b",
    re.IGNORECASE,
)

DATA_ANALYTICS_RE = re.compile(
    r"\b(data analyst|product analyst|product data analyst|affiliate analyst|affiliate data analyst|product affiliate analyst|bi analyst|business intelligence analyst|analytics engineer|marketing data analyst|growth analyst|retention analyst|product analytics|affiliate analytics)\b",
    re.IGNORECASE,
)
DATA_SCIENCE_RE = re.compile(
    r"\b(data scientist|machine learning scientist|ml scientist|applied scientist|decision scientist|research scientist)\b",
    re.IGNORECASE,
)
ENTRY_LEVEL_RE = re.compile(
    r"\b(junior|jr\.?|intern|internship|working student|student|trainee|graduate|entry[- ]level|entry level|associate analyst)\b",
    re.IGNORECASE,
)
MID_PLUS_RE = re.compile(
    r"\b(mid|middle|mid[- ]level|senior|sr\.?|lead|principal|staff|expert|ii|iii|iv|manager|several years|[3-9]\+?\s+years)\b",
    re.IGNORECASE,
)
MID_RE = re.compile(
    r"\b(mid|middle|mid[- ]level|ii|iii|journeyman|several years|[3-5]\+?\s+years)\b",
    re.IGNORECASE,
)
SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|head|director|manager|expert|iv|[6-9]\+?\s+years|10\+?\s+years)\b",
    re.IGNORECASE,
)
PRODUCT_AFFILIATE_ANALYTICS_RE = re.compile(
    r"\b(product analyst|product data analyst|product analytics|affiliate analyst|affiliate data analyst|affiliate analytics|product affiliate analyst|growth analyst|retention analyst|marketing data analyst)\b",
    re.IGNORECASE,
)
FORBIDDEN_APPLICATION_TEXT_RE = re.compile(
    r"\b(proven track record|results-oriented|dynamic|innovative|cutting-edge|tech-savvy|excellent communicator|team player|leveraging my expertise|fast-paced environment|i am excited to apply|i am thrilled to apply|add numbers here|insert metric|as an ai)\b",
    re.IGNORECASE,
)


@dataclass
class AgentResult:
    ok: bool
    message: str
    payload: dict[str, Any]


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;\n]", value) if part.strip()]
    return [str(value).strip()]


def plain_words(text: str) -> set[str]:
    return {match.group(0).lower() for match in WORD_RE.finditer(text or "")}


def role_family(title: str, text: str) -> str:
    blob = f"{title} {text}"
    if DATA_SCIENCE_RE.search(blob):
        return "data_science"
    if DATA_ANALYTICS_RE.search(blob):
        return "data_analytics"
    return "other"


def seniority_level(title: str, text: str) -> str:
    blob = f"{title} {text}"
    title_blob = title or ""
    if ENTRY_LEVEL_RE.search(title_blob):
        return "entry"
    if SENIOR_RE.search(title_blob):
        return "senior"
    if MID_RE.search(title_blob):
        return "mid"
    if ENTRY_LEVEL_RE.search(blob):
        return "entry"
    if MID_RE.search(blob):
        return "mid"
    return "unspecified"


def analytics_track(title: str, text: str) -> str:
    blob = f"{title} {text}"
    if PRODUCT_AFFILIATE_ANALYTICS_RE.search(blob):
        return "product_affiliate_analytics"
    if DATA_ANALYTICS_RE.search(blob):
        return "data_analytics"
    if DATA_SCIENCE_RE.search(blob):
        return "data_science"
    return "other"


def profile_from_store(store: Store) -> dict[str, Any]:
    return store.get_json_setting("profile", {})


def workflow_from_store(store: Store) -> dict[str, Any]:
    return store.get_json_setting("workflow", {})


def standard_resume_path(store: Store) -> str:
    profile = profile_from_store(store)
    if profile.get("resume_path"):
        return str(profile["resume_path"])
    master = store.get_json_setting("resume_master", {})
    return str(master.get("standard_resume_path", ""))


def source_domain(value: str) -> str:
    parsed = urlparse(value or "")
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    return host.lower().removeprefix("www.")


def blocked_source_match(workflow: dict[str, Any], item: dict[str, Any]) -> str:
    blocked_domains = {source_domain(domain) for domain in normalize_list(workflow.get("blocked_source_domains"))}
    blocked_names = {name.lower() for name in normalize_list(workflow.get("blocked_source_names"))}
    source_name = str(item.get("source") or item.get("name") or "").lower()
    source_url = str(item.get("source_url") or item.get("url") or "")
    domains = {
        source_domain(source_url),
        source_domain(str(item.get("url") or "")),
    }
    if source_name and any(name in source_name for name in blocked_names):
        return source_name
    for domain in domains:
        if domain and any(domain == blocked or domain.endswith("." + blocked) for blocked in blocked_domains):
            return domain
    return ""


def clean_html_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</p>|</li>|</h\d>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).replace("\r", "").strip()


def parse_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = clean_html_text((payload.get("raw_text") or payload.get("description") or "").strip())
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    title = payload.get("title") or ""
    company = payload.get("company") or ""
    location = payload.get("location") or ""
    salary = payload.get("salary") or ""

    for line in lines[:10]:
        lowered = line.lower()
        if not title and TITLE_HINT_RE.search(line):
            title = line[:140]
        if not company and lowered.startswith(("company:", "company -", "employer:")):
            company = re.split(r":|-", line, maxsplit=1)[-1].strip()
        if not location and lowered.startswith(("location:", "office:", "based in:")):
            location = re.split(r":", line, maxsplit=1)[-1].strip()
        if not salary and ("salary" in lowered or "compensation" in lowered):
            salary = line[:160]

    if not title and lines:
        title = lines[0][:140]
    if not title:
        title = "Untitled data role"
    if str(company).strip().lower() in {"name", "company", "unknown"}:
        company = ""

    requirements = extract_requirements(raw)
    return {
        "source": payload.get("source", "manual"),
        "source_url": payload.get("source_url", payload.get("url", "")),
        "title": title,
        "company": company,
        "location": location,
        "remote": payload.get("remote", infer_remote(raw)),
        "salary": salary,
        "url": payload.get("url", ""),
        "description": raw or payload.get("description", ""),
        "requirements": requirements,
        "status": payload.get("status", "new"),
    }


def extract_requirements(text: str) -> list[str]:
    requirements: list[str] = []
    for line in (text or "").splitlines():
        clean = re.sub(r"^[*\-\d.)\s]+", "", line).strip()
        lowered = clean.lower()
        if not clean or len(clean) < 12:
            continue
        if any(word in lowered for word in ("experience", "proficient", "knowledge", "sql", "python", "degree")):
            requirements.append(clean[:220])
        if len(requirements) >= 12:
            break
    return requirements


def infer_remote(text: str) -> str:
    lowered = (text or "").lower()
    if "hybrid" in lowered:
        return "hybrid"
    if any(term in lowered for term in ("remote", "work from home", "work from anywhere", "home office", "distributed team", "fully distributed")):
        return "remote"
    if "on-site" in lowered or "onsite" in lowered:
        return "onsite"
    return ""


def score_job(profile: dict[str, Any], job: dict[str, Any], workflow: dict[str, Any] | None = None) -> tuple[int, str]:
    workflow = workflow or {}
    blocked = blocked_source_match(workflow, job)
    if blocked:
        return 0, f"blocked source: {blocked}"
    haystack = " ".join(
        str(job.get(key, ""))
        for key in ("title", "company", "location", "remote", "description")
    ).lower()
    title = str(job.get("title", "")).lower()
    words = plain_words(haystack)
    family = role_family(title, haystack)
    seniority = seniority_level(title, haystack)
    track = analytics_track(title, haystack)

    score = 22
    notes: list[str] = []

    if family == "data_science" and seniority == "senior":
        return 0, "excluded: senior/lead/staff data science; target is middle data science only"

    focus_families = set(normalize_list(workflow.get("focus_role_families"))) or {"data_analytics", "data_science"}
    if family in focus_families:
        score += 14
        notes.append(f"role family: {family.replace('_', ' ')}")
    else:
        score -= 45
        notes.append("outside target role family")

    if family == "data_analytics":
        if track == "product_affiliate_analytics":
            score += 16
            notes.append("track: product/affiliate analytics")
        else:
            score += 4
            notes.append("track: general analytics")

    if seniority == "mid":
        score += 16
        notes.append("seniority: middle")
    elif seniority == "senior":
        if family == "data_analytics":
            score += 15
            notes.append("seniority: senior analytics ok")
        else:
            score -= 8
            notes.append("seniority: senior needs review")
    elif seniority == "entry" and workflow.get("exclude_entry_level", True):
        score -= 38
        notes.append("entry/junior signal")
    else:
        score += 4 if family == "data_science" else 3
        notes.append("seniority unspecified")

    desired_titles = [item.lower() for item in normalize_list(profile.get("target_titles"))]
    title_hits = [item for item in desired_titles if item and item in title]
    if title_hits:
        score += 30
        notes.append(f"title match: {', '.join(title_hits[:3])}")
    elif TITLE_HINT_RE.search(title):
        score += 18
        notes.append("data-role title detected")

    skills = normalize_list(profile.get("skills"))
    matched_skills: list[str] = []
    for skill in skills:
        skill_lower = skill.lower()
        token_hit = skill_lower in haystack
        word_hit = skill_lower in words
        if token_hit or word_hit:
            matched_skills.append(skill)
    if matched_skills:
        score += min(34, 5 * len(matched_skills))
        notes.append(f"skills: {', '.join(matched_skills[:7])}")
    if TITLE_HINT_RE.search(title) and len(matched_skills) >= 3:
        score += 6
        notes.append("title and stack reinforce each other")

    target_locations = [item.lower() for item in normalize_list(profile.get("target_locations"))]
    location_blob = " ".join(str(job.get(key, "")) for key in ("location", "remote")).lower()
    location_hits = [item for item in target_locations if item and item.lower() in location_blob]
    if location_hits:
        score += 12
        notes.append(f"location: {', '.join(location_hits[:3])}")
    elif "remote" in location_blob:
        score += 8
        notes.append("remote-friendly")

    if "manager" in title and "data scientist" not in title and "analytics" not in title:
        score -= 12
        notes.append("manager title needs review")
    weak_role_terms = (
        "online data analyst",
        "rater",
        "evaluator",
        "annotator",
        "speaker",
        "speakers",
        "search engine",
        "ads quality",
        "führungsverantwortung",
        "management responsibility",
    )
    weak_hits = [term for term in weak_role_terms if term in haystack]
    if weak_hits:
        score -= 18
        notes.append(f"possible weak match: {', '.join(weak_hits[:3])}")

    avoid_hits = [item for item in normalize_list(profile.get("avoid_keywords")) if item.lower() in haystack]
    if avoid_hits:
        score -= 25
        notes.append(f"avoid: {', '.join(avoid_hits[:3])}")

    score = max(0, min(100, score))
    if not notes:
        notes.append("not enough text to explain fit yet")
    return score, "; ".join(notes)


def create_job(store: Store, payload: dict[str, Any]) -> dict[str, Any]:
    profile = profile_from_store(store)
    workflow = workflow_from_store(store)
    job = parse_job_payload(payload)
    score, notes = score_job(profile, job, workflow)
    job["match_score"] = score
    job["match_notes"] = notes
    created = store.create_job(job)
    store.log("info", f"Added job: {created['title']}", {"job_id": created["id"], "score": score})
    return created


def job_key(job: dict[str, Any]) -> str:
    if job.get("url"):
        return f"url:{job['url'].strip().lower()}"
    role_key = job_role_key(job)
    if role_key:
        return role_key
    return "role:" + "|".join(
        str(job.get(key, "")).strip().lower()
        for key in ("title", "company", "location")
    )


def job_role_key(job: dict[str, Any]) -> str:
    parts = [
        re.sub(r"\s+", " ", str(job.get(key, "")).strip().lower())
        for key in ("title", "company", "location")
    ]
    if not parts[0]:
        return ""
    return "role:" + "|".join(
        re.sub(r"[^a-z0-9+#./ -]+", "", part)
        for part in parts
    )


def job_keys(job: dict[str, Any]) -> set[str]:
    keys = {job_key(job)}
    role_key = job_role_key(job)
    if role_key:
        keys.add(role_key)
    url = str(job.get("url") or "").strip().lower()
    if url:
        keys.add(f"url:{url}")
    return {key for key in keys if key and key != "role:||"}


def existing_job_keys(store: Store) -> set[str]:
    keys: set[str] = set()
    for job in store.list_jobs():
        keys.update(job_keys(job))
    return keys


def has_seen_job(seen: set[str], job: dict[str, Any]) -> bool:
    return bool(seen.intersection(job_keys(job)))


def rescore_all(store: Store) -> AgentResult:
    profile = profile_from_store(store)
    workflow = workflow_from_store(store)
    threshold = int(workflow.get("min_score_to_prepare", 68) or 68)
    changed = 0
    demoted = 0
    for job in store.list_jobs():
        score, notes = score_job(profile, job, workflow)
        update = {"match_score": score, "match_notes": notes}
        if (
            workflow.get("demote_ready_below_threshold", True)
            and job.get("status") == "ready_to_apply"
            and score < threshold
        ):
            update["status"] = "scored"
            demoted += 1
        store.update_job(job["id"], update)
        changed += 1
    store.log("info", f"Rescored {changed} jobs", {"count": changed, "demoted": demoted})
    return AgentResult(True, f"Rescored {changed} jobs", {"count": changed, "demoted": demoted})


def company_interest_reason(job: dict[str, Any]) -> str:
    company = job.get("company") or "the company"
    text = " ".join(str(job.get(key, "")) for key in ("title", "company", "description", "requirements")).lower()
    signals = [
        (("retention", "lifecycle", "crm", "growth"), "your focus on growth, retention and customer behavior"),
        (("experiment", "a/b", "conversion"), "the opportunity to work with experiments and measurable product decisions"),
        (("marketplace", "commerce", "consumer", "subscription"), "your product and marketplace/customer analytics context"),
        (("fraud", "risk", "gaming", "casino", "igaming"), "the overlap with my iGaming, risk and product analytics background"),
        (("machine learning", "ml", "prediction", "model"), "the practical machine-learning and predictive analytics work described in the role"),
        (("dashboard", "bi", "reporting", "stakeholder"), "the need for clear dashboards, stakeholder reporting and decision support"),
        (("automation", "ai", "agent"), "the automation and AI-enabled analytics angle"),
        (("data warehouse", "etl", "elt", "dbt", "pipeline"), "the analytics engineering and reliable data infrastructure work"),
    ]
    for terms, reason in signals:
        if any(term in text for term in terms):
            return reason
    if company and company not in {"your team", "the company"}:
        return f"the problems {company} is hiring this team to solve"
    return "the data-driven problems described in the role"


def build_cover_letter(profile: dict[str, Any], job: dict[str, Any]) -> str:
    first_name = profile.get("first_name") or "Your name"
    skills = ", ".join(normalize_list(profile.get("skills"))[:5])
    company = job.get("company") or "your team"
    title = job.get("title") or "this role"
    fit = skills or "SQL, Python, product analytics, retention analysis and dashboards"
    reason = company_interest_reason(job)
    letter = (
        f"Hi {company} team, I would like to work with you as {title} because I am interested in {reason}. "
        f"My relevant experience includes {fit} and 3+ years across iGaming and product analytics. "
        f"I would be glad to help {company} turn data into clearer product and business decisions. "
        f"Best, {first_name}"
    )
    letter = re.sub(r"\s+", " ", letter.replace("–", "-").replace("—", "-")).strip()
    words = letter.split()
    if len(words) <= 100:
        return validate_application_text(letter, max_words=100)
    return validate_application_text(" ".join(words[:97]).rstrip(" ,.;:") + f". Best, {first_name}", max_words=100)


def validate_application_text(text: str, max_words: int | None = None) -> str:
    if FORBIDDEN_APPLICATION_TEXT_RE.search(text):
        raise ValueError("Generated application text contains forbidden generic AI-style phrasing.")
    if max_words is not None and len(text.split()) > max_words:
        raise ValueError(f"Generated application text is too long: {len(text.split())} words.")
    return text


def build_application_draft(profile: dict[str, Any], job: dict[str, Any]) -> str:
    title = job.get("title") or "role"
    company = job.get("company") or "the company"
    first_name = profile.get("first_name", "")
    last_name = profile.get("last_name", "")
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    return "\n".join(
        [
            f"Application package for {title} at {company}",
            "",
            "Copy data:",
            f"- Name: {full_name}",
            f"- Email: {profile.get('email', '')}",
            f"- Phone: {profile.get('phone', '')}",
            f"- Location: {profile.get('location', '')}",
            f"- LinkedIn: {profile.get('linkedin_url', '')}",
            f"- Portfolio/GitHub: {profile.get('portfolio_url') or profile.get('github_url', '')}",
            "",
            "Checklist:",
            "- Review role requirements against profile.",
            "- Attach the generated tailored resume from this card.",
            "- Use generated cover letter only after review.",
            "- Let the filler populate known fields.",
            "- Solve CAPTCHA/security checks manually if the site shows them.",
            "- Click final Submit only after the page looks correct.",
            "",
            "LinkedIn note:",
            f"Hi, I saw the {title} opening and it looks closely aligned with my data analytics/science background. I would be glad to connect.",
        ]
    )


def should_generate_application_package(job: dict[str, Any], workflow: dict[str, Any], force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "manual request"
    score = int(job.get("match_score") or 0)
    perfect_score = int(workflow.get("always_generate_score", 100) or 100)
    if score >= perfect_score:
        return True, f"score >= {perfect_score}"
    if workflow.get("auto_generate_for_auto_apply_candidates", True):
        if workflow.get("auto_submit_allowed", False) and str(job.get("url") or "").strip():
            return True, "auto-apply candidate"
    return False, "cost-saving policy"


def draft_job(store: Store, job_id: int, force_generate: bool = False) -> dict[str, Any]:
    profile = profile_from_store(store)
    job = store.get_job(job_id)
    workflow = workflow_from_store(store)
    generate_package, generation_reason = should_generate_application_package(job, workflow, force=force_generate)
    llm_package: dict[str, Any] | None = None
    llm_resume_generated = False
    cover_letter = ""
    if generate_package and (workflow.get("auto_generate_cover_letter", True) or workflow.get("auto_generate_resume", True)):
        try:
            llm_package = generate_llm_application_package(store, job_id)
            store.log(
                "info",
                "Generated LLM application package",
                {
                    "job_id": job_id,
                    "model": llm_package.get("model", ""),
                    "usage": llm_package.get("usage", {}),
                    "fit_notes": llm_package.get("fit_notes", []),
                },
            )
        except LLMGenerationUnavailable as exc:
            store.log("warning", "LLM package generation unavailable; using rules fallback", {"job_id": job_id, "reason": str(exc)})
    elif workflow.get("llm_generate_application_package", True):
        store.log(
            "info",
            "Skipped LLM package generation by cost-saving policy",
            {"job_id": job_id, "reason": generation_reason, "score": int(job.get("match_score") or 0)},
        )

    if workflow.get("auto_generate_cover_letter", True):
        if llm_package:
            cover_letter = validate_application_text(str(llm_package.get("cover_letter", "")), max_words=100)
        else:
            cover_letter = build_cover_letter(profile, job)
    else:
        cover_letter = job.get("cover_letter", "")
    draft_text = build_application_draft(profile, job)
    updated = store.update_job(
        job_id,
        {
            "cover_letter": cover_letter,
            "draft_text": draft_text,
            "status": "ready_to_apply",
        },
    )
    should_write_resume = workflow.get("auto_generate_resume", True) and (force_generate or not updated.get("resume_variant"))
    if should_write_resume:
        try:
            if llm_package:
                generate_resume_from_payload(store, job_id, llm_package["resume"], source="openai")
                updated = store.get_job(job_id)
                llm_resume_generated = True
            elif has_enough_resume_context(updated):
                generate_resume_for_job(store, job_id)
                updated = store.get_job(job_id)
            else:
                fallback = standard_resume_path(store)
                if fallback:
                    updated = store.update_job(job_id, {"resume_attachment": fallback})
                    store.log("info", "Using standard resume fallback due to limited job context", {"job_id": job_id})
        except Exception as exc:  # noqa: BLE001
            store.log("error", "Resume generation failed", {"job_id": job_id, "error": str(exc)})
            fallback = standard_resume_path(store)
            if fallback:
                updated = store.update_job(job_id, {"resume_attachment": fallback})
    store.log(
        "info",
        f"Prepared draft for {updated['title']}",
        {"job_id": job_id, "llm_resume": llm_resume_generated, "generation_reason": generation_reason},
    )
    return updated


def has_enough_resume_context(job: dict[str, Any]) -> bool:
    description = str(job.get("description", ""))
    requirements = job.get("requirements") or []
    if len(description) >= 350:
        return True
    if isinstance(requirements, list) and len([item for item in requirements if str(item).strip()]) >= 2:
        return True
    return int(job.get("match_score") or 0) >= 70


def draft_ready_jobs(store: Store) -> AgentResult:
    workflow = workflow_from_store(store)
    if not workflow.get("auto_package_ready_jobs", True):
        store.log("info", "Automatic package generation is disabled", {})
        return AgentResult(True, "Automatic package generation is disabled", {"count": 0, "resumes": 0, "skipped_cost_saving": 0})
    threshold = int(workflow.get("min_score_to_prepare", 72))
    count = 0
    resume_count = 0
    skipped_cost = 0
    for job in store.list_jobs():
        status = job.get("status")
        needs_new_package = status in {"new", "scored"}
        needs_resume = status == "ready_to_apply" and not (job.get("resume_variant") or job.get("resume_attachment")) and workflow.get("auto_generate_resume", True)
        if int(job.get("match_score") or 0) >= threshold and (needs_new_package or needs_resume):
            generate_package, reason = should_generate_application_package(job, workflow)
            if not generate_package:
                skipped_cost += 1
                store.log(
                    "info",
                    "Skipped automatic package generation to save LLM costs",
                    {"job_id": job["id"], "score": int(job.get("match_score") or 0), "reason": reason},
                )
                continue
            before = job.get("resume_attachment", "") or job.get("resume_variant", "")
            updated = draft_job(store, job["id"])
            after = updated.get("resume_attachment", "") or updated.get("resume_variant", "")
            if after and after != before:
                resume_count += 1
            count += 1
    store.log(
        "info",
        f"Prepared {count} application packages",
        {"threshold": threshold, "resumes": resume_count, "skipped_cost_saving": skipped_cost},
    )
    return AgentResult(
        True,
        f"Prepared {count} application packages",
        {"count": count, "resumes": resume_count, "skipped_cost_saving": skipped_cost},
    )


PUBLIC_WIDE_SOURCE_KINDS = {
    "remotive_api",
    "arbeitnow_api",
    "jobicy_api",
    "himalayas_api",
    "remoteok_api",
    "rss",
    "public_html",
    "greenhouse_board",
    "lever_site",
    "ashby_board",
}


def discover_from_sources(store: Store, wide: bool = False) -> AgentResult:
    sources = store.get_json_setting("sources", [])
    workflow = workflow_from_store(store)
    queries = normalize_list(workflow.get("search_queries")) or ["data analyst", "data scientist"]
    locations = ["remote"] if workflow.get("remote_only", True) else normalize_list(workflow.get("search_locations"))
    max_new = int(workflow.get("max_new_jobs_per_run", 35) or 35)
    if wide:
        max_new = max(max_new, 120)
        sources = [
            source for source in sources
            if source.get("enabled") and source.get("kind") in PUBLIC_WIDE_SOURCE_KINDS and not blocked_source_match(workflow, source)
        ]
    else:
        sources = [source for source in sources if source.get("enabled") and not blocked_source_match(workflow, source)]
    per_source_limit = max(8, min(24, max_new // max(1, len(sources)))) if wide else max_new
    created = 0
    errors: list[str] = []
    seen = existing_job_keys(store)
    for source in sources:
        try:
            found = discover_source(source, queries, locations)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            errors.append(f"{source.get('name', source.get('url', 'source'))}: {exc}")
            continue
        source_created = 0
        for item in found:
            candidate = {
                "source": source.get("name", "source"),
                "source_url": source.get("url", ""),
                **item,
            }
            if blocked_source_match(workflow, candidate):
                continue
            parsed = parse_job_payload(candidate)
            if has_seen_job(seen, parsed):
                continue
            create_job(store, candidate)
            seen.update(job_keys(parsed))
            created += 1
            source_created += 1
            if created >= max_new or (wide and source_created >= per_source_limit):
                break
        if created >= max_new:
            break
    message = f"Discovered {created} candidate jobs"
    if wide:
        message = f"Wide search discovered {created} candidate jobs across {len(sources)} public sources"
    if errors:
        message += f"; {len(errors)} source errors"
    store.log("info", message, {"created": created, "errors": errors, "wide": wide})
    return AgentResult(True, message, {"created": created, "errors": errors, "wide": wide, "sources": len(sources)})


def discover_source(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    kind = source.get("kind")
    if kind in {"career_page", "ats_page", "html", "public_html"}:
        url = source.get("url", "")
        if not url:
            return []
        return discover_links(url)
    if kind == "remotive_api":
        return discover_remotive(source, queries, locations)
    if kind == "arbeitnow_api":
        return discover_arbeitnow(source, queries, locations)
    if kind == "jobicy_api":
        return discover_jobicy(source, queries, locations)
    if kind == "himalayas_api":
        return discover_himalayas(source, queries, locations)
    if kind == "remoteok_api":
        return discover_remoteok(source, queries, locations)
    if kind == "rss":
        return discover_rss(source, queries, locations)
    if kind == "greenhouse_board":
        return discover_greenhouse_board(source, queries, locations)
    if kind == "lever_site":
        return discover_lever_site(source, queries, locations)
    if kind == "ashby_board":
        return discover_ashby_board(source, queries, locations)
    if kind == "linkedin_assisted":
        return []
    return []


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "JobCockpit/0.2 human-in-the-loop job search assistant",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read(3_000_000).decode("utf-8", errors="ignore"))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml, text/html",
            "User-Agent": "JobCockpit/0.2 human-in-the-loop job search assistant",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read(3_000_000).decode("utf-8", errors="ignore")


def matches_query(job: dict[str, Any], queries: list[str]) -> bool:
    text = " ".join(
        str(job.get(key, ""))
        for key in ("title", "description", "requirements", "tags")
    ).lower()
    for query in queries:
        terms = [term for term in query.lower().split() if len(term) > 2]
        if terms and all(term in text for term in terms):
            return True
    return bool(TITLE_HINT_RE.search(text))


def matches_location(job: dict[str, Any], locations: list[str]) -> bool:
    if not locations:
        return True
    blob = " ".join(str(job.get(key, "")) for key in ("location", "remote", "description")).lower()
    location_blob = str(job.get("location", "")).lower()
    normalized = [location.lower() for location in locations if location]
    only_remote = set(normalized).issubset({"remote", "anywhere", "worldwide", "global"})
    remote_terms = (
        "remote",
        "anywhere",
        "worldwide",
        "global",
        "work from home",
        "work from anywhere",
        "home office",
        "fully remote",
        "distributed team",
        "fully distributed",
    )
    if only_remote:
        return any(term in blob for term in remote_terms)
    restricted_terms = {
        "united states": ("united states", "usa", "u.s.", "us only", "puerto rico"),
        "canada": ("canada",),
        "latin america": ("latam", "latin america"),
        "australia": ("australia",),
        "new zealand": ("new zealand",),
    }
    for target, terms in restricted_terms.items():
        if any(term in location_blob for term in terms) and target not in normalized and "worldwide" not in normalized and "anywhere" not in normalized:
            return False
    worldwide_terms = ("worldwide", "anywhere", "global", "no location restriction", "remote - anywhere")
    if any(term in blob for term in worldwide_terms):
        return True
    for target, terms in restricted_terms.items():
        if any(term in blob for term in terms) and target not in normalized and "worldwide" not in normalized and "anywhere" not in normalized:
            return False
    if "remote" in blob and any(location in {"remote", "europe", "emea"} for location in normalized):
        return True
    return any(location in blob for location in normalized)


def discover_remotive(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    base_url = source.get("url") or "https://remotive.com/api/remote-jobs"
    results: list[dict[str, Any]] = []
    for query in queries:
        data = fetch_json(f"{base_url}?search={quote_plus(query)}")
        for item in data.get("jobs", []):
            job = {
                "title": item.get("title", ""),
                "company": item.get("company_name", ""),
                "location": item.get("candidate_required_location", "Remote"),
                "remote": "remote",
                "salary": item.get("salary", ""),
                "url": item.get("url", ""),
                "description": clean_html_text(item.get("description", "")),
                "requirements": item.get("tags", []),
            }
            if matches_query(job, queries) and matches_location(job, locations):
                results.append(job)
    return dedupe_jobs(results)


def discover_arbeitnow(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    base_url = source.get("url") or "https://www.arbeitnow.com/api/job-board-api"
    data = fetch_json(base_url)
    items = data.get("data", []) if isinstance(data, dict) else []
    results: list[dict[str, Any]] = []
    for item in items:
        job = {
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("location", ""),
            "remote": "remote" if item.get("remote") else "",
            "salary": "",
            "url": item.get("url", ""),
            "description": clean_html_text(item.get("description", "")),
            "requirements": item.get("tags", []),
        }
        if matches_query(job, queries) and matches_location(job, locations):
            results.append(job)
    return dedupe_jobs(results)


def discover_jobicy(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    base_url = source.get("url") or "https://jobicy.com/api/v2/remote-jobs"
    results: list[dict[str, Any]] = []
    geos = jobicy_geos(locations)
    for query in queries:
        for geo in geos:
            url = f"{base_url}?count=50&tag={quote_plus(query)}"
            if geo:
                url += f"&geo={quote_plus(geo)}"
            data = fetch_json(url)
            jobs = data.get("jobs", []) if isinstance(data, dict) else []
            for item in jobs:
                salary = ""
                if item.get("salaryMin") or item.get("salaryMax"):
                    salary = f"{item.get('salaryMin') or ''}-{item.get('salaryMax') or ''} {item.get('salaryCurrency') or ''}".strip("- ")
                job = {
                    "title": item.get("jobTitle", ""),
                    "company": item.get("companyName", ""),
                    "location": item.get("jobGeo", "Remote"),
                    "remote": "remote",
                    "salary": salary,
                    "url": item.get("url", ""),
                    "description": clean_html_text(item.get("jobDescription", "") or item.get("jobExcerpt", "")),
                    "requirements": [item.get("jobIndustry", ""), item.get("jobType", ""), item.get("jobLevel", "")],
                }
                if matches_query(job, queries) and matches_location(job, locations):
                    results.append(job)
    return dedupe_jobs(results)


def jobicy_geos(locations: list[str]) -> list[str]:
    if not locations:
        return [""]
    mapping = {
        "remote": "",
        "anywhere": "",
        "worldwide": "",
        "europe": "europe",
        "emea": "emea",
        "germany": "germany",
        "netherlands": "netherlands",
        "united kingdom": "uk",
        "uk": "uk",
        "usa": "usa",
        "united states": "usa",
        "canada": "canada",
        "poland": "poland",
        "georgia": "",
        "belarus": "",
    }
    geos = []
    for location in locations:
        key = location.strip().lower()
        if key in mapping and mapping[key] not in geos:
            geos.append(mapping[key])
    return geos or [""]


def discover_himalayas(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    base_url = source.get("url") or "https://himalayas.app/jobs/api"
    results: list[dict[str, Any]] = []
    for offset in (0, 20, 40):
        data = fetch_json(f"{base_url}?limit=20&offset={offset}")
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        for item in jobs:
            restrictions = item.get("locationRestrictions") or []
            salary = ""
            if item.get("minSalary") or item.get("maxSalary"):
                salary = f"{item.get('minSalary') or ''}-{item.get('maxSalary') or ''} {item.get('currency') or ''}".strip("- ")
            job = {
                "title": item.get("title", ""),
                "company": item.get("companyName", ""),
                "location": ", ".join(restrictions) or "Remote",
                "remote": "remote",
                "salary": salary,
                "url": item.get("applicationLink") or item.get("guid", ""),
                "description": clean_html_text(item.get("description", "") or item.get("excerpt", "")),
                "requirements": list(item.get("categories", []))[:12],
            }
            if matches_query(job, queries) and matches_location(job, locations):
                results.append(job)
    return dedupe_jobs(results)


def discover_remoteok(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    base_url = source.get("url") or "https://remoteok.com/api"
    data = fetch_json(base_url)
    items = data if isinstance(data, list) else []
    results: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("position"):
            continue
        job = {
            "title": item.get("position", ""),
            "company": item.get("company", ""),
            "location": item.get("location", "Remote"),
            "remote": "remote",
            "salary": item.get("salary", ""),
            "url": item.get("url", ""),
            "description": clean_html_text(item.get("description", "")),
            "requirements": item.get("tags", []),
        }
        if matches_query(job, queries) and matches_location(job, locations):
            results.append(job)
    return dedupe_jobs(results)


def discover_rss(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    url = source.get("url", "")
    if not url:
        return []
    root = ET.fromstring(fetch_text(url))
    results: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:80]:
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        description = clean_html_text(item.findtext("description", default=""))
        job = {
            "title": title,
            "company": source.get("name", ""),
            "location": "Remote",
            "remote": "remote",
            "url": link,
            "description": description,
            "requirements": [],
        }
        if matches_query(job, queries) and matches_location(job, locations):
            results.append(job)
    return dedupe_jobs(results)


def discover_greenhouse_board(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    token = greenhouse_token(source)
    if not token:
        return []
    data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{quote_plus(token)}/jobs?content=true")
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    results: list[dict[str, Any]] = []
    for item in jobs:
        location = ""
        if isinstance(item.get("location"), dict):
            location = str(item["location"].get("name", ""))
        description = clean_html_text(str(item.get("content") or ""))
        requirements = extract_requirements(description)
        job = {
            "title": item.get("title", ""),
            "company": source.get("company") or source.get("name", token),
            "location": location,
            "remote": infer_remote(f"{location}\n{description}"),
            "salary": "",
            "url": item.get("absolute_url", ""),
            "description": description,
            "requirements": requirements,
        }
        if matches_query(job, queries) and matches_location(job, locations):
            results.append(job)
    return dedupe_jobs(results)


def discover_lever_site(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    site = lever_site(source)
    if not site:
        return []
    data = fetch_json(f"https://api.lever.co/v0/postings/{quote_plus(site)}?mode=json")
    items = data if isinstance(data, list) else []
    results: list[dict[str, Any]] = []
    for item in items:
        categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
        sections = item.get("lists") if isinstance(item.get("lists"), list) else []
        list_text = " ".join(clean_html_text(str(section.get("content", ""))) for section in sections if isinstance(section, dict))
        description = clean_html_text(
            "\n".join(
                str(part or "")
                for part in [
                    item.get("openingPlain") or item.get("opening"),
                    item.get("descriptionPlain") or item.get("description"),
                    list_text,
                    item.get("additionalPlain") or item.get("additional"),
                ]
            )
        )
        location = str(categories.get("location") or ", ".join(categories.get("allLocations", []) or []) or "")
        job = {
            "title": item.get("text", ""),
            "company": source.get("company") or source.get("name", site),
            "location": location,
            "remote": str(item.get("workplaceType") or infer_remote(f"{location}\n{description}")),
            "salary": lever_salary(item.get("salaryRange")),
            "url": item.get("applyUrl") or item.get("hostedUrl", ""),
            "description": description,
            "requirements": extract_requirements(description),
        }
        if matches_query(job, queries) and matches_location(job, locations):
            results.append(job)
    return dedupe_jobs(results)


def discover_ashby_board(source: dict[str, Any], queries: list[str], locations: list[str]) -> list[dict[str, Any]]:
    org = ashby_org(source)
    if not org:
        return []
    data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{quote_plus(org)}")
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    results: list[dict[str, Any]] = []
    for item in jobs:
        secondary = item.get("secondaryLocations") if isinstance(item.get("secondaryLocations"), list) else []
        extra_locations = [str(loc.get("location", "")) for loc in secondary if isinstance(loc, dict) and loc.get("location")]
        location = ", ".join([str(item.get("location") or ""), *extra_locations]).strip(", ")
        description = clean_html_text(str(item.get("descriptionPlain") or item.get("descriptionHtml") or ""))
        salary = ""
        comp = item.get("compensation")
        if isinstance(comp, dict):
            salary = str(comp.get("compensationTierSummary") or comp.get("summary") or "")
        job = {
            "title": item.get("title", ""),
            "company": source.get("company") or source.get("name", org),
            "location": location,
            "remote": str(item.get("workplaceType") or ("remote" if item.get("isRemote") else infer_remote(f"{location}\n{description}"))),
            "salary": salary,
            "url": item.get("applyUrl") or item.get("jobUrl", ""),
            "description": description,
            "requirements": extract_requirements(description),
        }
        if matches_query(job, queries) and matches_location(job, locations):
            results.append(job)
    return dedupe_jobs(results)


def greenhouse_token(source: dict[str, Any]) -> str:
    explicit = str(source.get("board_token") or source.get("token") or "").strip()
    if explicit:
        return explicit
    parsed = urlparse(str(source.get("url") or ""))
    parts = [part for part in parsed.path.split("/") if part]
    if "boards-api.greenhouse.io" in parsed.netloc and "boards" in parts:
        index = parts.index("boards")
        return parts[index + 1] if len(parts) > index + 1 else ""
    if "greenhouse.io" in parsed.netloc and parts:
        return parts[0]
    return ""


def lever_site(source: dict[str, Any]) -> str:
    explicit = str(source.get("site") or source.get("token") or "").strip()
    if explicit:
        return explicit
    parsed = urlparse(str(source.get("url") or ""))
    parts = [part for part in parsed.path.split("/") if part]
    if "api.lever.co" in parsed.netloc and "postings" in parts:
        index = parts.index("postings")
        return parts[index + 1] if len(parts) > index + 1 else ""
    if "jobs.lever.co" in parsed.netloc and parts:
        return parts[0]
    return ""


def ashby_org(source: dict[str, Any]) -> str:
    explicit = str(source.get("org") or source.get("token") or "").strip()
    if explicit:
        return explicit
    parsed = urlparse(str(source.get("url") or ""))
    parts = [part for part in parsed.path.split("/") if part]
    if "api.ashbyhq.com" in parsed.netloc and "job-board" in parts:
        index = parts.index("job-board")
        return parts[index + 1] if len(parts) > index + 1 else ""
    if "jobs.ashbyhq.com" in parsed.netloc and parts:
        return parts[0]
    return ""


def lever_salary(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    currency = value.get("currency") or ""
    interval = value.get("interval") or ""
    minimum = value.get("min") or value.get("minimum")
    maximum = value.get("max") or value.get("maximum")
    if minimum or maximum:
        return f"{minimum or ''}-{maximum or ''} {currency} {interval}".strip("- ")
    return str(value.get("salaryDescription") or value.get("salaryDescriptionPlain") or "")


def dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for job in jobs:
        keys = job_keys(job)
        if seen.intersection(keys):
            continue
        seen.update(keys)
        unique.append(job)
    return unique


def discover_links(url: str) -> list[dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "JobCockpit/0.1 human-in-the-loop job search assistant"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read(900_000).decode("utf-8", errors="ignore")

    links: list[dict[str, str]] = []
    for href in LINK_RE.findall(body):
        full_url = urljoin(url, html.unescape(href))
        text_window = body[max(0, body.find(href) - 200) : body.find(href) + 300]
        text = re.sub(r"<[^>]+>", " ", text_window)
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if TITLE_HINT_RE.search(full_url) or TITLE_HINT_RE.search(text):
            title_match = TITLE_HINT_RE.search(text)
            title = title_match.group(0).title() if title_match else "Data role"
            links.append({"url": full_url, "title": title})
        if len(links) >= 40:
            break
    unique: dict[str, dict[str, str]] = {}
    for link in links:
        unique[link["url"]] = link
    return list(unique.values())


def run_agent(store: Store, mode: str) -> AgentResult:
    if mode == "score_all":
        return rescore_all(store)
    if mode == "draft_ready":
        return draft_ready_jobs(store)
    if mode == "package_ready":
        return draft_ready_jobs(store)
    if mode == "discover_sources":
        return discover_from_sources(store)
    if mode == "wide_search":
        discover = discover_from_sources(store, wide=True)
        score = rescore_all(store)
        draft = draft_ready_jobs(store)
        return AgentResult(
            True,
            "Wide search finished",
            {"discover": discover.payload, "score": score.payload, "draft": draft.payload},
        )
    if mode == "daily_review":
        discover = discover_from_sources(store)
        score = rescore_all(store)
        draft = draft_ready_jobs(store)
        return AgentResult(
            True,
            "Daily review finished",
            {"discover": discover.payload, "score": score.payload, "draft": draft.payload},
        )
    store.log("warning", f"Unknown agent mode: {mode}", {"mode": mode})
    return AgentResult(False, f"Unknown agent mode: {mode}", {"mode": mode})
