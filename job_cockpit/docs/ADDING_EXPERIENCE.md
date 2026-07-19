# Adding More Real Experience

Use this when your real experience is broader than the short resume.

## Best Place To Add It

Add extra experience to `master_resume.experience_bank`.

This keeps the base resume clean while giving the generator more truthful material for specific vacancies.

## What To Add

Good experience-bank items:

- extra projects that did not fit into the base CV;
- tools used in a real task, even if not your main stack;
- analytics domains: CRM, lifecycle, affiliate, marketing, finance, risk, fraud, product, monetization;
- task types: dashboards, funnels, cohorts, retention, churn, LTV, GGR, A/B tests, forecasting, automation, ETL, API work;
- stakeholder work: product, marketing, finance, support, management;
- prototypes: RAG, agents, vector search, churn models, reporting automation.

Do not add claims you cannot explain in an interview.

## Format

Copy `job_cockpit/config/experience_bank.sample.json`, edit it, then import:

```powershell
Copy-Item job_cockpit\config\experience_bank.sample.json job_cockpit\config\my_experience_bank.json
notepad job_cockpit\config\my_experience_bank.json
python job_cockpit\core\import_experience_bank.py job_cockpit\config\my_experience_bank.json
```

## Example Item

```json
{
  "id": "crm_retention_analysis",
  "source": "iGaming retention analytics",
  "role_period": "Apr 2025 - Present",
  "tags": ["crm", "retention", "lifecycle", "cohort analysis"],
  "skills": ["SQL", "Python", "Tableau", "Google Sheets"],
  "bullets": [
    "Analyzed CRM and retention campaigns using cohorts, LTV, churn and player activity segments.",
    "Prepared recurring dashboards and manager-facing reports for product, marketing and finance decisions."
  ],
  "notes": "Anonymized real project."
}
```
