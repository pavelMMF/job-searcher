# LLM Application Generation Rules

These rules apply to the OpenAI-backed application generator.

## Purpose

The LLM generator may produce:

- a tailored resume payload for the existing PDF renderer;
- one short cover letter paragraph;
- short fit notes for logs/debugging.
- safe free-text screening answers during browser autofill.

The Python search and scoring scripts still decide which jobs are worth preparing. The LLM does not choose jobs by itself.

## Model

Default model: `gpt-4.1-nano`.

Reason: OpenAI's GPT-4.1 API announcement describes `gpt-4.1-nano` as the fastest and cheapest model in that family, with listed pricing of `$0.10 / 1M input tokens`, `$0.025 / 1M cached input tokens`, and `$0.40 / 1M output tokens`. This task is short-form structured rewriting, not complex reasoning.

Upgrade path:

- use `gpt-4.1-mini` if quality is not good enough;
- use `gpt-5.4` only for occasional higher-quality experiments;
- use larger models only for one-off review or rewrite experiments;
- keep deterministic fallback enabled.

## Cost Policy

Automatic OpenAI package generation is limited by workflow settings.

During `Wide Search` and `Daily Review`, the system may score and list many jobs, but it should generate a resume/cover-letter package only when one of these is true:

- the job can enter the safe Auto Queue: `auto_submit_allowed` is enabled and the job has an application URL;
- the job has `match_score >= always_generate_score`, default `100`;
- the user clicks `Generate Package` on a specific job.

For other jobs, keep the job scored and visible without spending OpenAI tokens. The user can still generate a package manually from the job detail panel.

## Secret Handling

The API key must not be written into source code, docs, command output, screenshots, or activity logs.

Supported key locations:

- environment variable `OPENAI_API_KEY`;
- local ignored file `job_cockpit/config/openai.env`.

The sample file is `job_cockpit/config/openai.env.sample`.

## Truthfulness

The LLM receives three candidate references:

- `master_resume.json` as the source of truth;
- `master_resume.experience_bank` for extra real projects, responsibilities and tools that are not always visible in the short base resume;
- deterministic fallback resume payload;
- extracted text from the original PDF resume, used as a style and completeness reference.

If the original PDF and `master_resume.json` conflict, `master_resume.json` wins for facts.

The generator may:

- reorder sections;
- emphasize matching real experience;
- compress or rewrite bullets;
- choose more relevant existing skills;
- adapt summary and highlights to the vacancy.
- use truthful stretch: mirror vacancy language and connect adjacent real experience to the role without claiming unsupported direct experience.

Generation pipeline:

1. Read the deterministic fallback payload shape.
2. Identify role family, seniority, tools and domain requirements from the vacancy.
3. Select only matching real facts from `master_resume.json`, `experience_bank`, fallback payload and reference PDF text.
4. Rewrite summary, highlights, skills and bullets inside the expected payload shape.
5. Preserve every real role and period.
6. Remove generic AI-style phrasing before returning JSON.
7. Return no metadata, no hidden notes, and no detector-facing signals such as `generated`, `tailored`, or prompt fragments.

The generator must not invent:

- employers;
- dates;
- degrees;
- citizenship;
- work authorization;
- tools absent from the master resume;
- metrics or results absent from the master resume;
- projects not present in the master resume;
- relocation/visa/sponsorship facts.

If an important vacancy requirement is absent from the resume facts, the generator must not add it to `skills`, `highlights`, or experience bullets as if Pavel has direct experience. It may only:

- emphasize adjacent real experience;
- mention a transferable pattern in the cover letter;
- record the gap in `fit_notes`;
- leave the deterministic fallback resume unchanged for that requirement.

## Resume Structure

The output resume payload must keep the same structure used by `resume_generator.py`:

- `name`;
- `headline`;
- `contacts`;
- `summary`;
- `highlights`;
- `skills`;
- `experience`;
- `education`;
- `training`;
- `target`.

Every real role from `job_cockpit/config/master_resume.json` must remain present. Required periods:

- `Apr 2025 - Present`;
- `Apr 2023 - Mar 2025`.

Each role must keep at least two bullets.

The headline should be the closest truthful vacancy-aligned target title from `master_resume.headline_variants` or the deterministic fallback payload. Prefer one clean title, not a multi-title string. Examples: `Product Data Analyst`, `Senior Marketing Analytics Engineer`, `Senior Analytics Engineer`, `Senior Data Analyst`, `Senior Product Analyst`, `Senior Marketing Data Analyst`, `Product Affiliate Analyst`, `BI Analyst`, or `Data Scientist`.

Do not restore older multi-title headlines such as `Product Analyst | Retention Analyst | Data Scientist`, and do not split the latest experience back into a separate `Dec 2025 - Present` Data Scientist role.

The LLM should actively rewrite experience bullets for the vacancy, not merely copy fallback bullets. It may:

- foreground the real responsibilities that match the vacancy;
- rewrite bullets toward marketing analytics, traffic/funnel analytics, product analytics, BI/reporting, analytics engineering, data science, AI automation, or stakeholder work depending on the job;
- merge adjacent real facts into stronger bullets;
- mirror vacancy wording when source facts support it.

It must not change role periods, employers, real experience role titles, education, citizenship, work authorization, metrics, or tools.

The LLM must not copy vacancy-only tools into skills or bullets unless they exist in the candidate facts. If the job mentions tools like LookML, Looker, dbt, Snowflake, BigQuery, AWS, GCP, Amplitude, Mixpanel, Segment, or similar terms and they are absent from `master_resume`, `fallback_resume_payload`, and the reference PDF, omit them and emphasize adjacent real experience instead. Do not include parenthetical vacancy markers such as `(preferred)`, `(nice to have)`, or `(required)` in the resume.

## Style

Resume:

- human, direct, concrete;
- ATS-readable;
- no generation metadata;
- no "Tailored for", "Generated", "AI", "agent notes", or `job-cockpit`;
- no fake marketing tone.
- no mass-generated rhythm where every bullet has the same abstract verb + vague business outcome shape.
- no overuse of exact job-description keywords when the real experience does not support them.

Cover letter:

- one paragraph;
- 100 words maximum;
- mention the company/role specifically;
- say why the company or role is interesting based on the job description;
- connect the role to real experience;
- no generic filler.

Screening answers:

- safe categories only: real relevant experience, why role/company, SQL/Python/BI/tool experience already in the resume, availability/profile text when explicitly configured;
- salary, notice period, relocation, work authorization, sponsorship, EEO, and legal consent may be answered only from explicit `application_answers.json` values;
- CAPTCHA, passwords, login, MFA, OTP, account security, broad legal acknowledgement, background checks, arbitration, account terms, marketing/newsletter consent, and unknown fields must not be filled by LLM.
- every proposed answer must be audited with field label, category, confidence, source facts, applied flag, and skip reason.

Forbidden phrases:

- `proven track record`;
- `results-oriented`;
- `dynamic`;
- `innovative`;
- `cutting-edge`;
- `tech-savvy`;
- `excellent communicator`;
- `team player`;
- `leveraging my expertise`;
- `fast-paced environment`;
- `I am excited to apply`;
- `I am thrilled to apply`;
- `as an AI`.

## Validation

After OpenAI returns JSON, Python validators must still run:

- resume payload validation;
- required periods check;
- minimum bullets per role check;
- forbidden marker check;
- cover letter length check;
- cover letter forbidden phrase check.

If validation fails, the system must log a warning and fall back to deterministic generation or the standard resume.

## Logging

Logs may include:

- job id;
- model name;
- usage object;
- short fit notes;
- validation failure reason.

Logs must not include:

- API key;
- full prompt with secret;
- raw OpenAI headers;
- unredacted authentication errors.
