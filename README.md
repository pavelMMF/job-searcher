# Job Cockpit

Local human-in-the-loop cockpit for Data Analyst and Data Scientist applications. It collects remote job postings, scores them for fit, and generates a truthfully tailored PDF resume and cover letter per vacancy — reordering, rewriting, and keyword-matching your **real** experience toward each job without inventing employers, dates, tools, or metrics.

## Setup

This repository ships **code and sample configs only** — no personal data and no API keys. On first use, create your own config files from the samples in `job_cockpit/config/`:

```powershell
Copy-Item job_cockpit\config\master_resume.sample.json job_cockpit\config\master_resume.json
Copy-Item job_cockpit\config\openai.env.sample         job_cockpit\config\openai.env
Copy-Item job_cockpit\config\profile.sample.json       job_cockpit\config\profile.json
Copy-Item job_cockpit\config\sources.sample.json       job_cockpit\config\sources.json
```

Then:

1. Fill `master_resume.json` with your real, truthful experience (this is the single source of facts the LLM is allowed to use).
2. Put your OpenAI API key in `job_cockpit\config\openai.env` as `OPENAI_API_KEY=sk-...`. This file is git-ignored and must never be committed.
3. Install dependencies: `python -m pip install -r job_cockpit\requirements.txt`.

Your personal files (`master_resume.json`, `openai.env`, generated `output/`, working notes) are all listed in `.gitignore` and stay local.

**Candidate name is not hard-coded.** The published code carries no personal name — the candidate name used in prompts, generated resumes, and output filenames is read at runtime from the `name` field in your local (git-ignored) `master_resume.json`. Fill it with your own name; nothing in the repository needs to be edited.

## Run

```powershell
.\start_cockpit.ps1
```

Open:

```text
http://127.0.0.1:8765
```

For phone access on the same Wi-Fi, run with `--host 0.0.0.0` and open `http://YOUR_PC_LAN_IP:8765` from the phone.

```powershell
.\start_cockpit.ps1 -HostName 0.0.0.0 -Port 8765
```

Run in the background:

```powershell
.\start_cockpit_background.ps1
```

Stop the background server:

```powershell
.\stop_cockpit.ps1
```

## What It Does

- Stores your profile, resume path, target roles, skills, and job preferences.
- Collects manual job descriptions and optional public career-page sources.
- Searches public remote job APIs/RSS such as Remotive, Arbeitnow, Jobicy, Himalayas, RemoteOK, and We Work Remotely.
- Scores jobs for fit.
- Generates application drafts and cover letters.
- Generates a tailored PDF resume for each job from a truthful master resume.
- Auto-ready focuses on Middle+ Data Analytics and Data Science roles; junior, intern, working-student, and entry-level roles are demoted.
- Produces a safe browser filler script for application pages.
- Opens a visible assisted-apply browser from the dashboard and fills recognized fields.
- Can safe-submit fully recognized forms when `Safe auto-submit` is enabled.
- Tracks statuses: new, ready to apply, applied, skipped.
- Stores interview meetings and exports `.ics` for Google Calendar import.

## Safety

The assistant does not solve CAPTCHA, bypass security checks, or enter passwords. With `Safe auto-submit` enabled, it can click final submit only when there are no unknown required fields, CAPTCHA/security/login prompts, consent checkboxes, or demographic/EEO questions.

Resume tailoring is truth-preserving: it can reorder, emphasize, rewrite, and keyword-match your real experience, but it should not invent employers, dates, tools, metrics, degrees, or work authorization.

## Resume Generator

Your extracted master resume is stored in:

```text
job_cockpit\config\master_resume.json
```

In the UI, open a job card and click `Resume`. The cockpit writes a tailored PDF to:

```text
output\pdf\
```

The generated PDF prioritizes the job's title, requirements, and keywords in the headline, summary, skills, and selected experience bullets.

Resume generation rules are fixed here:

```text
job_cockpit\docs\RESUME_GENERATION_RULES.md
job_cockpit\docs\APPLICATION_TEXT_GENERATION_RULES.md
```

Important contract:

- every generated resume must include all real roles from the master resume, including `Apr 2023 - Mar 2025`;
- each role must keep at least two bullets when source bullets exist;
- tailoring may emphasize and reorder truthful experience, but must not invent employers, dates, tools, metrics, degrees, work authorization, or projects;
- generated PDFs must not contain internal footer/debug text such as `Tailored for ...` or `Generated ...`;
- generated resume and cover-letter text must avoid generic AI-style phrases, placeholders, unsupported buzzwords, and over-polished empty wording;
- visual style should stay clean, human, recruiter-friendly, with the aurora header and golden/brown section headings.

If a job description is too thin to tailor responsibly, the package falls back to your standard reference resume (the PDF path set in `standard_resume_path` inside `master_resume.json`).

## One-Click Package Flow

In the UI, click `Daily Review` to run the full pipeline:

```text
search sources -> dedupe jobs -> score fit -> generate cover letter -> generate tailored PDF -> mark ready_to_apply
```

Click `Package` if jobs are already in the cockpit and you only want to create missing cover letters/resumes for high-score roles.

Configured sources live in the `Sources` tab as JSON. The default enabled sources are:

- Remotive public remote jobs API
- Arbeitnow public job board API
- Jobicy public remote jobs API and Data Science RSS
- Himalayas public remote jobs API
- Manual intake

RemoteOK and We Work Remotely are disabled and blocked by preference.

The default workflow is `remote_only`: it does not target a specific country or region. Region-restricted remote jobs may still appear so you can decide manually whether citizenship, contract type, or payroll setup works.

LinkedIn and company ATS forms are handled as assisted application targets. Click `Apply Next` for one job or `Auto Queue` for a background run over Ready jobs. If `Safe auto-submit` is enabled, clean forms are submitted automatically and marked `Applied`; blocked forms stay Ready for human review.

The assisted browser keeps its local session profile here:

```text
job_cockpit\browser_profiles\applications
```

Log in inside that browser when a site asks. Do not paste passwords, OTPs, recovery codes, or cookies into chat.

For account access setup, see:

```text
job_cockpit\docs\AUTH.md
```

If you run outside the bundled Codex runtime, install core PDF dependencies:

```powershell
python -m pip install -r job_cockpit\requirements.txt
```

## Optional Browser Automation

The project can use local optional dependencies from `job_cockpit\vendor`. To install them manually in a clean copy:

```powershell
python -m pip install --target job_cockpit\vendor -r job_cockpit\requirements-optional.txt
$env:PYTHONPATH=(Resolve-Path job_cockpit\vendor).Path
$env:PLAYWRIGHT_BROWSERS_PATH=(Join-Path (Get-Location).Path 'job_cockpit\ms-playwright')
python -m playwright install chromium
```

Then run a direct helper if needed:

```powershell
$env:PYTHONPATH=(Resolve-Path job_cockpit\vendor).Path
$env:PLAYWRIGHT_BROWSERS_PATH=(Join-Path (Get-Location).Path 'job_cockpit\ms-playwright')
python job_cockpit\automation\fill_application.py --url "https://company.example/apply" --job-id 1
```

The browser opens visibly, attaches the tailored resume when the job has one, fills known fields, highlights submit-like buttons, and waits for your manual review.

## Google Calendar

The built-in path exports meetings as `.ics`:

```powershell
python job_cockpit\automation\google_calendar_sync.py
```

Direct Google Calendar write access should be added only after creating OAuth credentials and installing the optional Google dependencies.
