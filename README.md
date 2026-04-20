# Mejor Rock en Español — Facebook Automation Bot

Fully automated Facebook content pipeline for the "Mejor Rock en Español" page.
Uses Gemini AI to generate posts, Pexels for images, and the Facebook Graph API to publish.
Runs entirely on GitHub Actions — no server, no laptop required.

## How it works

| Schedule | Action |
|---|---|
| Every Sunday 8:00 UTC | `generate.py` — Gemini creates 7 posts for the week |
| Every day 15:00 UTC | `publish.py` — Posts one item to Facebook (11am EST) |
| Every Sunday 8:30 UTC | `report.py` — Sends weekly summary email |

---

## One-time setup (do this once, then it runs forever)

### 1. Clone or create the GitHub repo

Create a **private** repo on github.com, then:

```bash
git clone https://github.com/YOUR_USERNAME/rock_bot.git
cd rock_bot
```

Copy all project files into this folder.

### 2. Get your API keys

| Key | Where to get it |
|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → Get API key |
| `FB_PAGE_ID` | Graph API Explorer → `/me/accounts` → find your page |
| `FB_PAGE_TOKEN` | See Step 3 below |
| `PEXELS_API_KEY` | [pexels.com/api](https://www.pexels.com/api/) → free account |

### 3. Get a long-lived Facebook Page Access Token

```bash
# Step A — exchange your short-lived token for a long-lived user token
curl "https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN"

# Step B — get your Page token from the long-lived user token
curl "https://graph.facebook.com/me/accounts?access_token=LONG_LIVED_USER_TOKEN"
```

Copy the `access_token` value next to your page name. This lasts 60 days.
Set a calendar reminder to refresh it every 55 days.

### 4. Add secrets to GitHub

Go to your repo → Settings → Secrets and variables → Actions → New repository secret.

Add one secret for each of these:

```
GEMINI_API_KEY
FB_PAGE_ID
FB_PAGE_TOKEN
PEXELS_API_KEY
REPORT_EMAIL      (optional — your email for weekly report)
SMTP_USER         (optional — Gmail address to send from)
SMTP_PASSWORD     (optional — Gmail App Password, not your real password)
```

### 5. Test locally first (optional but recommended)

```bash
# Windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Copy .env.example to .env and fill in your values
copy .env.example .env

# Test generation
python generate.py

# Inspect the queue
type posts.json

# Test publishing (this will post to your real page)
python publish.py
```

### 6. Push to GitHub

```bash
git add .
git commit -m "Initial setup"
git push origin main
```

GitHub Actions will now run automatically on schedule.

### 7. Trigger a manual test run

Go to your repo → Actions → Rock Bot Automation → Run workflow → choose "generate" → Run.
Then run "publish" to post immediately.

---

## Monitoring

- **GitHub Actions tab** — shows every run, logs, pass/fail status
- **Weekly email** — sent every Sunday morning with full stats
- **log.json** — full history of every post attempt (saved as GitHub artifact)
- **posts.json** — current queue state (saved as GitHub artifact)

To download log.json or posts.json: Actions → latest run → Artifacts section.

---

## Refreshing the Facebook token (every 55 days)

The Page Access Token expires after 60 days. Set a recurring reminder.
When it expires, repeat Step 3 above and update the `FB_PAGE_TOKEN` secret in GitHub.

---

## Costs

| Tool | Cost |
|---|---|
| GitHub Actions | Free (2,000 minutes/month included) |
| Gemini 1.5 Flash API | Free tier (generous daily limits) |
| Pexels API | Free |
| Facebook Graph API | Free |
| **Total** | **$0/month** |
