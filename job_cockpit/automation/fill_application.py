from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
VENDOR = ROOT / "vendor"
BROWSERS = ROOT / "ms-playwright"
AUDIT_DIR = ROOT.parent / "output" / "automation_runs"
APPLICATION_ANSWERS = ROOT / "config" / "application_answers.json"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))
sys.path.insert(0, str(CORE))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS))

from forms import build_field_payload  # noqa: E402
from openai_tools import DEFAULT_MODEL, OpenAIRequestUnavailable, call_openai_json, openai_api_key  # noqa: E402
from storage import Store  # noqa: E402


FIELD_RULES: list[tuple[str, str]] = [
    ("first_name", r"first\s*name|given\s*name|forename"),
    ("last_name", r"last\s*name|family\s*name|surname"),
    ("full_name", r"full\s*name|legal\s*name|your\s*name|^name$"),
    ("email", r"e-?mail|email"),
    ("phone", r"phone|mobile|telephone"),
    ("linkedin_url", r"linkedin|linked\s*in"),
    ("github_url", r"github"),
    ("portfolio_url", r"portfolio|website|personal\s*site"),
    ("current_title", r"current\s*(job\s*)?title|current\s*position|current\s*role|job\s*title"),
    ("current_company", r"current\s*company|current\s*employer|employer\s*name"),
    ("location", r"current\s*location|location|address"),
    ("city", r"\bcity\b|town|municipality"),
    ("country", r"country|country/region"),
    ("postal_code", r"postal|zip\s*code|postcode"),
    ("timezone", r"time\s*zone|timezone"),
    ("employment_type", r"employment\s*type|contract\s*type"),
    ("english_level", r"english\s*(level|proficiency)|language\s*level"),
    ("highest_degree", r"highest\s*degree|education\s*level|degree"),
    ("years_total", r"years.*(experience|professional)|total.*experience"),
    ("years_sql", r"years.*sql|sql.*years"),
    ("years_python", r"years.*python|python.*years"),
    ("years_bi", r"years.*(tableau|power\s*bi|looker|dashboard|bi)|bi.*years"),
    ("work_authorization", r"work\s*authorization|authorized|eligible.*work|right.*work|visa|sponsorship"),
    ("salary_expectation", r"salary|compensation|expected\s*pay|desired\s*pay"),
    ("notice_period", r"notice\s*period|start\s*date|available"),
    ("cover_letter", r"cover\s*letter|motivation|why.*interested|message.*hiring|additional\s*information"),
]

SAFE_FIELD_KEYS = {field for field, _pattern in FIELD_RULES} | {
    "resume_path",
    "job_title",
    "company",
    "work_format",
    "remote_preference",
    "remote_ok",
    "willing_remote",
    "willing_to_relocate",
    "work_authorized",
    "requires_sponsorship",
    "authorized_countries",
    "eeo_race",
    "eeo_gender",
    "eeo_veteran_status",
    "eeo_disability_status",
    "legal_consent_application_processing",
    "legal_consent_privacy",
}

CONTROLLED_EEO_KEYS = {
    "eeo_race",
    "eeo_gender",
    "eeo_veteran_status",
    "eeo_disability_status",
}
CONTROLLED_LEGAL_KEYS = {
    "legal_consent_application_processing",
    "legal_consent_privacy",
}
LLM_ALLOWED_TEXT_CATEGORIES = {
    "safe_experience",
    "safe_motivation",
    "safe_tools",
    "safe_profile",
    "safe_availability",
    "controlled_factual",
}
SENSITIVE_FACTUAL_LABEL_RE = re.compile(
    r"\b(salary|compensation|pay|notice period|start date|available|availability|relocat|authorized|eligible.*work|right.*work|work authorization|visa|sponsorship)\b",
    re.IGNORECASE,
)
LLM_SCREENING_SYSTEM_PROMPT = """You answer safe job application screening fields for Pavel Mishelutau.

Return JSON only:
{"answers":[{"field_id":"...","answer":"...","category":"safe_experience","confidence":0.0,"source_facts":["..."]}]}

Allowed categories:
- safe_experience: relevant real experience from the resume context.
- safe_motivation: short why-role/why-company answer based on job text.
- safe_tools: tools/skills already present in the resume context.
- safe_profile: LinkedIn/portfolio/profile text already present in context.
- safe_availability: availability text only if explicit answer_profile value exists.
- controlled_factual: salary, notice, relocation, work authorization, or sponsorship only if explicit answer_profile value exists.

Blocked categories:
- blocked_security: CAPTCHA, passwords, login, MFA, OTP, anti-bot, account recovery.
- blocked_legal: broad terms, background checks, arbitration, marketing, newsletters, account creation, legal acknowledgements.
- blocked_eeo_missing_explicit: race, gender, veteran, disability, EEO, demographic fields unless explicit answer_profile value exists.
- blocked_work_auth_missing_explicit: work authorization/sponsorship without explicit answer_profile value.
- blocked_salary_missing_explicit: salary/notice without explicit answer_profile value.
- unknown: unclear field or not enough source facts.

Rules:
- Do not invent facts, employers, dates, tools, metrics, citizenship, visa/sponsorship, relocation, salary, notice period, or authorization.
- Keep answers concise: one sentence for input fields, two short sentences for textarea fields.
- If confidence is below 0.65, return a blocked/unknown category with an empty answer.
- Never answer CAPTCHA, password, login, MFA, OTP, security, or anti-bot fields.
- Legal consent and EEO choices are handled by the deterministic answer bank, not by free-form generation.
"""


async def fill_application(args: argparse.Namespace) -> int:
    try:
        sys.modules.pop("playwright", None)
        sys.modules.pop("playwright.async_api", None)
        if VENDOR.exists():
            vendor_text = str(VENDOR)
            sys.path = [vendor_text] + [path for path in sys.path if path != vendor_text]
        from playwright.async_api import async_playwright
    except ImportError as exc:
        print("Playwright is not installed. Install optional dependencies first:")
        print("  python -m pip install -r job_cockpit/requirements-optional.txt")
        print("  python -m playwright install chromium")
        print(f"Import error: {exc}")
        try:
            import playwright

            print(f"Playwright package: {getattr(playwright, '__file__', '')}")
            print(f"Playwright path: {list(getattr(playwright, '__path__', []))}")
        except Exception as debug_exc:  # noqa: BLE001
            print(f"Playwright package debug failed: {debug_exc}")
        print(f"Vendor async_api exists: {(VENDOR / 'playwright' / 'async_api').exists()}")
        print(f"sys.path head: {sys.path[:8]}")
        return 2

    store = Store(args.db)
    profile = load_profile(args.profile) if args.profile else store.get_json_setting("profile", {})
    job = (
        store.get_job(args.job_id)
        if args.job_id
        else {"title": args.title or "", "company": args.company or "", "cover_letter": args.cover_letter or ""}
    )
    answer_profile = load_application_answers(args.answers, profile, store)
    fields = enrich_field_payload(build_field_payload(profile, job), profile, job, answer_profile, store)

    async with async_playwright() as p:
        context, browser = await open_context(p, args)
        page = context.pages[0] if context.pages else await context.new_page()
        await safe_goto(page, args.url, timeout=60_000)
        await settle(page)

        if args.auto_open_apply:
            page = await open_apply_target(page)
            await settle(page)

        if await has_captcha(page):
            print("Paused: CAPTCHA/security challenge detected. Solve it manually in the browser, then rerun if needed.")
            audit_info = await write_audit(
                page,
                args,
                job,
                fields,
                {
                    "text_fields": 0,
                    "skill_ratings": 0,
                    "selects": 0,
                    "choices": 0,
                    "controlled_choices": 0,
                    "llm_text_fields": 0,
                    "uploads": 0,
                    "manual_fields": 0,
                },
                {"submitted": False, "message": "human handoff - CAPTCHA/security challenge detected", "reasons": ["CAPTCHA/security challenge detected"]},
                [],
                [],
            )
            print(f"AUDIT_PATH: {audit_info['path']}")
            await wait_for_human(context, args)
            await close_browser(context, browser)
            return 3

        text_filled = await fill_text_fields(page, fields)
        skill_ratings = await fill_skill_rating_fields(page)
        selected = await fill_selects(page, fields)
        choices = await fill_choice_fields(page, fields)
        controlled = await fill_controlled_choice_fields(page, answer_profile, store)
        llm_result = await run_llm_screening_autofill(page, store, job, fields, answer_profile)
        uploaded = await attach_resume(page, fields.get("resume_path", ""))
        manual = await highlight_manual_fields(page)
        await highlight_submit_buttons(page)
        llm_field_answers = controlled["answers"] + llm_result["answers"]

        metrics = {
            "text_fields": text_filled,
            "skill_ratings": skill_ratings,
            "selects": selected,
            "choices": choices,
            "controlled_choices": controlled["filled"],
            "llm_text_fields": llm_result["filled"],
            "uploads": uploaded,
            "manual_fields": len(manual),
        }
        if args.auto_submit_safe:
            submit_result = await submit_if_safe(page)
            if submit_result["submitted"] and args.mark_applied_on_submit and args.job_id:
                mark_job_applied(store, args.job_id, submit_result)
            audit_info = await write_audit(page, args, job, fields, metrics, submit_result, manual, llm_field_answers)
            print(f"AUDIT_PATH: {audit_info['path']}")
            print(
                "Filled "
                f"{text_filled} text fields, {skill_ratings} skill rating(s), selected {selected} dropdowns, uploaded {uploaded} file(s). "
                f"Selected {choices} choice field(s), controlled {controlled['filled']} sensitive choice(s). "
                f"LLM filled {llm_result['filled']} screening field(s). Highlighted {len(manual)} manual fields. "
                f"Auto-submit: {submit_result['message']}"
            )
        else:
            readiness = await evaluate_submit_readiness(page)
            submit_result = {
                "submitted": False,
                "message": "not clicked - manual review mode",
                "reasons": readiness.get("reasons", []),
                "readiness": readiness,
            }
            audit_info = await write_audit(page, args, job, fields, metrics, submit_result, manual, llm_field_answers)
            print(f"AUDIT_PATH: {audit_info['path']}")
            print(
                "Filled "
                f"{text_filled} text fields, {skill_ratings} skill rating(s), selected {selected} dropdowns, uploaded {uploaded} file(s). "
                f"Selected {choices} choice field(s), controlled {controlled['filled']} sensitive choice(s). "
                f"LLM filled {llm_result['filled']} screening field(s). Highlighted {len(manual)} manual fields. "
                "Final submit was not clicked."
            )
        await wait_for_human(context, args)
        await close_browser(context, browser)
        return 0


async def open_context(playwright: Any, args: argparse.Namespace) -> tuple[Any, Any | None]:
    launch_options: dict[str, Any] = {"headless": args.headless}
    if args.slow_mo:
        launch_options["slow_mo"] = args.slow_mo
    if args.user_data_dir:
        profile_dir = Path(args.user_data_dir).expanduser()
        profile_dir.mkdir(parents=True, exist_ok=True)
        context = await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            viewport={"width": 1360, "height": 920},
            **launch_options,
        )
        return context, None
    browser = await playwright.chromium.launch(**launch_options)
    context = await browser.new_context(viewport={"width": 1360, "height": 920})
    return context, browser


async def close_browser(context: Any, browser: Any | None) -> None:
    try:
        await context.close()
    except Exception:  # noqa: BLE001
        pass
    if browser:
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass


def load_profile(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_application_answers(path: str, profile: dict[str, Any], store: Store) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for candidate in [APPLICATION_ANSWERS, Path(path).expanduser() if path else None]:
        if not candidate:
            continue
        try:
            if candidate.exists():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    answers.update(data)
        except Exception as exc:  # noqa: BLE001
            print(f"Could not load application answers from {candidate}: {exc}")
    stored = store.get_json_setting("application_answers", {})
    if isinstance(stored, dict):
        answers.update(stored)
    embedded = profile.get("application_answers", {})
    if isinstance(embedded, dict):
        answers.update(embedded)
    return answers


def enrich_field_payload(
    fields: dict[str, Any],
    profile: dict[str, Any],
    job: dict[str, Any],
    answers: dict[str, Any],
    store: Store,
) -> dict[str, Any]:
    enriched = dict(fields)
    master = store.get_json_setting("resume_master", {}) or {}
    contacts = master.get("contacts", {}) if isinstance(master.get("contacts"), dict) else {}
    experience = master.get("experience", []) if isinstance(master.get("experience"), list) else []
    education = master.get("education", []) if isinstance(master.get("education"), list) else []
    current = experience[0] if experience and isinstance(experience[0], dict) else {}
    degree = education[0] if education and isinstance(education[0], dict) else {}

    if not enriched.get("full_name") and master.get("name"):
        enriched["full_name"] = str(master.get("name"))
        parts = str(master.get("name")).split()
        if parts and not enriched.get("first_name"):
            enriched["first_name"] = parts[0]
        if len(parts) > 1 and not enriched.get("last_name"):
            enriched["last_name"] = parts[-1]

    contact_map = {
        "phone": "phone",
        "email": "email",
        "location": "location",
        "work_authorization": "work_authorization",
        "employment_type": "employment_type",
        "work_format": "work_format",
        "citizenship": "citizenship",
    }
    for field, source in contact_map.items():
        if not enriched.get(field) and contacts.get(source):
            enriched[field] = str(contacts.get(source))

    defaults = {
        "current_title": current.get("title", ""),
        "current_company": current.get("company", ""),
        "highest_degree": degree.get("degree", ""),
        "job_title": job.get("title", ""),
        "company": job.get("company", ""),
    }
    for field, value in defaults.items():
        if value and not enriched.get(field):
            enriched[field] = str(value)

    for source in [profile, answers]:
        for key, value in source.items():
            if key == "application_answers":
                continue
            if key not in SAFE_FIELD_KEYS:
                continue
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            enriched[key] = value
    return enriched


async def settle(page: Any) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:  # noqa: BLE001
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=4_000)
    except Exception:  # noqa: BLE001
        pass


async def safe_goto(page: Any, url: str, timeout: int = 45_000) -> bool:
    for wait_until in ("domcontentloaded", "load", "commit"):
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout)
            return True
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "net::ERR_ABORTED" in message or "maybe frame was detached" in message:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=8_000)
                    return True
                except Exception:  # noqa: BLE001
                    continue
            if wait_until == "commit":
                print(f"Navigation failed: {message.splitlines()[0]}")
                return False
    return False


async def has_captcha(page: Any) -> bool:
    selectors = [
        'iframe[src*="recaptcha"]',
        'iframe[src*="hcaptcha"]',
        ".g-recaptcha",
        ".h-captcha",
        '[name*="captcha" i]',
        '[id*="captcha" i]',
        '[class*="captcha" i]',
    ]
    for selector in selectors:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def open_apply_target(page: Any) -> Any:
    if await count_application_controls(page) >= 4:
        return page
    link = await find_apply_link(page)
    if link:
        if await safe_goto(page, link, timeout=45_000):
            return page
    clicked_page = await click_apply_button(page)
    return clicked_page or page


async def count_application_controls(page: Any) -> int:
    return int(
        await page.evaluate(
            """
            () => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              return Array.from(document.querySelectorAll("input, textarea, select")).filter((el) => {
                const type = (el.getAttribute("type") || "").toLowerCase();
                return visible(el) && !["hidden", "submit", "button"].includes(type);
              }).length;
            }
            """
        )
    )


async def find_apply_link(page: Any) -> str:
    links = await page.evaluate(
        """
        () => Array.from(document.querySelectorAll("a[href]")).map((el) => ({
          href: el.getAttribute("href") || "",
          text: `${el.innerText || ""} ${el.getAttribute("aria-label") || ""}`.trim(),
          visible: (() => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
          })()
        }))
        """
    )
    for item in links:
        text = str(item.get("text") or "").lower()
        href = str(item.get("href") or "")
        if not item.get("visible") or not href or href.startswith(("mailto:", "tel:")):
            continue
        if re.search(r"\b(apply|apply now|apply for this job|start application|easy apply)\b", text):
            return urljoin(page.url, href)
    return ""


async def click_apply_button(page: Any) -> Any | None:
    buttons = page.locator('button, [role="button"]')
    count = min(await buttons.count(), 35)
    for index in range(count):
        button = buttons.nth(index)
        try:
            label = await button.evaluate(
                """
                (el) => {
                  const style = window.getComputedStyle(el);
                  const rect = el.getBoundingClientRect();
                  const visible = style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                  return {
                    visible,
                    text: `${el.innerText || ""} ${el.getAttribute("aria-label") || ""}`.trim(),
                    type: (el.getAttribute("type") || "").toLowerCase(),
                    inForm: Boolean(el.closest("form"))
                  };
                }
                """
            )
            text = str(label.get("text") or "").lower()
            if not label.get("visible") or label.get("type") == "submit" or label.get("inForm"):
                continue
            if re.search(r"\b(apply|apply now|apply for this job|start application|easy apply)\b", text):
                before_pages = list(page.context.pages)
                await button.click(timeout=2_000)
                await asyncio.sleep(1)
                after_pages = list(page.context.pages)
                for candidate in after_pages:
                    if candidate not in before_pages and not candidate.is_closed():
                        await candidate.bring_to_front()
                        return candidate
                return page
        except Exception:  # noqa: BLE001
            continue
    return None


async def fill_text_fields(page: Any, fields: dict[str, Any]) -> int:
    rules = [
        {"field": field, "pattern": pattern, "value": fields.get(field, "")}
        for field, pattern in FIELD_RULES
        if fields.get(field)
    ]
    return int(
        await page.evaluate(
            """
            ({ rules }) => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder"),
                  el.getAttribute("name"),
                  el.getAttribute("id"),
                  el.getAttribute("autocomplete")
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                if (wrapper) parts.push((wrapper.innerText || "").slice(0, 180));
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").toLowerCase();
              };
              const setValue = (el, value) => {
                const prototype = Object.getPrototypeOf(el);
                const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
                if (descriptor && descriptor.set) {
                  descriptor.set.call(el, value);
                } else {
                  el.value = value;
                }
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
              };
              let filled = 0;
              for (const el of document.querySelectorAll("input, textarea")) {
                const type = (el.getAttribute("type") || "").toLowerCase();
                if (["hidden", "password", "submit", "button", "checkbox", "radio", "file"].includes(type)) continue;
                if (!visible(el) || el.disabled || el.readOnly || el.value) continue;
                const label = textFor(el);
                for (const rule of rules) {
                  if (new RegExp(rule.pattern, "i").test(label)) {
                    setValue(el, rule.value);
                    el.style.outline = "2px solid #2f9e44";
                    el.style.outlineOffset = "2px";
                    filled += 1;
                    break;
                  }
                }
              }
              return filled;
            }
            """,
            {"rules": rules},
        )
    )


async def fill_skill_rating_fields(page: Any) -> int:
    return int(
        await page.evaluate(
            """
            () => {
              const ratings = [
                { pattern: /\\bsql\\b|postgres|mysql|mssql|snowflake|bigquery/, value: "8" },
                { pattern: /power\\s*bi/, value: "7" },
                { pattern: /tableau|looker|dashboard|bi\\b/, value: "7" },
                { pattern: /python|pandas/, value: "8" },
                { pattern: /statistics|statistical|a\\/b|ab testing|experiment/, value: "7" },
                { pattern: /machine learning|ml\\b|data science/, value: "6" }
              ];
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder"),
                  el.getAttribute("name"),
                  el.getAttribute("id")
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                if (wrapper) parts.push((wrapper.innerText || "").slice(0, 220));
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").toLowerCase();
              };
              const setValue = (el, value) => {
                const prototype = Object.getPrototypeOf(el);
                const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
                if (descriptor && descriptor.set) {
                  descriptor.set.call(el, value);
                } else {
                  el.value = value;
                }
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                el.style.outline = "2px solid #2f9e44";
                el.style.outlineOffset = "2px";
              };
              const ratingPrompt = /rate|rating|scale|level|knowledge|experience|proficiency|from\\s+1|1\\s*-\\s*10|1\\s*to\\s*10/;
              let filled = 0;
              for (const el of document.querySelectorAll("input, select")) {
                const type = (el.getAttribute("type") || "").toLowerCase();
                if (["hidden", "password", "submit", "button", "checkbox", "radio", "file"].includes(type)) continue;
                if (!visible(el) || el.disabled || el.readOnly || el.value) continue;
                const label = textFor(el);
                if (!ratingPrompt.test(label)) continue;
                const match = ratings.find((item) => item.pattern.test(label));
                if (!match) continue;
                if (el.tagName.toLowerCase() === "select") {
                  const option = Array.from(el.options || []).find((candidate) => {
                    const text = `${candidate.text || ""} ${candidate.value || ""}`.trim();
                    return text === match.value || text.startsWith(`${match.value} `);
                  });
                  if (!option) continue;
                  el.value = option.value;
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                  el.dispatchEvent(new Event("change", { bubbles: true }));
                  el.style.outline = "2px solid #2f9e44";
                  el.style.outlineOffset = "2px";
                } else {
                  setValue(el, match.value);
                }
                filled += 1;
              }
              return filled;
            }
            """
        )
    )


async def fill_selects(page: Any, fields: dict[str, Any]) -> int:
    return int(
        await page.evaluate(
            """
            ({ fields }) => {
              const yesNo = (value) => {
                if (value === true || value === false) return value;
                const clean = String(value ?? "").trim().toLowerCase();
                if (["yes", "true", "1", "y"].includes(clean)) return true;
                if (["no", "false", "0", "n"].includes(clean)) return false;
                return null;
              };
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder"),
                  el.getAttribute("name"),
                  el.getAttribute("id")
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                if (wrapper) parts.push((wrapper.innerText || "").slice(0, 160));
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").toLowerCase();
              };
              const choose = (select, predicate) => {
                const options = Array.from(select.options || []);
                const option = options.find((candidate) => predicate((candidate.text || "").trim().toLowerCase(), String(candidate.value || "").toLowerCase()));
                if (!option) return false;
                select.value = option.value;
                select.dispatchEvent(new Event("input", { bubbles: true }));
                select.dispatchEvent(new Event("change", { bubbles: true }));
                select.style.outline = "2px solid #2f9e44";
                select.style.outlineOffset = "2px";
                return true;
              };
              const chooseYesNo = (select, answer) => choose(select, (text, value) => {
                const combined = `${text} ${value}`;
                if (answer === true) return /\\byes\\b|authorized|eligible|allowed|able/.test(combined);
                return /\\bno\\b|not require|without|do not|don't|none/.test(combined);
              });
              const chooseContains = (select, value) => {
                const clean = String(value || "").trim().toLowerCase();
                if (!clean) return false;
                return choose(select, (text, optionValue) => clean.includes(text) || text.includes(clean) || clean.includes(optionValue) || optionValue.includes(clean));
              };
              let selected = 0;
              const workAuthorized = yesNo(fields.work_authorized);
              const requiresSponsorship = yesNo(fields.requires_sponsorship);
              for (const select of document.querySelectorAll("select")) {
                if (!visible(select) || select.disabled || select.value) continue;
                const label = textFor(select);
                let changed = false;
                if (/sponsorship|visa/.test(label) && requiresSponsorship !== null) {
                  changed = chooseYesNo(select, requiresSponsorship);
                } else if (/authorized|eligible.*work|right.*work|work authorization/.test(label) && workAuthorized !== null) {
                  changed = chooseYesNo(select, workAuthorized);
                } else if (/country/.test(label)) {
                  changed = chooseContains(select, fields.country);
                } else if (/city/.test(label)) {
                  changed = chooseContains(select, fields.city);
                } else if (/location/.test(label)) {
                  changed = chooseContains(select, fields.location);
                } else if (/english|language/.test(label)) {
                  changed = chooseContains(select, fields.english_level);
                } else if (/employment|contract/.test(label)) {
                  changed = chooseContains(select, fields.employment_type);
                } else if (/remote|work\\s*model|work\\s*format/.test(label)) {
                  changed = chooseContains(select, fields.work_format || fields.remote_preference);
                }
                if (changed) selected += 1;
              }
              return selected;
            }
            """,
            {"fields": fields},
        )
    )


async def fill_choice_fields(page: Any, fields: dict[str, Any]) -> int:
    return int(
        await page.evaluate(
            """
            ({ fields }) => {
              const yesNo = (value) => {
                if (value === true || value === false) return value;
                const clean = String(value ?? "").trim().toLowerCase();
                if (["yes", "true", "1", "y"].includes(clean)) return true;
                if (["no", "false", "0", "n"].includes(clean)) return false;
                return null;
              };
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder"),
                  el.getAttribute("name"),
                  el.getAttribute("id"),
                  el.value
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                if (wrapper) parts.push((wrapper.innerText || "").slice(0, 220));
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").toLowerCase();
              };
              const checkedSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "checked")?.set;
              const setChecked = (el) => {
                if (checkedSetter) checkedSetter.call(el, true);
                else el.checked = true;
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                el.style.outline = "2px solid #2f9e44";
                el.style.outlineOffset = "2px";
              };
              const forbidden = /privacy|terms|consent|gdpr|agreement|agree|acknowledge|race|ethnicity|gender|veteran|disability|eeo|equal employment|password|captcha|security|otp|2fa|mfa|newsletter|marketing/;
              const wantsYes = /\\byes\\b|authorized|eligible|allowed|able|i do|i can/;
              const wantsNo = /\\bno\\b|not require|without|do not|don't|none|not applicable|n\\/a/;
              const pickInGroup = (inputs, answer) => {
                for (const input of inputs) {
                  if (!visible(input) || input.disabled || input.checked) continue;
                  const label = textFor(input);
                  if (forbidden.test(label)) continue;
                  if (answer === true && wantsYes.test(label)) {
                    setChecked(input);
                    return true;
                  }
                  if (answer === false && wantsNo.test(label)) {
                    setChecked(input);
                    return true;
                  }
                }
                return false;
              };
              let filled = 0;
              const workAuthorized = yesNo(fields.work_authorized);
              const requiresSponsorship = yesNo(fields.requires_sponsorship);
              const willingRemote = yesNo(fields.remote_ok ?? fields.willing_remote);
              const willingRelocate = yesNo(fields.willing_to_relocate);

              const radioGroups = new Map();
              for (const input of document.querySelectorAll('input[type="radio"]')) {
                const name = input.name || input.id || String(radioGroups.size);
                if (!radioGroups.has(name)) radioGroups.set(name, []);
                radioGroups.get(name).push(input);
              }
              for (const inputs of radioGroups.values()) {
                if (inputs.some((input) => input.checked)) continue;
                const groupLabel = inputs.map(textFor).join(" ");
                if (forbidden.test(groupLabel)) continue;
                let answer = null;
                if (/sponsorship|visa/.test(groupLabel)) answer = requiresSponsorship;
                else if (/authorized|eligible.*work|right.*work|work authorization/.test(groupLabel)) answer = workAuthorized;
                else if (/remote|work\\s*from\\s*home|distributed/.test(groupLabel)) answer = willingRemote;
                else if (/relocat/.test(groupLabel)) answer = willingRelocate;
                if (answer !== null && pickInGroup(inputs, answer)) filled += 1;
              }

              for (const input of document.querySelectorAll('input[type="checkbox"]')) {
                if (!visible(input) || input.disabled || input.checked) continue;
                const label = textFor(input);
                if (forbidden.test(label)) continue;
                if (/remote|work\\s*from\\s*home|distributed/.test(label) && willingRemote === true) {
                  setChecked(input);
                  filled += 1;
                } else if (/relocat/.test(label) && willingRelocate === true) {
                  setChecked(input);
                  filled += 1;
                }
              }
              return filled;
            }
            """,
            {"fields": fields},
        )
    )


async def fill_controlled_choice_fields(page: Any, answers: dict[str, Any], store: Store) -> dict[str, Any]:
    workflow = store.get_json_setting("workflow", {})
    controlled: dict[str, Any] = {}
    if workflow.get("auto_fill_eeo_from_answers", True):
        for key in CONTROLLED_EEO_KEYS:
            value = answers.get(key)
            if isinstance(value, str) and value.strip():
                controlled[key] = value.strip()
    if workflow.get("auto_fill_legal_consent_from_answers", True):
        for key in CONTROLLED_LEGAL_KEYS:
            value = coerce_bool(answers.get(key))
            if value is True:
                controlled[key] = True
    if not controlled:
        return {"filled": 0, "answers": []}
    actions = list(
        await page.evaluate(
            """
            ({ answers }) => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder"),
                  el.getAttribute("name"),
                  el.getAttribute("id"),
                  el.value
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                const legend = el.closest("fieldset")?.querySelector("legend");
                if (legend) parts.push(legend.innerText);
                const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                if (wrapper) parts.push((wrapper.innerText || "").slice(0, 260));
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
              };
              const choiceText = (el) => {
                const parts = [
                  el.value,
                  el.getAttribute("aria-label"),
                  el.getAttribute("name"),
                  el.getAttribute("id")
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
              };
              const setValue = (el, value) => {
                el.value = value;
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                el.style.outline = "2px solid #b88722";
                el.style.outlineOffset = "2px";
              };
              const checkedSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "checked")?.set;
              const setChecked = (el) => {
                if (checkedSetter) checkedSetter.call(el, true);
                else el.checked = true;
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                el.style.outline = "2px solid #b88722";
                el.style.outlineOffset = "2px";
              };
              const clean = (value) => String(value ?? "").toLowerCase().replace(/[_-]+/g, " ").replace(/\\s+/g, " ").trim();
              const roleFor = (label) => {
                const value = clean(label);
                if (/race|ethnicity|ethnic origin/.test(value)) return "eeo_race";
                if (/gender|sex\\b/.test(value)) return "eeo_gender";
                if (/veteran|armed forces|military status/.test(value)) return "eeo_veteran_status";
                if (/disability|disabled/.test(value)) return "eeo_disability_status";
                return "";
              };
              const matchesAnswer = (role, optionText) => {
                const expected = clean(answers[role]);
                const option = clean(optionText);
                if (!expected || /prefer not|decline|do not wish|don't wish|rather not/.test(option)) return false;
                if (role === "eeo_race" && /white|caucasian/.test(expected)) return /\\bwhite\\b|caucasian/.test(option);
                if (role === "eeo_gender" && /\\bmale\\b|\\bman\\b/.test(expected) && !/female|woman/.test(expected)) {
                  return (/\\bmale\\b|\\bman\\b/.test(option)) && !/female|woman/.test(option);
                }
                if (role === "eeo_veteran_status" && /\\bno\\b|not a veteran|not veteran|non veteran/.test(expected)) {
                  return /not a protected veteran|not a veteran|not veteran|non veteran|\\bno\\b|i am not/.test(option);
                }
                if (role === "eeo_disability_status" && /\\bno\\b|no disability|do not have|don't have|not disabled/.test(expected)) {
                  return /\\bno\\b|do not have|don't have|not disabled|no disability/.test(option);
                }
                return option.includes(expected) || expected.includes(option);
              };
              const legalAllowed = answers.legal_consent_application_processing === true || answers.legal_consent_privacy === true;
              const narrowLegal = /privacy notice|privacy policy|data processing|process(?:ing)? (?:my |the )?application|process.*personal data|gdpr|data retention|store.*application|consent.*data|agree.*privacy|acknowledge.*privacy/;
              const broadLegal = /background|criminal|credit|drug|reference check|arbitration|terms of use|terms and conditions|create account|marketing|newsletter|sms|text message|promotional|screening report|consumer report/;
              const actions = [];
              const record = (label, answer, category, source) => actions.push({
                field_label: String(label || "").slice(0, 180),
                proposed_answer: String(answer),
                category,
                confidence: 1,
                source_facts: [source],
                applied: true,
                reason: "explicit application_answers value"
              });

              for (const select of document.querySelectorAll("select")) {
                if (!visible(select) || select.disabled || select.value) continue;
                const label = textFor(select);
                const role = roleFor(label);
                if (!role || !answers[role]) continue;
                const option = Array.from(select.options || []).find((candidate) => matchesAnswer(role, `${candidate.text || ""} ${candidate.value || ""}`));
                if (!option) continue;
                setValue(select, option.value);
                record(`${label}: ${option.text || option.value}`, answers[role], "controlled_eeo", `application_answers.${role}`);
              }

              const radioGroups = new Map();
              for (const input of document.querySelectorAll('input[type="radio"]')) {
                const name = input.name || input.id || String(radioGroups.size);
                if (!radioGroups.has(name)) radioGroups.set(name, []);
                radioGroups.get(name).push(input);
              }
              for (const inputs of radioGroups.values()) {
                if (inputs.some((input) => input.checked)) continue;
                const groupLabel = inputs.map(textFor).join(" ");
                const role = roleFor(groupLabel);
                if (!role || !answers[role]) continue;
                const match = inputs.find((input) => visible(input) && !input.disabled && matchesAnswer(role, choiceText(input)));
                if (!match) continue;
                setChecked(match);
                record(choiceText(match), answers[role], "controlled_eeo", `application_answers.${role}`);
              }

              for (const input of document.querySelectorAll('input[type="checkbox"]')) {
                if (!visible(input) || input.disabled || input.checked) continue;
                const label = textFor(input);
                const normalized = clean(label);
                const role = roleFor(label);
                if (role && answers[role] && matchesAnswer(role, choiceText(input))) {
                  setChecked(input);
                  record(label, answers[role], "controlled_eeo", `application_answers.${role}`);
                  continue;
                }
                if (legalAllowed && narrowLegal.test(normalized) && !broadLegal.test(normalized)) {
                  setChecked(input);
                  record(label, "true", "controlled_legal", "application_answers.legal_consent_application_processing");
                }
              }
              return actions;
            }
            """,
            {"answers": controlled},
        )
    )
    return {"filled": len(actions), "answers": normalize_audit_answers(actions)}


async def run_llm_screening_autofill(
    page: Any,
    store: Store,
    job: dict[str, Any],
    fields: dict[str, Any],
    answers: dict[str, Any],
) -> dict[str, Any]:
    workflow = store.get_json_setting("workflow", {})
    if not workflow.get("llm_autofill_screening_questions", True):
        return {"filled": 0, "answers": []}
    key = openai_api_key()
    if not key:
        return {"filled": 0, "answers": []}

    max_fields = int(workflow.get("llm_autofill_max_fields", 12) or 12)
    candidates = await collect_llm_candidate_fields(page, max_fields=max_fields)
    if not candidates:
        return {"filled": 0, "answers": []}

    model = str(workflow.get("llm_model") or DEFAULT_MODEL)
    timeout = int(workflow.get("llm_timeout_seconds", 45) or 45)
    context = build_llm_screening_context(store, job, fields, answers, candidates)
    try:
        response = call_openai_json(
            model=model,
            key=key,
            system_prompt=LLM_SCREENING_SYSTEM_PROMPT,
            context=context,
            timeout=timeout,
            max_output_tokens=2200,
        )
    except OpenAIRequestUnavailable as exc:
        return {
            "filled": 0,
            "answers": [
                {
                    "field_label": "LLM screening autofill",
                    "proposed_answer": "",
                    "category": "unavailable",
                    "confidence": 0,
                    "source_facts": [],
                    "applied": False,
                    "reason": str(exc).splitlines()[0][:220],
                }
            ],
        }

    proposed = normalize_llm_screening_answers(response, candidates)
    min_confidence = float(workflow.get("llm_autofill_min_confidence", 0.65) or 0.65)
    filled, audited = await apply_llm_text_answers(page, proposed, candidates, answers, min_confidence)
    return {"filled": filled, "answers": audited}


async def collect_llm_candidate_fields(page: Any, max_fields: int) -> list[dict[str, Any]]:
    return list(
        await page.evaluate(
            """
            ({ maxFields }) => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder"),
                  el.getAttribute("name"),
                  el.getAttribute("id"),
                  el.getAttribute("autocomplete")
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                const legend = el.closest("fieldset")?.querySelector("legend");
                if (legend) parts.push(legend.innerText);
                const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                if (wrapper) parts.push((wrapper.innerText || "").slice(0, 260));
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
              };
              const blocked = /password|captcha|security|otp|verification|one-time|2fa|mfa|login|sign in|account password|ssn|social security|tax id|bank account|routing number/i;
              const fields = [];
              let index = 0;
              for (const el of document.querySelectorAll("input, textarea")) {
                const tag = el.tagName.toLowerCase();
                const type = (el.getAttribute("type") || tag).toLowerCase();
                if (["hidden", "password", "submit", "button", "checkbox", "radio", "file"].includes(type)) continue;
                if (!visible(el) || el.disabled || el.readOnly || el.value) continue;
                const label = textFor(el);
                if (blocked.test(label)) continue;
                const fieldId = `llm-field-${Date.now()}-${index}`;
                el.setAttribute("data-job-cockpit-llm-id", fieldId);
                fields.push({
                  field_id: fieldId,
                  label: label.slice(0, 220),
                  tag,
                  type,
                  required: Boolean(el.required || el.getAttribute("aria-required") === "true"),
                  max_length: Number(el.getAttribute("maxlength") || 0),
                  placeholder: String(el.getAttribute("placeholder") || "").slice(0, 160)
                });
                index += 1;
                if (fields.length >= maxFields) break;
              }
              return fields;
            }
            """,
            {"maxFields": max(1, min(max_fields, 25))},
        )
    )


def build_llm_screening_context(
    store: Store,
    job: dict[str, Any],
    fields: dict[str, Any],
    answers: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    master = store.get_json_setting("resume_master", {}) or {}
    reference_cache = store.get_json_setting("reference_resume_text_cache", {}) or {}
    explicit_answers = {
        key: value
        for key, value in answers.items()
        if key in SAFE_FIELD_KEYS and value not in ("", None, [], {})
    }
    return {
        "rules_version": "2026-06-28",
        "candidate": {
            "master_resume": master,
            "known_fields": {key: value for key, value in fields.items() if key in SAFE_FIELD_KEYS and value not in ("", None, [], {})},
            "answer_profile": explicit_answers,
            "reference_resume_pdf_text": str(reference_cache.get("text", ""))[:10_000],
        },
        "job": {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "remote": job.get("remote", ""),
            "url": job.get("url", ""),
            "source": job.get("source", ""),
            "requirements": job.get("requirements", []),
            "description": str(job.get("description", ""))[:7000],
        },
        "visible_empty_fields": candidates,
    }


def normalize_llm_screening_answers(response: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate_by_id = {str(item.get("field_id", "")): item for item in candidates}
    raw_answers = response.get("answers", [])
    if not isinstance(raw_answers, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_answers[: len(candidates)]:
        if not isinstance(item, dict):
            continue
        field_id = str(item.get("field_id", "")).strip()
        candidate = candidate_by_id.get(field_id)
        if not candidate:
            continue
        source_facts = item.get("source_facts", [])
        if not isinstance(source_facts, list):
            source_facts = [str(source_facts)]
        try:
            confidence = float(item.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        normalized.append(
            {
                "field_id": field_id,
                "field_label": str(candidate.get("label", ""))[:180],
                "proposed_answer": re.sub(r"\s+", " ", str(item.get("answer", ""))).strip(),
                "category": str(item.get("category", "unknown")).strip() or "unknown",
                "confidence": max(0.0, min(confidence, 1.0)),
                "source_facts": [str(fact).strip()[:180] for fact in source_facts if str(fact).strip()][:6],
                "tag": str(candidate.get("tag", "")),
                "max_length": int(candidate.get("max_length") or 0),
            }
        )
    return normalized


async def apply_llm_text_answers(
    page: Any,
    proposed: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    explicit_answers: dict[str, Any],
    min_confidence: float,
) -> tuple[int, list[dict[str, Any]]]:
    candidate_by_id = {str(item.get("field_id", "")): item for item in candidates}
    explicit_keys = {
        key
        for key, value in explicit_answers.items()
        if key in SAFE_FIELD_KEYS and value not in ("", None, [], {})
    }
    fill_items: list[dict[str, str]] = []
    audit: list[dict[str, Any]] = []
    for item in proposed:
        reason = ""
        label = str(item.get("field_label", ""))
        category = str(item.get("category", "unknown"))
        answer = str(item.get("proposed_answer", "")).strip()
        confidence = float(item.get("confidence", 0) or 0)
        if category not in LLM_ALLOWED_TEXT_CATEGORIES:
            reason = f"blocked category: {category}"
        elif confidence < min_confidence:
            reason = f"low confidence: {confidence:.2f}"
        elif not answer:
            reason = "empty answer"
        elif SENSITIVE_FACTUAL_LABEL_RE.search(label) and not explicit_keys:
            reason = "sensitive factual field requires explicit application_answers value"
        elif SENSITIVE_FACTUAL_LABEL_RE.search(label) and not any("application_answers" in fact for fact in item.get("source_facts", [])):
            reason = "sensitive factual answer missing explicit source"
        if not reason:
            candidate = candidate_by_id.get(str(item.get("field_id", "")), {})
            answer = clamp_llm_answer(answer, candidate)
            fill_items.append({"field_id": str(item.get("field_id", "")), "answer": answer})
            item["proposed_answer"] = answer
            item["applied"] = True
            item["reason"] = "filled by LLM screening assistant"
        else:
            item["applied"] = False
            item["reason"] = reason
        audit.append(
            {
                "field_label": label,
                "proposed_answer": item.get("proposed_answer", ""),
                "category": category,
                "confidence": confidence,
                "source_facts": item.get("source_facts", []),
                "applied": item.get("applied", False),
                "reason": item.get("reason", ""),
            }
        )
    if not fill_items:
        return 0, normalize_audit_answers(audit)
    filled = int(
        await page.evaluate(
            """
            ({ items }) => {
              const setValue = (el, value) => {
                const prototype = Object.getPrototypeOf(el);
                const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
                if (descriptor && descriptor.set) {
                  descriptor.set.call(el, value);
                } else {
                  el.value = value;
                }
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                el.style.outline = "2px solid #2f9e44";
                el.style.outlineOffset = "2px";
              };
              let filled = 0;
              for (const item of items) {
                const el = document.querySelector(`[data-job-cockpit-llm-id="${CSS.escape(item.field_id)}"]`);
                if (!el || el.disabled || el.readOnly || el.value) continue;
                setValue(el, item.answer);
                filled += 1;
              }
              return filled;
            }
            """,
            {"items": fill_items},
        )
    )
    return filled, normalize_audit_answers(audit)


def clamp_llm_answer(answer: str, candidate: dict[str, Any]) -> str:
    limit = int(candidate.get("max_length") or 0)
    if not limit:
        limit = 700 if str(candidate.get("tag", "")).lower() == "textarea" else 180
    limit = max(20, min(limit, 900))
    if len(answer) <= limit:
        return answer
    return answer[: limit - 1].rstrip(" ,.;") + "."


def normalize_audit_answers(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in values:
        source_facts = item.get("source_facts", [])
        if not isinstance(source_facts, list):
            source_facts = [source_facts]
        normalized.append(
            {
                "field_label": str(item.get("field_label", ""))[:180],
                "proposed_answer": str(item.get("proposed_answer", ""))[:900],
                "category": str(item.get("category", ""))[:80],
                "confidence": float(item.get("confidence", 0) or 0),
                "source_facts": [str(fact)[:180] for fact in source_facts[:8]],
                "applied": bool(item.get("applied", False)),
                "reason": str(item.get("reason", ""))[:220],
            }
        )
    return normalized


def coerce_bool(value: Any) -> bool | None:
    if value is True or value is False:
        return value
    clean = str(value or "").strip().lower()
    if clean in {"yes", "true", "1", "y", "agree", "accepted"}:
        return True
    if clean in {"no", "false", "0", "n"}:
        return False
    return None


async def attach_resume(page: Any, resume_path: str) -> int:
    resume = Path(resume_path).expanduser()
    if not resume.exists():
        print(f"Resume file not found: {resume}")
        return 0
    file_inputs = page.locator('input[type="file"]')
    total = await file_inputs.count()
    count = 0
    for index in range(total):
        file_input = file_inputs.nth(index)
        try:
            label = await file_input.evaluate(
                """
                (el) => {
                  const parts = [el.getAttribute("aria-label"), el.getAttribute("name"), el.getAttribute("id")];
                  if (el.id) {
                    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (label) parts.push(label.innerText);
                  }
                  const parentLabel = el.closest("label");
                  if (parentLabel) parts.push(parentLabel.innerText);
                  const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                  if (wrapper) parts.push((wrapper.innerText || "").slice(0, 160));
                  return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").toLowerCase();
                }
                """
            )
            looks_like_resume = bool(re.search(r"\b(resume|cv|curriculum|upload)\b", str(label)))
            looks_like_cover = bool(re.search(r"cover\s*letter|motivation", str(label)))
            if total > 1 and (looks_like_cover or not looks_like_resume):
                await mark_manual(file_input)
                continue
            await file_input.set_input_files(str(resume), timeout=2_500)
            await mark_success(file_input)
            count += 1
        except Exception:  # noqa: BLE001
            continue
    return count


async def mark_success(locator: Any) -> None:
    await locator.evaluate("(el) => { el.style.outline = '2px solid #2f9e44'; el.style.outlineOffset = '2px'; }")


async def mark_manual(locator: Any) -> None:
    await locator.evaluate("(el) => { el.style.outline = '2px solid #f08c00'; el.style.outlineOffset = '2px'; }")


async def highlight_manual_fields(page: Any) -> list[dict[str, Any]]:
    return list(
        await page.evaluate(
            """
            () => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder"),
                  el.getAttribute("name"),
                  el.getAttribute("id"),
                  el.getAttribute("autocomplete")
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                if (wrapper) parts.push((wrapper.innerText || "").slice(0, 220));
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
              };
              const reasonsFor = (label, required, type, empty) => {
                const clean = label.toLowerCase();
                const reasons = [];
                if (/password|captcha|security|otp|verification|one-time|2fa|mfa|login|sign in/.test(clean)) reasons.push("security/login");
                if (/race|ethnicity|gender|sexual orientation|veteran|disability|pronoun|eeo|equal employment/.test(clean)) reasons.push("demographic/EEO");
                if (/privacy|terms|consent|gdpr|agreement|agree|acknowledge/.test(clean)) reasons.push("consent/privacy");
                if (["checkbox", "radio"].includes(type)) reasons.push("choice needs review");
                if (required && empty) reasons.push("required empty");
                return reasons.length ? reasons : ["unknown field"];
              };
              const manual = [];
              for (const el of document.querySelectorAll("input, textarea, select")) {
                const type = (el.getAttribute("type") || el.tagName || "").toLowerCase();
                if (["hidden", "submit", "button"].includes(type)) continue;
                const required = el.required || el.getAttribute("aria-required") === "true";
                const radioGroupChecked = type === "radio" && el.name
                  ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)).some((input) => input.checked)
                  : false;
                const checkboxOrRadio = ["checkbox", "radio"].includes(type);
                const empty = type === "radio" ? !radioGroupChecked : type === "checkbox" ? !el.checked : !el.value;
                const label = textFor(el);
                const sensitive = /password|captcha|security|otp|verification|one-time|2fa|mfa|login|sign in/i.test(label);
                const special = /race|ethnicity|gender|sexual orientation|veteran|disability|pronoun|eeo|equal employment|privacy|terms|consent|gdpr|agreement|agree|acknowledge/i.test(label);
                if (visible(el) && empty && (required || sensitive || special || checkboxOrRadio)) {
                  el.style.outline = "2px solid #f08c00";
                  el.style.outlineOffset = "2px";
                  manual.push({
                    label: label.slice(0, 180),
                    type,
                    required,
                    reason: reasonsFor(label, required, type, empty).join(", ")
                  });
                }
              }
              return manual;
            }
            """
        )
    )


async def highlight_submit_buttons(page: Any) -> None:
    await page.evaluate(
        """
        () => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
          };
          for (const el of document.querySelectorAll('button, input[type="submit"], [role="button"]')) {
            const text = `${el.innerText || ""} ${el.value || ""} ${el.getAttribute("aria-label") || ""}`.toLowerCase();
            if (/submit|send application|apply|continue|next|review/.test(text) && visible(el)) {
              el.style.outline = "2px solid #d6336c";
              el.style.outlineOffset = "2px";
            }
          }
        }
        """
    )


async def submit_if_safe(page: Any) -> dict[str, Any]:
    readiness = await evaluate_submit_readiness(page)
    if not readiness["ok"]:
        return {
            "submitted": False,
            "message": "skipped - " + "; ".join(readiness["reasons"][:6]),
            "reasons": readiness["reasons"],
            "readiness": readiness,
        }
    clicked = await click_final_submit(page)
    if not clicked:
        return {
            "submitted": False,
            "message": "skipped - final submit button disappeared",
            "reasons": ["no submit"],
            "readiness": readiness,
        }
    await settle(page)
    success = await detect_submission_success(page)
    return {
        "submitted": True,
        "confirmed": success,
        "message": "submitted" + (" and confirmation detected" if success else "; confirmation not detected"),
        "reasons": [],
        "readiness": readiness,
    }


async def evaluate_submit_readiness(page: Any) -> dict[str, Any]:
    if await has_captcha(page):
        return {"ok": False, "reasons": ["CAPTCHA/security challenge detected"]}
    result = await page.evaluate(
        """
        () => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
          };
          const textFor = (el) => {
            const parts = [
              el.getAttribute("aria-label"),
              el.getAttribute("placeholder"),
              el.getAttribute("name"),
              el.getAttribute("id"),
              el.getAttribute("autocomplete")
            ];
            if (el.id) {
              const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
              if (label) parts.push(label.innerText);
            }
            const parentLabel = el.closest("label");
            if (parentLabel) parts.push(parentLabel.innerText);
            const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
            if (wrapper) parts.push((wrapper.innerText || "").slice(0, 220));
            return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").toLowerCase();
          };
          const reasons = [];
          const sensitive = /password|captcha|security|otp|verification|one-time|2fa|mfa|login|sign in/;
          const demographic = /race|ethnicity|gender|sexual orientation|veteran|disability|pronoun|eeo|equal employment/;
          const consent = /privacy|terms|consent|gdpr|agreement|agree|acknowledge/;
          const narrowConsent = /privacy notice|privacy policy|data processing|process(?:ing)? (?:my |the )?application|process.*personal data|gdpr|data retention|store.*application|consent.*data|agree.*privacy|acknowledge.*privacy/;
          const broadConsent = /background|criminal|credit|drug|reference check|arbitration|terms of use|terms and conditions|create account|marketing|newsletter|sms|text message|promotional|screening report|consumer report/;
          for (const el of document.querySelectorAll("input, textarea, select")) {
            if (!visible(el) || el.disabled) continue;
            const type = (el.getAttribute("type") || "").toLowerCase();
            if (["hidden", "submit", "button"].includes(type)) continue;
            const label = textFor(el);
            const required = el.required || el.getAttribute("aria-required") === "true";
            const radioGroupChecked = type === "radio" && el.name
              ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)).some((input) => input.checked)
              : false;
            const empty = type === "radio" ? !radioGroupChecked : type === "checkbox" ? !el.checked : !el.value;
            if (sensitive.test(label)) reasons.push("security/login field needs human");
            if (demographic.test(label) && empty) reasons.push("demographic/EEO field needs human");
            if (consent.test(label) && broadConsent.test(label)) reasons.push("broad legal consent needs human");
            if (consent.test(label) && !narrowConsent.test(label) && !broadConsent.test(label) && (required || ["checkbox", "radio"].includes(type))) {
              reasons.push("ambiguous consent/privacy field needs human");
            }
            if (consent.test(label) && narrowConsent.test(label) && empty && required) reasons.push("application-processing consent field empty");
            if (required && empty) reasons.push(`required field empty: ${label.slice(0, 70) || type || el.tagName.toLowerCase()}`);
          }
          const submitButtons = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"]')).filter((el) => {
            if (!visible(el) || el.disabled) return false;
            const text = `${el.innerText || ""} ${el.value || ""} ${el.getAttribute("aria-label") || ""}`.toLowerCase();
            if (/next|continue|review|preview|save|create account|sign in|log in/.test(text)) return false;
            return /submit application|send application|submit|send/.test(text);
          });
          if (submitButtons.length !== 1) reasons.push(`final submit candidates: ${submitButtons.length}`);
          return { ok: reasons.length === 0, reasons };
        }
        """
    )
    reasons = list(dict.fromkeys(str(reason) for reason in result.get("reasons", []) if str(reason).strip()))
    return {"ok": bool(result.get("ok")) and not reasons, "reasons": reasons}


async def click_final_submit(page: Any) -> bool:
    return bool(
        await page.evaluate(
            """
            () => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"]')).filter((el) => {
                if (!visible(el) || el.disabled) return false;
                const text = `${el.innerText || ""} ${el.value || ""} ${el.getAttribute("aria-label") || ""}`.toLowerCase();
                if (/next|continue|review|preview|save|create account|sign in|log in/.test(text)) return false;
                return /submit application|send application|submit|send/.test(text);
              });
              if (buttons.length !== 1) return false;
              buttons[0].click();
              return true;
            }
            """
        )
    )


async def detect_submission_success(page: Any) -> bool:
    try:
        text = await page.locator("body").inner_text(timeout=6_000)
    except Exception:  # noqa: BLE001
        text = ""
    return bool(
        re.search(
            r"thank you|submitted|application received|received your application|successfully submitted|application complete",
            text,
            re.I,
        )
    )


async def collect_form_snapshot(page: Any) -> list[dict[str, Any]]:
    return list(
        await page.evaluate(
            """
            () => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const textFor = (el) => {
                const parts = [
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder"),
                  el.getAttribute("name"),
                  el.getAttribute("id"),
                  el.getAttribute("autocomplete")
                ];
                if (el.id) {
                  const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                  if (label) parts.push(label.innerText);
                }
                const parentLabel = el.closest("label");
                if (parentLabel) parts.push(parentLabel.innerText);
                const wrapper = el.closest("[data-qa], [data-testid], fieldset, .field, .form-group, div");
                if (wrapper) parts.push((wrapper.innerText || "").slice(0, 180));
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
              };
              return Array.from(document.querySelectorAll("input, textarea, select")).filter(visible).slice(0, 120).map((el) => {
                const type = (el.getAttribute("type") || el.tagName || "").toLowerCase();
                const radioGroupChecked = type === "radio" && el.name
                  ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)).some((input) => input.checked)
                  : false;
                const checkboxOrRadio = ["checkbox", "radio"].includes(type);
                return {
                  label: textFor(el).slice(0, 180),
                  tag: el.tagName.toLowerCase(),
                  type,
                  required: Boolean(el.required || el.getAttribute("aria-required") === "true"),
                  has_value: type === "radio" ? Boolean(radioGroupChecked) : checkboxOrRadio ? Boolean(el.checked) : Boolean(el.value),
                  disabled: Boolean(el.disabled),
                  read_only: Boolean(el.readOnly)
                };
              });
            }
            """
        )
    )


async def write_audit(
    page: Any,
    args: argparse.Namespace,
    job: dict[str, Any],
    fields: dict[str, Any],
    metrics: dict[str, Any],
    submit_result: dict[str, Any],
    manual_fields: list[dict[str, Any]],
    llm_field_answers: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    job_part = f"job_{args.job_id}" if args.job_id else "manual"
    slug = safe_slug(f"{job.get('company', '')}_{job.get('title', '')}")[:70] or "application"
    json_path = AUDIT_DIR / f"{stamp}_{job_part}_{slug}.json"
    screenshot_path = AUDIT_DIR / f"{stamp}_{job_part}_{slug}.png"
    screenshot = ""
    try:
        await page.screenshot(path=str(screenshot_path), full_page=True, timeout=6_000)
        screenshot = str(screenshot_path)
    except Exception as exc:  # noqa: BLE001
        screenshot = f"not captured: {str(exc).splitlines()[0]}"

    readiness = submit_result.get("readiness")
    if not readiness:
        try:
            readiness = await evaluate_submit_readiness(page)
        except Exception as exc:  # noqa: BLE001
            readiness = {"ok": False, "reasons": [f"readiness check failed: {str(exc).splitlines()[0]}"]}

    snapshot: list[dict[str, Any]]
    try:
        snapshot = await collect_form_snapshot(page)
    except Exception as exc:  # noqa: BLE001
        snapshot = [{"label": f"snapshot failed: {str(exc).splitlines()[0]}", "type": "error"}]

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "job_id": args.job_id,
        "job": {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "source_url": args.url,
            "final_url": getattr(page, "url", ""),
        },
        "mode": {
            "auto_open_apply": bool(args.auto_open_apply),
            "auto_submit_safe": bool(args.auto_submit_safe),
            "headless": bool(args.headless),
        },
        "metrics": metrics,
        "submit": submit_result,
        "readiness": readiness,
        "manual_fields": manual_fields[:80],
        "llm_field_answers": (llm_field_answers or [])[:80],
        "form_snapshot": snapshot,
        "used_field_keys": sorted(
            key for key, value in fields.items() if key in SAFE_FIELD_KEYS and value not in ("", None, [], {})
        ),
        "resume_path": str(fields.get("resume_path", "")),
        "screenshot": screenshot,
        "rules": [
            "CAPTCHA, login, MFA and anti-bot challenges require human handoff.",
            "EEO/demographic and narrow application-processing consent fields may be answered only from explicit application_answers values.",
            "Broad legal acknowledgements, background checks, account terms, marketing consent and unknown required fields require human handoff.",
            "Work authorization and sponsorship yes/no answers require explicit application_answers values.",
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "path": str(json_path),
        "url": f"/api/automation-runs/{json_path.name}",
        "screenshot": str(screenshot_path) if screenshot == str(screenshot_path) else "",
    }


def safe_slug(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._-")
    return clean or "application"


def mark_job_applied(store: Store, job_id: int, submit_result: dict[str, Any]) -> None:
    status = "applied"
    note = "safe auto-submit clicked"
    if submit_result.get("confirmed"):
        note = "safe auto-submit confirmed by page text"
    store.update_job(job_id, {"status": status})
    store.log("info", f"Marked job #{job_id} applied after auto-submit", {"job_id": job_id, "note": note})


async def wait_for_human(context: Any, args: argparse.Namespace) -> None:
    if args.no_wait or args.wait_mode == "none":
        return
    if args.wait_mode == "browser":
        print("Browser is open. Close the browser window when you are done reviewing/submitting.")
        while True:
            pages = [page for page in context.pages if not page.is_closed()]
            if not pages:
                return
            await asyncio.sleep(1)
    print("Press Enter here when you are done reviewing the browser.")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, input)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open and safely fill a job application form.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--db", default=str(ROOT / "cockpit.db"))
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--profile")
    parser.add_argument("--answers", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--company", default="")
    parser.add_argument("--cover-letter", default="")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--wait-mode", choices=["enter", "browser", "none"], default="enter")
    parser.add_argument("--user-data-dir", default="")
    parser.add_argument("--auto-open-apply", action="store_true")
    parser.add_argument("--auto-submit-safe", action="store_true")
    parser.add_argument("--mark-applied-on-submit", action="store_true")
    parser.add_argument("--slow-mo", type=int, default=0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(fill_application(args)))


if __name__ == "__main__":
    main()
