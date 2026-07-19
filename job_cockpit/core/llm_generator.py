from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openai_tools import DEFAULT_MODEL, OPENAI_ENV_FILE, OpenAIRequestUnavailable, call_openai_json, openai_api_key
from resume_generator import build_resume_payload, load_master_resume, validate_resume_payload
from storage import Store


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_CACHE_KEY = "reference_resume_text_cache"


class LLMGenerationUnavailable(RuntimeError):
    pass


HIGH_RISK_TOOL_TERMS = (
    "LookML",
    "Looker",
    "dbt",
    "Snowflake",
    "BigQuery",
    "Redshift",
    "Spark",
    "Databricks",
    "AWS",
    "GCP",
    "Azure",
    "Amplitude",
    "Mixpanel",
    "Segment",
    "Fivetran",
    "Dagster",
    "Prefect",
)


def openai_generation_status(store: Store) -> dict[str, Any]:
    workflow = store.get_json_setting("workflow", {})
    return {
        "enabled": bool(workflow.get("llm_generate_application_package", True)),
        "model": workflow.get("llm_model", DEFAULT_MODEL),
        "has_key": bool(openai_api_key()),
        "env_file_supported": str(OPENAI_ENV_FILE),
    }


def generate_llm_application_package(store: Store, job_id: int) -> dict[str, Any]:
    workflow = store.get_json_setting("workflow", {})
    if not workflow.get("llm_generate_application_package", True):
        raise LLMGenerationUnavailable("LLM application generation is disabled.")
    key = openai_api_key()
    if not key:
        raise LLMGenerationUnavailable("OPENAI_API_KEY is not configured.")

    model = str(workflow.get("llm_model") or DEFAULT_MODEL)
    timeout = int(workflow.get("llm_timeout_seconds", 45) or 45)
    master = load_master_resume(store)
    job = store.get_job(job_id)
    fallback_payload = build_resume_payload(master, job)
    reference_resume = load_reference_resume_text(store, master)
    context = build_generation_context(master, job, fallback_payload, workflow, reference_resume)
    try:
        response = call_openai_json(
            model=model,
            key=key,
            system_prompt=SYSTEM_PROMPT,
            context=context,
            timeout=timeout,
            max_output_tokens=5000,
        )
    except OpenAIRequestUnavailable as exc:
        raise LLMGenerationUnavailable(str(exc)) from exc
    package = normalize_llm_package(response)
    resume_payload = package["resume"]
    validate_resume_payload(resume_payload)
    validate_no_unsupported_terms(resume_payload, master, fallback_payload, reference_resume)
    package["cover_letter"] = sanitize_cover_letter(package["cover_letter"])
    try:
        validate_cover_letter(package["cover_letter"])
    except LLMGenerationUnavailable:
        package["cover_letter"] = build_safe_cover_letter(job, master)
        validate_cover_letter(package["cover_letter"])
    return {
        "resume": resume_payload,
        "cover_letter": package["cover_letter"],
        "fit_notes": package.get("fit_notes", []),
        "model": model,
        "usage": response.get("_usage", {}),
    }


def load_reference_resume_text(store: Store, master: dict[str, Any]) -> dict[str, Any]:
    path_text = str(master.get("standard_resume_path") or "").strip()
    if not path_text:
        return {"available": False, "path": "", "text": "", "error": "standard resume path is not configured"}
    path = Path(path_text).expanduser()
    try:
        stat = path.stat()
    except OSError as exc:
        return {"available": False, "path": str(path), "text": "", "error": f"reference resume is not readable: {exc}"}

    cache = store.get_json_setting(REFERENCE_CACHE_KEY, {})
    cache_key = {
        "path": str(path),
        "mtime": stat.st_mtime,
        "size": stat.st_size,
    }
    if isinstance(cache, dict) and all(cache.get(key) == value for key, value in cache_key.items()):
        text = str(cache.get("text", ""))
        if text:
            return {"available": True, "path": str(path), "text": text, "cached": True}

    text = extract_pdf_text(path)
    if not text:
        return {"available": False, "path": str(path), "text": "", "error": "no text extracted from reference resume"}
    text = normalize_reference_text(text)[:12_000]
    store.set_json_setting(REFERENCE_CACHE_KEY, {**cache_key, "text": text})
    return {"available": True, "path": str(path), "text": text, "cached": False}


def extract_pdf_text(path: Path) -> str:
    errors: list[str] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(page for page in pages if page.strip())
        if text.strip():
            return text
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pypdf: {exc}")
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(page for page in pages if page.strip())
        if text.strip():
            return text
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pdfplumber: {exc}")
    return ""


def normalize_reference_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_generation_context(
    master: dict[str, Any],
    job: dict[str, Any],
    fallback_payload: dict[str, Any],
    workflow: dict[str, Any],
    reference_resume: dict[str, Any],
) -> dict[str, Any]:
    max_description = int(workflow.get("llm_max_description_chars", 7000) or 7000)
    return {
        "rules_version": "2026-06-28",
        "candidate": {
            "master_resume": master,
            "fallback_resume_payload": fallback_payload,
            "reference_resume_pdf": reference_resume,
        },
        "job": {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "remote": job.get("remote", ""),
            "salary": job.get("salary", ""),
            "url": job.get("url", ""),
            "source": job.get("source", ""),
            "match_score": job.get("match_score", 0),
            "match_notes": job.get("match_notes", ""),
            "requirements": job.get("requirements", []),
            "description": str(job.get("description", ""))[:max_description],
        },
        "output_contract": {
            "resume": "Return the same shape as fallback_resume_payload.",
            "headline": "Choose the most vacancy-aligned truthful headline from master_resume.headline_variants or fallback_resume_payload.headline. Match the exact role title in job.title when the candidate facts support that seniority and specialization. Keep summary consistent with this headline.",
            "summary": "First 1-2 sentences must foreground the 2-3 most important competencies from job.requirements/description, expressed through the candidate's real matching experience, using the vacancy's own wording where it is truthfully supported. Concrete and human, not salesy.",
            "experience": "Rewrite bullets more strongly toward the vacancy using only source facts; lead each bullet with the responsibility, tool, domain, or outcome that maps to a job requirement, mirroring the vacancy's terminology where the source facts support it. Re-select and re-order which real bullets appear so several change per vacancy. Keep periods/employers/titles inside experience roles unchanged.",
            "cover_letter": "One paragraph, <= 100 words, specific to company/job, no generic AI phrasing.",
            "fit_notes": "Short factual notes explaining the tailoring choices, including which vacancy keywords you mirrored and which real experience backs each.",
        },
    }


SYSTEM_PROMPT = """You generate truthful, ATS-readable job application material for the candidate described in master_resume.

Rules:
- Return JSON only.
- Do not invent employers, dates, education, citizenship, work authorization, metrics, tools, or projects.
- Use only facts present in master_resume, fallback_resume_payload, or reference_resume_pdf.
- If reference_resume_pdf conflicts with master_resume, master_resume wins for facts; reference_resume_pdf is primarily a style and completeness reference.
- You may reorder, compress, emphasize, and rewrite real experience for relevance.
- Use truthful stretch: you may mirror vacancy language and connect adjacent real experience to the role, but never state unsupported tools, projects, domains, metrics, employers, or hands-on experience as facts.
- If an important vacancy requirement is not in the resume facts, do not add it to skills or bullets; at most mention adjacent experience in fit_notes or cover letter language without claiming direct experience.
- Preserve every real experience role and period from the master resume.
- Choose resume.headline to fit the vacancy as closely as possible, using master_resume.headline_variants or fallback_resume_payload.headline. When the candidate's real seniority and specialization support it, align the headline wording to job.title so a recruiter sees an immediate match.
- Open resume.summary with the 2-3 competencies the vacancy weighs most, evidenced by the candidate's real experience and phrased in the vacancy's language where truthfully supported, so the summary is impossible to skim past for relevance. Keep it factual, never fabricate scope or metrics to achieve this.
- Prefer a single clean target headline such as Senior Marketing Analytics Engineer, Senior Analytics Engineer, Senior Data Analyst, Senior Product Analyst, Senior Marketing Data Analyst, Product Affiliate Analyst, BI Analyst, or Data Scientist when supported by the candidate facts and vacancy.
- Do not restore older multi-title headlines such as Product Analyst | Retention Analyst | Data Scientist, and do not split the latest experience into a separate Data Scientist role.
- Make the first sentence of the summary consistent with the chosen headline; do not say "Senior Product Analyst" if resume.headline is "Senior Marketing Analytics Engineer".
- Before writing, extract the vacancy's key requirements and recurring terms from job.title, job.requirements, and job.description; treat those as the target keyword set for this application.
- For every requirement in that set that IS supported by the candidate facts, mirror the vacancy's own wording in the headline, summary, skills, or bullets so the alignment is obvious to a recruiter and to an ATS keyword scan. Do NOT invent support for requirements that are absent from the candidate facts.
- Rewrite experience bullets more aggressively for role relevance: foreground matching real responsibilities, tools, domains, stakeholders, metrics, infrastructure, dashboards, experiments, marketing/traffic/funnel work, AI automation, or analytics engineering depending on the vacancy. Lead each bullet with the matching keyword or outcome, not with a generic verb.
- Re-select and re-order which real bullets are shown per vacancy: the candidate has more real experience than fits, so surface the subset most aligned to this specific role and drop weakly-relevant bullets. Several bullets should visibly change between two different vacancies.
- Each generated experience section should feel purpose-built for the vacancy: latest role should usually have 5-7 strong bullets; older role should usually have 3-5 bullets. Do not simply copy the fallback bullets unchanged unless they are already the best fit.
- You may merge adjacent real bullets, compress wording, and mirror vacancy language when the source facts support it.
- Keep experience role period, company, and role title unchanged. Do not invent new employers, dates, promotions, departments, exact industries, or unsupported tools.
- Never copy vacancy-only tools into skills or bullets unless they are present in master_resume, fallback_resume_payload, or reference_resume_pdf. For example, if a job mentions LookML, Looker, dbt, Snowflake, BigQuery, AWS, GCP, or Amplitude but the candidate facts do not, leave those out and emphasize adjacent real experience instead.
- Do not include parenthetical vacancy markers such as "(preferred)", "(nice to have)", or "(required)" in the resume.
- Keep all bullets defensible in an interview.
- Do not include internal metadata such as "Tailored for", "Generated", "AI", "agent notes", or job-cockpit.
- Resume headings are handled by the PDF renderer; return content only.
- Summary should be human and concrete, not salesy.
- Highlights should be short evidence bullets copied or tightly paraphrased from real experience.
- Skills must be skills already present in the master resume.
- Avoid mass-generated rhythm: do not make every bullet the same abstract action verb + vague business outcome pattern.
- Do not overuse exact vacancy keywords when the real resume facts do not support them.
- Prefer concrete nouns from real experience over polished abstractions.
- Cover letter must be one paragraph, at most 100 words, and should mention why this company/role is interesting based on the job text.
- Avoid generic phrases: proven track record, results-oriented, dynamic, innovative, cutting-edge, tech-savvy, excellent communicator, team player, leveraging my expertise, fast-paced environment, I am excited to apply, I am excited about, I am thrilled to apply.

Expected JSON:
{
  "resume": {
    "name": "...",
    "headline": "...",
    "contacts": {...},
    "summary": "...",
    "highlights": ["...", "...", "..."],
    "skills": ["...", "..."],
    "experience": [
      {"company":"...", "title":"...", "period":"...", "duration":"...", "context":"...", "bullets":["...", "..."]}
    ],
    "education": [...],
    "training": [...],
    "target": {"title":"...", "company":""}
  },
  "cover_letter": "...",
  "fit_notes": ["...", "..."]
}
"""


def normalize_llm_package(value: dict[str, Any]) -> dict[str, Any]:
    resume = value.get("resume")
    cover_letter = value.get("cover_letter")
    if not isinstance(resume, dict):
        raise LLMGenerationUnavailable("LLM package is missing resume object.")
    if not isinstance(cover_letter, str) or not cover_letter.strip():
        raise LLMGenerationUnavailable("LLM package is missing cover_letter.")
    fit_notes = value.get("fit_notes", [])
    if not isinstance(fit_notes, list):
        fit_notes = [str(fit_notes)]
    return {
        "resume": resume,
        "cover_letter": re.sub(r"\s+", " ", cover_letter).strip(),
        "fit_notes": [str(item).strip() for item in fit_notes if str(item).strip()][:8],
    }


def sanitize_cover_letter(text: str) -> str:
    replacements = {
        r"\bI am excited about\b": "I am interested in",
        r"\bI am excited to apply for\b": "I am applying for",
        r"\bI am thrilled to apply for\b": "I am applying for",
        r"\bI am thrilled about\b": "I am interested in",
    }
    cleaned = re.sub(r"\s+", " ", text).strip()
    for pattern, replacement in replacements.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned


def build_safe_cover_letter(job: dict[str, Any], master: dict[str, Any]) -> str:
    company = str(job.get("company") or "your team").strip()
    title = str(job.get("title") or "this role").strip()
    skills: list[str] = []
    for group in ("analytics", "tools", "engineering", "data_science"):
        values = master.get("skills", {}).get(group, [])
        if isinstance(values, list):
            skills.extend(str(item) for item in values)
    selected = [skill for skill in skills if skill in {"SQL", "Python", "Tableau", "Power BI", "Marketing Analytics", "Product Analytics", "A/B Testing", "API integrations", "Docker"}]
    selected_text = ", ".join(selected[:6]) or "SQL, Python, dashboards and product analytics"
    return (
        f"Hi {company} team, I would like to work with you as {title}. "
        f"My experience in product, traffic and marketing analytics includes {selected_text}, dashboarding, KPI monitoring, and analytics infrastructure work. "
        f"I can help connect business questions with reliable data, reporting, experiments and automation."
    )


def validate_no_unsupported_terms(
    resume_payload: dict[str, Any],
    master: dict[str, Any],
    fallback_payload: dict[str, Any],
    reference_resume: dict[str, Any],
) -> None:
    source_text = "\n".join(
        [
            json.dumps(master, ensure_ascii=False),
            json.dumps(fallback_payload, ensure_ascii=False),
            str(reference_resume.get("text", "")),
        ]
    ).lower()
    payload_text = json.dumps(resume_payload, ensure_ascii=False).lower()
    leaked = [
        term
        for term in HIGH_RISK_TOOL_TERMS
        if term.lower() in payload_text and term.lower() not in source_text
    ]
    if leaked:
        raise LLMGenerationUnavailable(f"LLM resume contains unsupported tool terms: {', '.join(leaked)}")
    if "(preferred)" in payload_text or "(nice to have)" in payload_text or "(required)" in payload_text:
        raise LLMGenerationUnavailable("LLM resume contains vacancy marker text such as preferred/nice-to-have/required.")


FORBIDDEN_TEXT_RE = re.compile(
    r"\b(proven track record|results-oriented|dynamic|innovative|cutting-edge|tech-savvy|excellent communicator|team player|leveraging my expertise|fast-paced environment|i am excited to apply|i am excited about|i am thrilled to apply|as an ai)\b",
    re.IGNORECASE,
)


def validate_cover_letter(text: str) -> None:
    if len(text.split()) > 100:
        raise LLMGenerationUnavailable(f"Cover letter is too long: {len(text.split())} words.")
    if "\n\n" in text.strip():
        raise LLMGenerationUnavailable("Cover letter must be one paragraph.")
    if FORBIDDEN_TEXT_RE.search(text):
        raise LLMGenerationUnavailable("Cover letter contains forbidden generic AI-style phrasing.")


def redact_secret(value: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", value)
