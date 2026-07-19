# Auto Agent Setup

This document describes the intended job-search automation architecture for Job Cockpit.

## Current Search Flow

`Wide Search` and `Daily Review` run locally from `job_cockpit/core/agents.py`.

The flow is:

1. read enabled sources from the `Sources` settings;
2. read search queries, remote-only rules, blocked domains, seniority targets, and score threshold from `Workflow`;
3. fetch public API/RSS/HTML sources;
4. normalize job fields;
5. deduplicate by URL or role/company/location;
6. score fit against the local profile;
7. generate packages only for safe auto-apply candidates, perfect `100` score jobs, or user-requested jobs;
8. write everything to `job_cockpit/cockpit.db`;
9. show results in the local UI.

Enabled public sources are currently Remotive, Arbeitnow, Jobicy, Himalayas, and Jobicy Data Science RSS. RemoteOK and We Work Remotely are blocked by preference.

## Expanding Search Sources

Prefer structured sources over generic HTML scraping.

For the current strategy, the goal is a broad and diverse list of remote vacancies, not a target-company campaign. Start with aggregators, public APIs, RSS feeds, and remote job boards. ATS board sources are optional add-ons when a broad board exposes jobs through Greenhouse, Lever, or Ashby, or when a company is especially relevant by chance.

Supported source kinds:

- `remotive_api`, `arbeitnow_api`, `jobicy_api`, `himalayas_api`, `rss`, `public_html`;
- `greenhouse_board` for company boards like `https://boards.greenhouse.io/companytoken`;
- `lever_site` for company boards like `https://jobs.lever.co/companysite`;
- `ashby_board` for company boards like `https://jobs.ashbyhq.com/companyorg`.

Examples for the `Sources` tab:

```json
{
  "name": "Example Greenhouse company",
  "kind": "greenhouse_board",
  "enabled": true,
  "url": "https://boards.greenhouse.io/companytoken",
  "company": "Company Name"
}
```

```json
{
  "name": "Example Lever company",
  "kind": "lever_site",
  "enabled": true,
  "url": "https://jobs.lever.co/companysite",
  "company": "Company Name"
}
```

```json
{
  "name": "Example Ashby company",
  "kind": "ashby_board",
  "enabled": true,
  "url": "https://jobs.ashbyhq.com/companyorg",
  "company": "Company Name"
}
```

Do not add a long list of companies just because they use an ATS. A larger source list is useful only when it increases vacancy diversity and the scoring/region filters stay strict.

## Current Apply Flow

`Auto Queue` runs locally through Playwright:

1. select up to `auto_submit_max_per_run` jobs with status `ready_to_apply`;
2. open each job URL with the persistent local browser profile;
3. click an apply link/button when it is safe;
4. fill known profile fields;
5. attach the tailored resume;
6. answer safe technical rating fields, explicit answer-bank choices, and safe LLM screening text questions;
7. write an audit JSON and screenshot to `output/automation_runs`;
8. submit only if exactly one final submit button is found and no blocked fields are present;
9. mark the job `applied` only after a safe submit click;
10. otherwise keep the job ready and log `needs_review` with an `Audit JSON` link in the UI.

Detailed rules live in `job_cockpit/docs/AUTOFILL_RULES.md`.

Safe repeated answers live in `job_cockpit/config/application_answers.json`. Start from `job_cockpit/config/application_answers.sample.json`; leave unknown values empty or `null`.

## Human Handoff

The agent must stop and leave the page for the user when it sees:

- CAPTCHA;
- login/password/MFA/security checkpoint;
- broad consent/privacy/legal checkbox, background check, arbitration, account terms, marketing/newsletter consent;
- demographic/EEO questions without explicit `application_answers.json` values;
- unknown required fields;
- work authorization or sponsorship yes/no without explicit answer-bank values;
- unclear submit intent;
- browser/site navigation failure.

For these cases the correct behavior is: open or prepare the page, fill everything safe, then report `needs_review`.

## Google Setup

Use Google OAuth, never passwords.

Follow `job_cockpit/docs/AUTH.md`:

1. create a Google Cloud OAuth Desktop client;
2. save it as `job_cockpit/config/google_oauth_client.json`;
3. run `job_cockpit/automation/google_oauth_setup.py`;
4. keep `job_cockpit/config/google_token.json` local.

Recommended Google uses:

- Calendar read/write for interviews;
- Gmail read-only to detect recruiter/interview messages;
- Gmail compose for drafts;
- manual send approval for emails.

Google OAuth does not give universal permission to log into random ATS sites. For job sites that offer `Sign in with Google`, the browser profile can remember your session after you log in manually.

## OpenAI API Setup

Job Cockpit can optionally call OpenAI for application package generation and safe screening-question autofill.

Rules live in `job_cockpit/docs/LLM_APPLICATION_GENERATION_RULES.md`.

Default model: `gpt-4.1-nano`.

Set the key as an environment variable:

```text
OPENAI_API_KEY
```

or copy `job_cockpit/config/openai.env.sample` to `job_cockpit/config/openai.env` and fill it locally. `openai.env` is ignored by git.

Use the API only from local backend scripts, never from frontend JavaScript. Keep the key out of git and logs.

Recommended OpenAI uses:

- generate a truthful resume payload;
- draft human-sounding cover letters under `APPLICATION_TEXT_GENERATION_RULES.md`;
- produce short fit notes for logs.
- answer safe free-text application questions using real resume facts and explicit answer-bank values.

If OpenAI is missing, unavailable, or produces invalid content, Job Cockpit falls back to deterministic generation.

Do not use OpenAI for:

- entering passwords;
- bypassing CAPTCHA;
- solving MFA;
- clicking broad legal/consent fields without review;
- guessing EEO/legal answers without explicit `application_answers.json` values;
- inventing resume facts.

## Reporting

Every automation run should write to Activity and the UI:

- started time;
- sources checked;
- jobs found;
- jobs scored;
- packages created;
- auto-submitted count;
- needs-review count;
- per-job reason for stopping;
- errors such as HTTP 429 or navigation failures.

The `Auto Applies` UI should remain the source of truth for auto-submitted vs needs-review applications.

## Target Behavior

The desired safe autopilot is:

1. scheduled search;
2. score and package good jobs;
3. auto-open/fill safe applications;
4. auto-submit only clean forms;
5. leave CAPTCHA/login/unknown forms ready for the user;
6. send a daily report with links to pages needing human action.
