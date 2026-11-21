# Citizen of Gamoria — Autopost

Posts your Shorts to **YouTube** and **Instagram Reels** at the time you schedule, using GitHub Actions. Your PC can be off.

How it works:

1. On your PC, add clips to the queue with `scripts/plan.py`. It copies the MP4 from your clipper's `clips\out` folder into `videos/` and writes the title, caption and time into `queue.json`.
2. You push to GitHub.
3. Every 15 minutes GitHub checks the queue. Anything whose time has passed gets posted, `queue.json` is updated with the post IDs, and the video file is deleted from the repo.

**Timing:** clips go out within about 15–30 minutes after the scheduled time, not to the exact minute. GitHub sometimes starts scheduled runs late.

---

## One-time setup

You need Python and Git on your PC. Takes about an hour, plus waiting for Google (step 2).

### 1. Create the GitHub repo

1. On github.com, create a **new public repository**, for example `gamoria-autopost`. Leave it empty.
2. In this folder (`D:\Automation\autopost`) run:

```
mkdir .github\workflows
move autopost.yml .github\workflows\autopost.yml
git init
git add -A
git commit -m "autopost setup"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/gamoria-autopost.git
git push -u origin main
```

### 2. YouTube API

1. Go to <https://console.cloud.google.com>, create a project (e.g. "Gamoria Autopost").
2. **APIs & Services → Library** → enable **YouTube Data API v3**.
3. **APIs & Services → OAuth consent screen** → External → fill in app name and your email → add yourself as a test user.
4. **Important:** on the same screen click **Publish app** so its status is **In production**. If it stays in "Testing", the token stops working after 7 days. (Google will show an "unverified app" warning when you sign in. That's fine for your own use. Click Advanced → continue.)
5. **APIs & Services → Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON file. Keep it out of the repo.
6. On your PC:

```
pip install google-auth-oauthlib
python scripts/get_youtube_token.py "C:\path\to\client_secret.json"
```

Sign in with the Google account that owns the channel. It prints three values for step 4.

**YouTube audit (required for public posts).** Videos uploaded through the API by an unaudited project are locked to **private**. Apply for the audit here: <https://support.google.com/youtube/contact/yt_api_form>. Until it's approved, uploads land as private and you can make them public by hand in YouTube Studio.

### 3. Instagram API (no Facebook Page needed)

This uses Instagram's "API with Instagram login". Instagram downloads each video from its public link in this repo, which is why the repo is public. Your tokens stay hidden in GitHub Secrets.

Your Instagram must be a **Business** (or Creator) account: Instagram app → Settings → Account type and tools → Switch to professional account.

1. Go to <https://developers.facebook.com> → **My Apps → Create app**. Name it `Gamoria Autopost`.
2. For the use case, choose **Manage messaging & content on Instagram**. Skip connecting a business portfolio if asked. Finish creating the app.
3. In the app, open **Instagram → API setup with Instagram login**.
4. Under **Generate access tokens**, click **Add account** and log in as **@citizenofgamoria**. Allow the permissions, including content publishing.
5. Next to the account, click **Generate token**. Copy the token. This is **IG_ACCESS_TOKEN** (valid 60 days; the weekly job renews it).
6. The number shown next to the account name is its Instagram user ID. This is **IG_USER_ID**.
7. **Token renewal (GH_PAT):** on GitHub go to **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**. Repository access: **Only select repositories → gamoria-autopost**. Permissions: **Secrets → Read and write**. Expiration: the longest offered. Copy the token.

### 4. Add GitHub secrets

GitHub → your repo → **Settings → Secrets and variables → Actions → New repository secret**. Add all six:

| Secret | Value |
|---|---|
| `YT_CLIENT_ID` | from step 2.6 |
| `YT_CLIENT_SECRET` | from step 2.6 |
| `YT_REFRESH_TOKEN` | from step 2.6 |
| `IG_USER_ID` | from step 3.6 |
| `IG_ACCESS_TOKEN` | from step 3.5 |
| `GH_PAT` | from step 3.7 (lets the weekly job save the renewed Instagram token) |

Never put these in a file in the repo.

### 5. Test it

Queue one clip a few minutes in the past and push:

```
python scripts/plan.py add "D:\Automation\clips\out\01_xqc_bike_flying.mp4" --at "2026-11-20 20:00"
git add -A && git commit -m "test clip" && git push
```

Then GitHub → **Actions → Autopost → Run workflow**. Watch the log. Afterwards run `git pull` and `python scripts/plan.py list` to see the result.

---

## Daily use

```
# Schedule one clip at a time you choose (your local time)
python scripts/plan.py add "D:\Automation\clips\out\02_xqc_dirt_bike_race.mp4" --at "2026-11-22 19:00"

# Or let it pick the next free slot (13:00, 19:00, 22:00 — change in config.json)
python scripts/plan.py add "D:\Automation\clips\out\02_xqc_dirt_bike_race.mp4" --auto

# Queue every clip in the folder, one per free slot
python scripts/plan.py add-all "D:\Automation\clips\out"

# See what's scheduled and what failed
python scripts/plan.py list

# Take one out
python scripts/plan.py remove 02_xqc_dirt_bike_race
```

Always **`git pull` first**, then add clips, then:

```
git add -A && git commit -m "queue clips" && git push
```

Captions come from the clipper's `.txt` file next to each MP4: the title, the credit line, your subscribe line and the hashtags. Edit `title` or `caption` in `queue.json` before pushing if you want to change them.

## Settings (`config.json`)

| Setting | What it does |
|---|---|
| `auto_slots` | Times used by `--auto` and `add-all` |
| `default_platforms` | `["youtube", "instagram"]`; use `--platforms youtube` to post one clip to one place |
| `channel_cta` | Line added to every caption |
| `delete_video_after_post` | Removes the MP4 from the repo once posted |
| `max_attempts` | Retries before an upload is marked failed |
| `youtube.privacy_status` | `public`, `unlisted` or `private` |
| `youtube.use_publish_at` | `true` = upload early and let YouTube publish at the exact minute (works once your project passes the audit) |
| `instagram.mode` | `instagram` (current: no Facebook Page, needs this repo public and `public_video_base_url` set). `facebook` uploads the file directly but needs a Business account linked to a Facebook Page |

## When something fails

- GitHub emails you when a run fails.
- `python scripts/plan.py list` shows the error for each upload. A failed upload is retried on the next runs, up to `max_attempts`.
- To retry after fixing a problem, change that platform's `"status"` back to `"pending"` and `"attempts"` to `0` in `queue.json`, then push.
- Instagram has a daily cap on API-published posts per account. It is far above a few Shorts a day.

## Limits to know

- GitHub rejects files over **100 MB**. Your Shorts are 15–40 MB.
- Public repos get unlimited free Actions minutes. If you ever make the repo private, change the schedule back to every 30 minutes and switch Instagram to `facebook` mode (needs a Facebook Page).
- Each clip is publicly downloadable from the repo between being queued and being posted.
- Keep crediting the streamer in every caption. The clipper already adds the credit line.
