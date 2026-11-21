"""Renew the Instagram access token (Instagram Login tokens last 60 days).

Run weekly by .github/workflows/refresh-ig-token.yml. Prints the new token to a file
given as the first argument, so the workflow can save it back into the IG_ACCESS_TOKEN secret.
"""
import os
import sys

import requests


def main():
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        print("IG_ACCESS_TOKEN secret is missing")
        return 1
    r = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=60,
    )
    data = r.json()
    if r.status_code >= 400 or "access_token" not in data:
        print(f"Refresh failed ({r.status_code}): {data}")
        return 1
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(data["access_token"])
    days = int(data.get("expires_in", 0)) // 86400
    print(f"Token renewed, valid for about {days} days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
