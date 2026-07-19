from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_field_payload(profile: dict[str, Any], job: dict[str, Any]) -> dict[str, str]:
    first_name = str(profile.get("first_name", ""))
    last_name = str(profile.get("last_name", ""))
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    cover_letter = str(job.get("cover_letter") or "")
    resume_path = str(profile.get("resume_path", ""))
    if job.get("resume_attachment"):
        resume_path = str(job["resume_attachment"])
    if job.get("resume_variant"):
        resume_path = str((PROJECT_ROOT / str(job["resume_variant"])).resolve())
    return {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "email": str(profile.get("email", "")),
        "phone": str(profile.get("phone", "")),
        "location": str(profile.get("location", "")),
        "linkedin_url": str(profile.get("linkedin_url", "")),
        "github_url": str(profile.get("github_url", "")),
        "portfolio_url": str(profile.get("portfolio_url", "")),
        "work_authorization": str(profile.get("work_authorization", "")),
        "salary_expectation": str(profile.get("salary_expectation", "")),
        "notice_period": str(profile.get("notice_period", "")),
        "cover_letter": cover_letter,
        "job_title": str(job.get("title", "")),
        "company": str(job.get("company", "")),
        "resume_path": resume_path,
    }


def build_fill_plan(profile: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    fields = build_field_payload(profile, job)
    return {
        "mode": "human_in_the_loop",
        "fields": fields,
        "blocked_actions": [
            "CAPTCHA solving",
            "automatic final submit",
            "password entry",
            "creating accounts without review",
        ],
        "pause_conditions": [
            "CAPTCHA detected",
            "missing required unknown field",
            "file upload requires OS picker",
            "submit button visible",
        ],
    }


def build_filler_script(profile: dict[str, Any], job: dict[str, Any]) -> str:
    payload = json.dumps(build_field_payload(profile, job), ensure_ascii=False)
    return FILLER_TEMPLATE.replace("__JOB_COCKPIT_PAYLOAD__", payload)


FILLER_TEMPLATE = r"""(() => {
  const data = __JOB_COCKPIT_PAYLOAD__;
  const report = [];
  const captcha = document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], .g-recaptcha, .h-captcha, [name*="captcha" i], [id*="captcha" i]');
  if (captcha) {
    captcha.scrollIntoView({block: "center", behavior: "smooth"});
    alert("Job Cockpit paused: CAPTCHA/security challenge detected. Please solve it manually, then run the filler again if needed.");
    return;
  }

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
    const wrapper = el.closest("[class], fieldset, div");
    if (wrapper) parts.push(wrapper.innerText.slice(0, 160));
    return parts.filter(Boolean).join(" ").toLowerCase();
  };

  const rules = [
    [/first.*name|given.*name|forename/, data.first_name],
    [/last.*name|family.*name|surname/, data.last_name],
    [/full.*name|legal.*name|your.*name|name/, data.full_name],
    [/e-?mail|email/, data.email],
    [/phone|mobile|telephone/, data.phone],
    [/linkedin|linked in/, data.linkedin_url],
    [/github/, data.github_url],
    [/portfolio|website|personal site/, data.portfolio_url],
    [/city|location|address/, data.location],
    [/work authorization|authorized|visa|sponsorship/, data.work_authorization],
    [/salary|compensation|expected pay/, data.salary_expectation],
    [/notice period|start date|available/, data.notice_period],
    [/cover letter|motivation|why are you interested|message to hiring/, data.cover_letter]
  ];

  const fill = (el, value) => {
    if (!value || !visible(el) || el.disabled || el.readOnly) return false;
    const old = el.value;
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event("input", {bubbles: true}));
    el.dispatchEvent(new Event("change", {bubbles: true}));
    if (old !== el.value) {
      el.style.outline = "2px solid #2f9e44";
      el.style.outlineOffset = "2px";
      return true;
    }
    return false;
  };

  for (const el of document.querySelectorAll("input, textarea")) {
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (["hidden", "password", "submit", "button", "checkbox", "radio"].includes(type)) continue;
    if (type === "file") {
      el.style.outline = "2px solid #f08c00";
      report.push("Resume upload field found; attach the file manually from your profile path.");
      continue;
    }
    const label = textFor(el);
    for (const [pattern, value] of rules) {
      if (pattern.test(label) && fill(el, value)) {
        report.push(`Filled ${label.slice(0, 45)}`);
        break;
      }
    }
  }

  for (const el of document.querySelectorAll("select")) {
    const label = textFor(el);
    if (/work authorization|authorized|visa|sponsorship/.test(label) && data.work_authorization) {
      const option = Array.from(el.options).find((opt) => opt.text.toLowerCase().includes(data.work_authorization.toLowerCase()));
      if (option) {
        el.value = option.value;
        el.dispatchEvent(new Event("change", {bubbles: true}));
        el.style.outline = "2px solid #2f9e44";
        report.push(`Selected ${label.slice(0, 45)}`);
      }
    }
  }

  const submitLike = Array.from(document.querySelectorAll('button, input[type="submit"]')).filter((el) => {
    const text = `${el.innerText || ""} ${el.value || ""} ${el.getAttribute("aria-label") || ""}`.toLowerCase();
    return /submit|send application|apply|continue|next/.test(text) && visible(el);
  });
  submitLike.forEach((el) => {
    el.style.outline = "2px solid #d6336c";
    el.style.outlineOffset = "2px";
  });

  alert(`Job Cockpit filled ${report.length} fields. Review everything manually. Highlighted pink buttons were not clicked.`);
})();"""
