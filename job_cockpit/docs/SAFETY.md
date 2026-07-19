# Job Cockpit Safety Boundaries

This project is designed as a human-in-the-loop job application assistant.

Allowed automation:

- Search public career pages at a normal browsing pace.
- Parse job descriptions and score fit against your profile.
- Generate truthful cover-letter drafts and application notes.
- Fill known form fields from your profile.
- Open visible application pages and click initial non-submit Apply links/buttons that navigate to the form.
- Safe-submit a fully recognized final form only when `auto_submit_allowed` is enabled.
- Export interview events as `.ics` calendar files.

Manual checkpoints:

- CAPTCHA and security challenges.
- Passwords, login approval, MFA, and account recovery screens.
- Final application submit when required fields, legal consents, demographic/EEO questions, account checks, or submit intent are unclear.
- Privacy/consent checkboxes and demographic questions unless you explicitly review them.
- Any required field that the assistant cannot classify confidently.

Blocked automation:

- CAPTCHA bypass or third-party CAPTCHA-solving integration.
- Credential extraction or hidden login automation.
- Mass application spam.
- Circumventing platform rate limits, anti-bot rules, or access controls.

The safe default is simple: the cockpit can prepare and fill, then it pauses for you.
