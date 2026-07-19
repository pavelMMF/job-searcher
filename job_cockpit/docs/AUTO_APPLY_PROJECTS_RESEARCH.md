# Auto-Apply Project Notes

Research date: 2026-06-28.

## Useful Comparable Projects

1. [ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot)

   Open-source pipeline with discovery, enrichment, scoring, resume tailoring, cover letters, and browser submission. Useful ideas for Job Cockpit: staged pipeline, dry-run apply mode, direct employer portals, and independent stages.

2. [Jobber](https://github.com/sentient-engineering/jobber)

   Browser-controlling AI agent for autonomous job applications. Useful idea: a browser agent can work across more sites than site-specific scrapers, but needs strict human handoff and audit logs because arbitrary forms are unstable.

3. [Job-apply-AI-agent](https://github.com/imon333/Job-apply-AI-agent)

   Python/n8n/Selenium/OpenAI style workflow that combines scraping, CV generation, applications, Google Sheets/Airtable, and email alerts. Useful ideas: workflow orchestration, spreadsheet-style tracking, and separate output directories for jobs and generated CVs.

4. [LinkedIn AI Job Applier Ultimate](https://github.com/beatwad/LinkedIn-AI-Job-Applier-Ultimate)

   Playwright/LLM-based LinkedIn and Indeed bot with custom resumes, question answering, dashboard, Telegram reports, run history, and scheduling. Useful ideas: dashboard, run history, screenshots, pause/resume, configuration validation, and "skip when information is missing".

5. [AIHawk](https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk)

   Large older project and common base for forks. Useful as an architecture reference, but not ideal as a direct dependency because the repository is archived/read-only.

6. [EasyApplyJobsBot](https://github.com/wodsuz/EasyApplyJobsBot)

   LinkedIn/Glassdoor-style Easy Apply bot. Useful idea: answer repeated application questions from a local profile. Risk: site-specific UI automation breaks often.

7. [LinkedIn Easy Apply Bot](https://github.com/nicolomantini/LinkedIn-Easy-Apply-Bot)

   Popular Easy Apply automation. Useful as a reminder that site-specific automation can reduce clicks, but it is fragile and can conflict with platform rules.

## Ideas Adopted Here

- Answer bank separate from resume/profile.
- Dry-run and safe-submit distinction.
- JSON run history per attempt.
- Screenshot per attempt when possible.
- UI link from each auto-apply record to the audit.
- Strict skip-on-unknown behavior.
- Human handoff for CAPTCHA/login/legal/EEO fields.
- Explicit booleans for work authorization and sponsorship.

## Ideas Not Adopted

- CAPTCHA bypass.
- Anti-bot or Cloudflare bypass.
- Password/OTP handling.
- Direct LinkedIn credential storage.
- Blind final-submit on unknown forms.
- Fabricating answers when the resume/profile lacks information.

## Next Useful Ideas

- Add a Telegram or mobile push report after each queue run.
- Add a reviewed answer memory: if the user manually answers a recurring safe screening question, save it to `application_answers.json`.
- Add per-domain rules for stable ATS systems such as Greenhouse, Lever, Ashby, Workable, SmartRecruiters, and Workday.
- Add a visible "Needs Human" queue showing the exact field labels from the latest audit.
- Add a browser-side pause button for long runs.
