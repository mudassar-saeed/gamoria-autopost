"""One-time helper: get a YouTube refresh token for the autopost workflow. Runs on your PC.

  pip install google-auth-oauthlib
  python scripts/get_youtube_token.py path\\to\\client_secret.json

A browser opens; sign in with the Google account that owns the channel and allow access.
It prints three values. Paste each into GitHub > repo > Settings > Secrets and variables
> Actions as YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN. Never commit them.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    flow = InstalledAppFlow.from_client_secrets_file(path, scopes=SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        print("No refresh token returned. Remove the app's access at "
              "https://myaccount.google.com/permissions and run this again.")
        return 1
    with open(path, encoding="utf-8") as f:
        info = json.load(f)
    info = info.get("installed") or info.get("web") or {}
    print("\nAdd these as GitHub secrets:\n")
    print(f"YT_CLIENT_ID      = {info.get('client_id')}")
    print(f"YT_CLIENT_SECRET  = {info.get('client_secret')}")
    print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
