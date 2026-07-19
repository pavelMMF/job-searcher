# Account Access

Do not paste passwords, OTP codes, recovery codes, or session cookies into chat.

## LinkedIn

Use a local browser session:

```powershell
python job_cockpit\automation\linkedin_collect.py --pages 2
```

What happens:

- A visible Chromium window opens with a persistent local profile in `job_cockpit\browser_profiles\linkedin`.
- You log in to LinkedIn yourself.
- If LinkedIn shows CAPTCHA, checkpoint, or MFA, you handle it manually.
- The script collects visible job cards from LinkedIn search pages and imports them into Job Cockpit.

Reset access by deleting:

```text
job_cockpit\browser_profiles\linkedin
```

The cockpit does not store your LinkedIn password and does not bypass LinkedIn security checks.

## Google

Use OAuth, not a password.

1. Create a Google Cloud OAuth Client ID for a Desktop app.
2. Save the downloaded JSON as:

```text
job_cockpit\config\google_oauth_client.json
```

3. Install optional dependencies:

```powershell
python -m pip install -r job_cockpit\requirements-optional.txt
```

4. Run:

```powershell
python job_cockpit\automation\google_oauth_setup.py
```

For calendar-only access:

```powershell
python job_cockpit\automation\google_oauth_setup.py --calendar-only
```

The token is saved locally:

```text
job_cockpit\config\google_token.json
```

Both Google files are ignored by git.

Default scopes:

- Calendar events read/write for interview scheduling.
- Gmail read-only for detecting interview invites.
- Gmail compose for drafting follow-ups. Sending should remain manual unless you explicitly add a send-confirmation workflow.

## Job Sites With Google Login

Google OAuth for Calendar/Gmail does not give the agent a universal login to ATS/job sites.

For job sites that support `Sign in with Google`, use a persistent Playwright browser profile:

1. run the browser automation in visible mode;
2. sign in with Google yourself in the opened browser;
3. pass CAPTCHA, MFA, or security checks manually;
4. let the agent reuse the saved local browser session on later runs.

The LLM should never receive your Google password, OTP, session cookies, or recovery codes. It can operate on the already-open authenticated page through Playwright, but authentication itself stays in the local browser session.
