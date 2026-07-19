# Agent Rule: Resume Generation

When editing or running the resume generator, follow `job_cockpit/docs/RESUME_GENERATION_RULES.md`.
For cover letters, summaries, bullets, LinkedIn notes, and application messages, also follow `job_cockpit/docs/APPLICATION_TEXT_GENERATION_RULES.md`.
For OpenAI-backed generation, also follow `job_cockpit/docs/LLM_APPLICATION_GENERATION_RULES.md`.

Non-negotiable rules:

- Keep resume tailoring truthful: no invented employers, dates, tools, metrics, projects, degrees, or work authorization.
- Every generated resume must include all real experience roles from `job_cockpit/config/master_resume.json`.
- The older role `Apr 2023 - Mar 2025 - Data Analyst, iGaming` must never disappear.
- Each real role should keep at least 2 bullets when source bullets exist.
- Do not add internal footer/debug text such as `Tailored for ...` or `Generated ...`.
- Preserve the aurora header and the clean golden/brown visual style.
- If the job description is too thin, use the standard resume rather than inventing a tailored match.
- Avoid generic AI-like text: no `proven track record`, `results-oriented`, `dynamic`, `innovative`, `cutting-edge`, unsupported `actionable insights`, or placeholder fragments.
- Cover letters must be one paragraph, under 100 words, concrete, and not open with `I am excited to apply`.
- OpenAI API keys must never be written into source code, committed files, frontend JavaScript, activity logs, or docs.
- OpenAI output must pass Python validators before a resume PDF or cover letter is saved.

Before finishing resume-generator changes, test at least one generated payload/PDF for:

- `Apr 2025 - Present`
- `Dec 2025 - Present`
- `Apr 2023 - Mar 2025`
- absence of `Tailored for`
- absence of `Generated 20`
