from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a local Google OAuth token for Job Cockpit.")
    parser.add_argument("--credentials", default=str(ROOT / "config" / "google_oauth_client.json"))
    parser.add_argument("--token", default=str(ROOT / "config" / "google_token.json"))
    parser.add_argument("--calendar-only", action="store_true")
    args = parser.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Google OAuth dependencies are not installed. Run:")
        print("  python -m pip install -r job_cockpit/requirements-optional.txt")
        raise SystemExit(2)

    credentials = Path(args.credentials)
    if not credentials.exists():
        print(f"OAuth client file not found: {credentials}")
        print("Create a Google Cloud OAuth Desktop client and save its JSON there.")
        raise SystemExit(2)

    scopes = ["https://www.googleapis.com/auth/calendar.events"] if args.calendar_only else DEFAULT_SCOPES
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials), scopes=scopes)
    creds = flow.run_local_server(port=0)
    token = Path(args.token)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved Google OAuth token to {token}")
    print("Do not commit credentials or tokens. They are ignored by .gitignore.")


if __name__ == "__main__":
    main()
