# 🤖 Job Search Agent

**Automated job scraper** that monitors 150+ company career pages, matches jobs to your skills using synonym-aware matching, filters out visa-restricted roles, and sends you notifications — **100% free**.

## How It Works

```
Excel file(s) with companies + career URLs
              ↓
  PASS 1: Scrape career pages (Greenhouse, Lever, Workday, SmartRecruiters, Ashby)
              ↓
  Synonym-aware matching against your skills & preferences
              ↓
  PASS 2: Fetch full descriptions for matched jobs only
              ↓
  Re-filter (catches "no sponsorship", citizenship requirements in descriptions)
              ↓
  Deduplicate via SQLite — only alert on NEW jobs
              ↓
  Notify via Email / Telegram / Discord
              ↓
  Weekly summary + Application pipeline tracking
```

---

## ⚡ Quick Start (5 minutes)

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/job-search-agent.git
cd job-search-agent
pip install -r requirements.txt
```

### 2. Add Your Company Excel Files

Copy your Excel files (e.g., `Semiconductor_Companies.xlsx`, `Robotics_Companies.xlsx`) into the `data/` folder.

The agent auto-detects columns named `Company Name` and `Career Portal Link` (or similar).

### 3. Customize Skills in `config.yaml`

Edit the `skills` section to match your target roles:

```yaml
skills:
  primary:        # Job title keywords (must match at least one)
    - "data analyst"
    - "ML engineer"
    - "business intelligence"
  technical:      # Boost score if these appear
    - "Python"
    - "SQL"
    - "Tableau"
  exclude:        # Skip jobs with these (checked in title + description)
    - "director"
    - "10+ years"
    - "will not sponsor"
    - "US citizen"
    - "security clearance"
```

**You don't need to list every variation** — the agent has built-in synonyms (see [Synonym Matching](#-synonym-matching) below).

### 4. Test It

```bash
python setup_test.py       # Verify dependencies
python main.py --dry-run   # Scrape + match, show results in console
```

### 5. Set Up Notifications (pick one)

See [Notification Setup](#-notification-setup) below.

### 6. Deploy for Automated Runs (free)

See [Deployment](#-free-deployment-github-actions) below.

---

## 🧠 Synonym Matching

The agent automatically expands your keywords to catch related job titles. You configure one keyword and it matches the entire family:

| You Configure | Also Matches |
|---|---|
| `data analyst` | analytics analyst, quantitative analyst, data analytics specialist, insight analyst, decision analyst, analytics associate |
| `ML engineer` | machine learning engineer, applied ML engineer, ML ops engineer, MLOps, ML developer |
| `business intelligence` | BI analyst, BI developer, BI engineer, reporting analyst, insights analyst |
| `marketing operations` | marketing ops, demand generation, revenue operations, marketing automation |
| `data scientist` | applied scientist, research scientist, quantitative researcher, decision scientist |
| `data engineer` | analytics engineer, ETL developer, data platform engineer, data infrastructure engineer |
| `software engineer` | software developer, SWE, SDE, backend engineer, full stack engineer |
| `robotics engineer` | robotics software engineer, automation engineer, controls engineer, perception engineer |

Technical skills are also expanded:

| You Configure | Also Matches |
|---|---|
| `Python` | python3, python programming |
| `SQL` | MySQL, PostgreSQL, Postgres |
| `A/B testing` | AB testing, experimentation, split testing |
| `Power BI` | PowerBI |
| `machine learning` | ML, statistical modeling |
| `AWS` | Amazon Web Services |

**In notifications**, synonym matches show as `ml engineer→machine learning engineer` so you know which variant was found.

### Adding Custom Synonyms

If the built-in lists don't cover your niche, add custom synonym groups in `config.yaml`:

```yaml
skills:
  role_synonyms:
    - ["semiconductor engineer", "fab engineer", "process engineer", "wafer engineer"]
    - ["devops engineer", "site reliability engineer", "SRE", "platform engineer"]

  tech_synonyms:
    - ["ROS", "Robot Operating System", "ROS2"]
    - ["MATLAB", "Simulink"]
```

---

## 📄 Two-Pass Description Fetching

Most job APIs only return titles and locations in their list endpoints. The agent uses a **two-pass strategy** to get full descriptions efficiently:

```
PASS 1 (fast):   Scrape all 150 companies → get titles/locations → ~3,000 jobs
                  Filter by primary keywords → ~50-100 matches
                  ⏱️ ~10 minutes

PASS 2 (targeted): Fetch full descriptions ONLY for those 50-100 matches
                   Re-filter with description text (catches visa restrictions, 
                   boosts technical skill scores)
                   ⏱️ ~5-15 minutes
```

This means visa/sponsorship exclusion keywords like `"will not sponsor"` or `"US citizen"` are properly caught even when they only appear deep in the job description.

**To disable** (faster runs, less accurate filtering):
```yaml
scraping:
  fetch_descriptions: false
```

---

## 🇺🇸 Smart Location Detection

The agent understands US job location formats automatically. Set `country: "US"` in config and it handles:

| Location Format | Detected As |
|---|---|
| `Milpitas, CA` | ✅ US (state abbreviation) |
| `Austin, TX 78701` | ✅ US (state + zip) |
| `San Jose, CA (Remote)` | ✅ US + Remote |
| `California` | ✅ US (full state name) |
| `United States` | ✅ US |
| `Multiple Locations` | ✅ US (multi-location) |
| `San Jose, CA \| Austin, TX \| NYC, NY` | ✅ US (pipe-separated) |
| `Nationwide` | ✅ US |
| `Multiple Locations (India)` | ❌ Not US (non-US country detected) |
| `London, UK` | ❌ Not US |
| `Remote` | ➡️ Scored as Remote (+4), not specifically US |

**Scoring:**

| Location Type | Score |
|---|---|
| Preferred city (e.g., San Jose, Austin) | +5 |
| Remote job | +4 |
| Any US location (auto-detected) | +3 |
| Non-US / Unknown | +0 |

---

## 🚫 Visa & Sponsorship Filtering

Add these to your `exclude` list in `config.yaml` to skip jobs that won't sponsor work visas:

```yaml
exclude:
  - "US citizen"
  - "U.S. citizen"
  - "citizenship required"
  - "security clearance"
  - "TS/SCI"
  - "no sponsorship"
  - "will not sponsor"
  - "does not sponsor"
  - "unable to sponsor"
  - "no visa sponsorship"
  - "permanent resident"
  - "green card required"
  - "US persons only"
  - "ITAR"
  - "EAR"
```

These are checked against the **full job description** (not just the title), so they catch requirements buried in the posting text — but only when `fetch_descriptions: true` is enabled.

---

## 📝 Application Tracking

Track every job you apply to and monitor your pipeline from the command line:

### Track a New Application
```bash
python main.py apply \
  --company "NVIDIA" \
  --title "Data Analyst" \
  --url "https://nvidia.com/jobs/123" \
  --resume "data_v3" \
  --salary "130k-160k" \
  --notes "Referral from Sarah"
```

### Update Status as You Progress
```bash
python main.py update 1 --status screening --notes "Recruiter call Thursday"
python main.py update 1 --status interview --interview-date 2025-03-01
python main.py update 1 --status offer --salary "145k + RSUs"
python main.py update 1 --status accepted
```

**Available statuses:** `applied` → `screening` → `interview` → `final_round` → `offer` → `accepted`
Also: `rejected`, `withdrawn`, `closed`, `no_response`

### View Applications
```bash
python main.py apps                        # All applications
python main.py apps --status interview     # Filter by status
python main.py apps --company NVIDIA       # Filter by company
```

### Pipeline Dashboard
```bash
python main.py pipeline
```

Output:
```
  📊 APPLICATION PIPELINE
  Total: 12  |  Response Rate: 58%  |  Avg Response: 8.3 days

  📤 applied        ████████████████████████████ 5
  📞 screening      ██████████████████ 3
  🎯 interview      ████████████ 2
  ❌ rejected       ██████ 1
  🎉 offer          ██████ 1
```

### Delete an Application
```bash
python main.py delete-app 5
```

---

## 📅 Weekly Summary

The agent automatically sends a **weekly digest** every Sunday including:

- New jobs discovered that week (count + breakdown by company)
- Top scoring active jobs
- Your application pipeline status
- Jobs that may have been taken down (stale listings)
- Scraping run statistics (errors, total scraped)

**Manually trigger anytime:**
```bash
python main.py --weekly-summary
```

The summary is sent through your configured notification channel (Email/Telegram/Discord/Console).

---

## 📬 Notification Setup

### Option A: Email (Gmail)

1. **Create a Gmail App Password** (NOT your real password):
   - Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   - You need 2-Factor Authentication enabled first
   - Select "Mail" → "Other" → name it "Job Agent" → Generate
   - Copy the 16-character password

2. **Edit `config.yaml`**:
   ```yaml
   notification:
     method: "email"
     email:
       smtp_server: "smtp.gmail.com"
       smtp_port: 587
       sender_email: "your.email@gmail.com"
       sender_password: "xxxx xxxx xxxx xxxx"  # App password from step 1
       recipient_email: "your.email@gmail.com"
   ```

### Option B: Telegram Bot (Recommended — instant push notifications)

1. **Create a bot**: Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → follow prompts → copy the **bot token**
2. **Get your chat ID**: Message [@userinfobot](https://t.me/userinfobot) → it replies with your **chat ID**
3. **Start your bot**: Open the bot link BotFather gave you and press "Start"
4. **Edit `config.yaml`**:
   ```yaml
   notification:
     method: "telegram"
     telegram:
       bot_token: "7123456789:AAF..."
       chat_id: "123456789"
   ```

### Option C: Discord Webhook

1. In your Discord server: **Server Settings** → **Integrations** → **Webhooks** → **New Webhook**
2. Copy the webhook URL
3. **Edit `config.yaml`**:
   ```yaml
   notification:
     method: "discord"
     discord:
       webhook_url: "https://discord.com/api/webhooks/..."
   ```

---

## 🚀 Free Deployment (GitHub Actions)

The agent runs **twice daily** on GitHub's servers for free. The database is stored in **GitHub Releases** (not git commits) to avoid repository bloat.

### Step 1: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
gh repo create job-search-agent --public --push
```

> **Public repo = unlimited free minutes.** Private repo = 2,000 min/month free (agent uses ~600 min/month at twice daily).

### Step 2: Add Notification Secrets

Go to your repo on GitHub → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret Name | Value |
|---|---|
| `SENDER_EMAIL` | your Gmail address |
| `SENDER_PASSWORD` | your Gmail App Password |
| `RECIPIENT_EMAIL` | email to receive alerts |
| — OR — | |
| `TELEGRAM_BOT_TOKEN` | your Telegram bot token |
| `TELEGRAM_CHAT_ID` | your Telegram chat ID |
| — OR — | |
| `DISCORD_WEBHOOK_URL` | your Discord webhook URL |

### Step 3: Uncomment Env Vars in Workflow

Edit `.github/workflows/daily_job_search.yml` and uncomment the env vars for your notification method.

### Step 4: Enable & Test

1. Go to repo → **Actions** tab → Enable workflows
2. Click "Daily Job Search" → "Run workflow" → Run

### Where Is My Database?

Your job database (`jobs.db`) is stored in **GitHub Releases**, not in git history. This prevents your repository from growing indefinitely.

- **View it**: Go to your repo → **Releases** (right sidebar) → **db-latest**
- **Download it**: Click the `jobs.db` asset to download
- **Browse it locally**: Open with [DB Browser for SQLite](https://sqlitebrowser.org/) (free)
- **First run**: No release exists yet — the agent starts with an empty database
- **Every subsequent run**: Downloads the latest database, runs the agent, uploads the updated database

### Changing the Schedule

Edit the cron expression in `.github/workflows/daily_job_search.yml`:

```yaml
schedule:
  - cron: '0 8,20 * * *'       # Twice daily: 8 AM and 8 PM UTC
```

Other examples:
| Cron | Schedule |
|---|---|
| `0 8 * * *` | Once daily at 8 AM UTC |
| `0 8,20 * * *` | Twice daily (8 AM + 8 PM UTC) |
| `0 8 * * 1-5` | Weekdays only at 8 AM UTC |
| `0 13,1 * * *` | 8 AM + 8 PM EST (adjusted for UTC) |

---

## 📁 Project Structure

```
job-search-agent/
├── main.py                 # Main orchestrator + CLI for application tracking
├── config.yaml             # Skills, preferences, notifications, scraping settings
├── requirements.txt        # Python dependencies
├── setup_test.py           # Quick setup validation
├── .gitignore              # Excludes jobs.db from git (stored in Releases)
├── data/                   # Place your Excel files here
│   └── jobs.db             # Auto-created locally (stored in GitHub Releases)
├── src/
│   ├── excel_reader.py     # Reads company list from Excel
│   ├── job_platforms.py    # Scrapers + description fetchers for all platforms
│   ├── skill_matcher.py    # Synonym-aware filtering & scoring
│   ├── database.py         # SQLite dedup + application tracking + weekly summary
│   └── notifier.py         # Email / Telegram / Discord / Console notifications
└── .github/
    └── workflows/
        └── daily_job_search.yml  # GitHub Actions cron (twice daily)
```

---

## 🔧 All Commands

```bash
# ---- Scraping ----
python main.py                     # Full run: scrape → match → notify
python main.py --dry-run           # Scrape + match, print to console (no notifications)
python main.py --verbose           # Detailed logging
python main.py --files a.xlsx b.xlsx  # Use specific Excel files

# ---- Info ----
python main.py --stats             # Database statistics
python main.py --weekly-summary    # Send weekly digest now

# ---- Application Tracking ----
python main.py apply -c "NVIDIA" -t "Data Analyst" --url "..." --resume "v3"
python main.py update 1 --status interview --notes "Technical round"
python main.py apps                # List all applications
python main.py apps -s interview   # Filter by status
python main.py apps -c NVIDIA      # Filter by company
python main.py pipeline            # Visual pipeline dashboard
python main.py delete-app 5        # Remove application #5
```

---

## 🎯 How Scoring Works

Each job gets a **relevance score** based on:

| Factor | Points |
|---|---|
| Primary keyword in **job title** (or synonym) | +10 per match |
| Primary keyword in **description** (or synonym) | +3 per match |
| Technical skill found (or synonym) | +2 per match |
| Preferred city match | +5 |
| Remote job (if enabled) | +4 |
| US location (any city/state, when country: "US") | +3 |

Jobs scoring higher appear first in notifications.

---

## 🔌 Supported Platforms

| Platform | Method | Pagination | Description Fetch |
|---|---|---|---|
| **Greenhouse** | JSON API | ✅ Full (100/page) | ✅ Per-job API |
| **Lever** | JSON API | ✅ Full (100/page) | ✅ HTML parsing |
| **Workday** | Search API | ✅ Full (20/page, auto-detects wd1-wd5) | ✅ JSON API |
| **SmartRecruiters** | JSON API | ✅ Full (100/page) | ✅ Per-job API |
| **Ashby** | JSON API | ✅ Single request | ✅ Per-job API |
| **Other** | HTML scraping | ❌ Landing page only | ⚠️ Best-effort HTML parsing |

---

## 💡 Tips

- **Start with `--dry-run`** to verify everything works before enabling notifications
- **First run is large**: Every matched job is "new" — subsequent runs only notify on genuinely new postings
- **Delete `data/jobs.db`** after a dry run if you want the first real run to also treat everything as new
- **Finding better URLs**: Google `site:boards.greenhouse.io "company name"` to check if a company uses Greenhouse (more reliable than generic scraping)
- **Disable description fetching** (`fetch_descriptions: false`) for faster runs if you don't need visa filtering
- **Add custom synonym groups** for niche roles not covered by the built-in lists
- **Check `python main.py --stats`** periodically to see how your database is growing

---

## License

MIT — free for personal use.
