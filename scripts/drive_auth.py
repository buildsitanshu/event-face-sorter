#!/usr/bin/env python
"""One-time Google Drive authorisation for event-face-sorter (Drive mode only).

Not exercised against a live Google account on the build machine; the token shape is read by drive.py make_creds.

Usage:
    sorter/.venv/bin/python scripts/drive_auth.py <client_secret.json> [--out ~/.config/event-face-sorter/oauth.json]

<client_secret.json> is the OAuth client (type Desktop) downloaded from your Google Cloud project.
A browser window opens once; after you approve read-only Drive access, a token file is written
(mode 0600) with token, refresh_token, client_id, client_secret, token_uri and scopes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DEFAULT_OUT = "~/.config/event-face-sorter/oauth.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="authorise read-only Google Drive access for event-face-sorter")
    ap.add_argument("client_secret", help="path of the OAuth client json (type Desktop) from Google Cloud")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"where to write the token json (default {DEFAULT_OUT})")
    args = ap.parse_args()

    secret = os.path.expanduser(args.client_secret)
    if not os.path.isfile(secret):
        print(f"client secret file not found: {secret}", file=sys.stderr)
        return 2
    out = os.path.expanduser(args.out)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
    creds = flow.run_local_server(port=0)
    if not creds.refresh_token:
        print("Google returned no refresh token. Remove this app at https://myaccount.google.com/permissions and run again.", file=sys.stderr)
        return 1

    info = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri or "https://oauth2.googleapis.com/token",
        "scopes": list(creds.scopes or SCOPES),
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(info, fh, indent=2)
    os.chmod(out, 0o600)
    print(f"token written: {out}")
    print("next step: put CONVO_ROOT_FOLDER_ID (and optionally CONVO_ROSTER_FOLDER_ID) in .env, then run ./run.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
