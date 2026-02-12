#!/usr/bin/env python3
"""
JOB SEARCH AGENT — Main Orchestrator
Scrapes career pages, matches skills, deduplicates, and sends notifications.

Usage:
    python main.py                          # Run with default config
    python main.py --config myconfig.yaml   # Custom config
    python main.py --files companies1.xlsx companies2.xlsx  # Custom Excel files
    python main.py --stats                  # Show database stats
    python main.py --dry-run                # Scrape & match but don't notify
"""

import os
import sys
import glob
import yaml
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.excel_reader import load_companies_from_excel, load_companies_from_multiple_files
from src.job_platforms import JobScraper
from src.skill_matcher import SkillMatcher
from src.database import JobDatabase
from src.notifier import Notifier


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        logging.warning(f"Config not found: {config_path}, using defaults")
        return {}
    with open(path, 'r') as f:
        config = yaml.safe_load(f) or {}

    # ---- Override notification config from environment variables ----
    # This allows GitHub Actions secrets to work without touching config.yaml
    if os.environ.get("SENDER_EMAIL"):
        config.setdefault("notification", {})
        config["notification"]["method"] = "email"
        config["notification"]["email"] = {
            "smtp_server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
            "smtp_port": int(os.environ.get("SMTP_PORT", 587)),
            "sender_email": os.environ["SENDER_EMAIL"],
            "sender_password": os.environ.get("SENDER_PASSWORD", ""),
            "recipient_email": os.environ.get("RECIPIENT_EMAIL", os.environ["SENDER_EMAIL"]),
        }
    elif os.environ.get("TELEGRAM_BOT_TOKEN"):
        config.setdefault("notification", {})
        config["notification"]["method"] = "telegram"
        config["notification"]["telegram"] = {
            "bot_token": os.environ["TELEGRAM_BOT_TOKEN"],
            "chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        }
    elif os.environ.get("DISCORD_WEBHOOK_URL"):
        config.setdefault("notification", {})
        config["notification"]["method"] = "discord"
        config["notification"]["discord"] = {
            "webhook_url": os.environ["DISCORD_WEBHOOK_URL"],
        }

    return config


def find_excel_files(data_dir: str = None) -> list:
    """Auto-discover Excel files in the data directory."""
    if data_dir is None:
        data_dir = str(PROJECT_ROOT / "data")
    patterns = ["*.xlsx", "*.xls"]
    files = []
    for p in patterns:
        files.extend(glob.glob(os.path.join(data_dir, p)))
    # Skip Excel temp/lock files (e.g. ~$Robotics_Companies_Careers.xlsx)
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    return sorted(files)


def run_agent(config: dict, excel_files: list = None, dry_run: bool = False):
    """Main agent execution."""
    logger = logging.getLogger("agent")
    start_time = datetime.now()
    logger.info(f"🤖 Job Search Agent starting at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # ---- 1. LOAD COMPANIES ----
    if not excel_files:
        excel_files = find_excel_files()
    if not excel_files:
        logger.error("No Excel files found! Place your company Excel files in the 'data/' folder.")
        logger.error("Or pass them via: python main.py --files companies.xlsx")
        sys.exit(1)

    logger.info(f"📁 Loading companies from {len(excel_files)} file(s): {excel_files}")
    companies = load_companies_from_multiple_files(excel_files)
    if not companies:
        logger.error("No companies loaded. Check your Excel files.")
        sys.exit(1)
    logger.info(f"✅ Loaded {len(companies)} unique companies")

    # ---- 2. INITIALIZE COMPONENTS ----
    scraper = JobScraper(config)
    matcher = SkillMatcher(config)
    db = JobDatabase()
    notifier = Notifier(config)

    # ---- 3. SCRAPE ALL COMPANIES ----
    all_jobs = []
    errors = 0
    for i, company in enumerate(companies, 1):
        name = company["name"]
        url = company["career_url"]
        logger.info(f"[{i}/{len(companies)}] Scraping: {name}")
        try:
            jobs = scraper.scrape_company(name, url)
            logger.info(f"  → Found {len(jobs)} job(s)")
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"  ✗ Error scraping {name}: {e}")
            errors += 1

    logger.info(f"\n📊 Scraping complete: {len(all_jobs)} total jobs from {len(companies)} companies ({errors} errors)")

    # ---- 4. FIRST PASS: Match skills on titles ----
    matched_jobs = matcher.filter_jobs(all_jobs)
    logger.info(f"🎯 First pass (titles): {len(matched_jobs)} jobs match your criteria")

    # ---- 5. SECOND PASS: Fetch descriptions for matched jobs & re-score ----
    if matched_jobs and config.get("scraping", {}).get("fetch_descriptions", True):
        logger.info(f"📄 Second pass: fetching descriptions for {len(matched_jobs)} matched jobs...")
        desc_fetched = 0
        desc_failed = 0
        for i, job in enumerate(matched_jobs, 1):
            if job.get("description", "").strip():
                # Already has description (e.g., from Lever)
                continue
            try:
                desc = scraper.fetch_job_description(job)
                if desc:
                    job["description"] = desc
                    desc_fetched += 1
                else:
                    desc_failed += 1
            except Exception as e:
                logger.debug(f"  Description fetch error: {e}")
                desc_failed += 1

            # Progress log every 20 jobs
            if i % 20 == 0:
                logger.info(f"  ... {i}/{len(matched_jobs)} descriptions processed")

        logger.info(f"📄 Descriptions: {desc_fetched} fetched, {desc_failed} unavailable")

        # Re-run matcher with descriptions to apply exclusion filters & boost scores
        matched_jobs = matcher.filter_jobs(matched_jobs)
        logger.info(f"🎯 Second pass (with descriptions): {len(matched_jobs)} jobs remain after filtering")

        # Flag jobs where description was not fetched (visa filtering may be incomplete)
        visa_unverified_count = 0
        for job in matched_jobs:
            if not job.get("description", "").strip():
                job["visa_unverified"] = True
                visa_unverified_count += 1
        if visa_unverified_count:
            logger.warning(f"⚠️  {visa_unverified_count} job(s) have unverified visa/sponsorship status (description unavailable)")

    # ---- 6. DEDUPLICATE (find new only) ----
    new_jobs = db.filter_new_jobs(matched_jobs)
    logger.info(f"🆕 New jobs (not seen before): {len(new_jobs)}")

    # ---- 6. LOG RUN ----
    db.log_run(
        companies_scraped=len(companies),
        total_found=len(all_jobs),
        new_matches=len(new_jobs),
        errors=errors,
    )

    # ---- 7. NOTIFY ----
    stats = db.get_stats()
    if new_jobs and not dry_run:
        success = notifier.send(new_jobs, stats)
        if success:
            db.mark_notified(new_jobs)
            logger.info("📬 Notification sent!")
        else:
            logger.warning("⚠️ Notification failed")
    elif new_jobs and dry_run:
        logger.info("🔇 Dry run — skipping notification")
        notifier._send_console(new_jobs, stats)
    else:
        logger.info("💤 No new matching jobs today")

    # ---- 8. WEEKLY SUMMARY (auto-triggered) ----
    if not dry_run and db.should_send_weekly_summary():
        logger.info("📅 Sending weekly summary...")
        summary = db.get_weekly_summary(weeks_back=1)
        if notifier.send_weekly_summary(summary):
            db.log_weekly_summary(
                summary["week_start"], summary["week_end"],
                len(summary["new_jobs"]), len(summary["active_apps"])
            )
            logger.info("📅 Weekly summary sent!")
        else:
            logger.warning("⚠️ Weekly summary failed")

    # ---- SUMMARY ----
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"\n{'='*50}")
    logger.info(f"  Run completed in {elapsed:.1f}s")
    logger.info(f"  Companies scraped: {len(companies)}")
    logger.info(f"  Total jobs found:  {len(all_jobs)}")
    logger.info(f"  Skill matches:     {len(matched_jobs)}")
    logger.info(f"  New matches:       {len(new_jobs)}")
    logger.info(f"  Errors:            {errors}")
    logger.info(f"  DB total tracked:  {stats['total_jobs_tracked']}")
    logger.info(f"{'='*50}\n")

    return {
        "companies": len(companies),
        "total_jobs": len(all_jobs),
        "matched": len(matched_jobs),
        "new": len(new_jobs),
        "errors": errors,
    }


def show_stats():
    db = JobDatabase()
    stats = db.get_stats()
    print("\n📊 Job Search Agent — Database Stats")
    print("─" * 40)
    for key, val in stats.items():
        print(f"  {key.replace('_', ' ').title()}: {val}")
    print()


def send_weekly_summary_now(config: dict):
    """Manually trigger weekly summary."""
    db = JobDatabase()
    notifier = Notifier(config)
    summary = db.get_weekly_summary(weeks_back=1)
    print(f"\n📅 Generating weekly summary ({summary['week_start']} to {summary['week_end']})...\n")
    notifier.send_weekly_summary(summary)
    db.log_weekly_summary(
        summary["week_start"], summary["week_end"],
        len(summary["new_jobs"]), len(summary["active_apps"])
    )


# ================================================================
#  APPLICATION TRACKING CLI
# ================================================================

def handle_apply(args):
    """Add a new application."""
    db = JobDatabase()
    app_id = db.add_application(
        company=args.company,
        title=args.title,
        url=args.url or "",
        location=args.location or "",
        resume_version=args.resume or "",
        notes=args.notes or "",
        salary_range=args.salary or "",
        contact_person=args.contact or "",
    )
    if app_id:
        print(f"\n✅ Application #{app_id} tracked!")
        print(f"   {args.title} @ {args.company}")
        print(f"   Status: applied")
        if args.url:
            print(f"   URL: {args.url}")
        if args.resume:
            print(f"   Resume: {args.resume}")
        print(f"\n   Update later with: python main.py update {app_id} --status screening")
    else:
        print(f"\n⚠️ Application already exists for: {args.title} @ {args.company}")


def handle_update(args):
    """Update an existing application."""
    db = JobDatabase()
    updates = {}
    if args.status:
        updates["status"] = args.status
    if args.notes:
        updates["notes"] = args.notes
    if args.interview_date:
        updates["interview_date"] = args.interview_date
    if args.response_date:
        updates["response_date"] = args.response_date
    if args.salary:
        updates["salary_range"] = args.salary
    if args.contact:
        updates["contact_person"] = args.contact
    if args.resume:
        updates["resume_version"] = args.resume

    if not updates:
        print("⚠️ No updates specified. Use --status, --notes, --interview-date, etc.")
        return

    success = db.update_application(args.app_id, **updates)
    if success:
        print(f"✅ Application #{args.app_id} updated: {updates}")
    else:
        print(f"❌ Failed to update application #{args.app_id}")


def handle_apps(args):
    """List applications with optional filters."""
    db = JobDatabase()
    apps = db.get_applications(status=args.status, company=args.company)

    if not apps:
        print("\n📝 No applications found matching your criteria.")
        print("   Add one with: python main.py apply --company X --title Y")
        return

    status_icons = {
        'applied': '📤', 'screening': '📞', 'interview': '🎯',
        'final_round': '🔥', 'offer': '🎉', 'accepted': '✅',
        'rejected': '❌', 'withdrawn': '↩️', 'closed': '🔒',
        'no_response': '😶',
    }

    print(f"\n📝 Applications ({len(apps)} total)")
    print("─" * 75)
    for a in apps:
        icon = status_icons.get(a['status'], '📋')
        applied = a.get('applied_date', '')[:10]
        print(f"  #{a['id']:3d} {icon} [{a['status']:12s}]  {a['title']}")
        print(f"       🏢 {a['company']}  📅 Applied: {applied}")
        if a.get('notes'):
            print(f"       📝 {a['notes'][:80]}")
        if a.get('interview_date'):
            print(f"       🎯 Interview: {a['interview_date']}")
        if a.get('salary_range'):
            print(f"       💰 Salary: {a['salary_range']}")
        if a.get('url'):
            print(f"       🔗 {a['url'][:80]}")
        print()


def handle_pipeline(args):
    """Show application pipeline summary."""
    db = JobDatabase()
    summary = db.get_application_summary()

    if summary["total_applications"] == 0:
        print("\n📊 No applications tracked yet.")
        print("   Start with: python main.py apply --company X --title Y")
        return

    print("\n" + "=" * 60)
    print("  📊 APPLICATION PIPELINE")
    print("=" * 60)

    # Visual pipeline
    status_icons = {
        'applied': '📤', 'screening': '📞', 'interview': '🎯',
        'final_round': '🔥', 'offer': '🎉', 'accepted': '✅',
        'rejected': '❌', 'withdrawn': '↩️', 'closed': '🔒',
        'no_response': '😶',
    }

    print(f"\n  Total: {summary['total_applications']}  |  "
          f"Response Rate: {summary['response_rate']}  |  "
          f"Avg Response: {summary['avg_days_to_response']} days\n")

    max_count = max((s['count'] for s in summary['by_status']), default=1)
    for s in summary['by_status']:
        icon = status_icons.get(s['status'], '📋')
        bar_len = int((s['count'] / max_count) * 30)
        bar = '█' * bar_len
        print(f"  {icon} {s['status']:14s} {bar} {s['count']}")

    # By company
    if summary['by_company']:
        print(f"\n  📋 By Company:")
        for c in summary['by_company'][:10]:
            statuses = c.get('statuses', '').replace(',', ', ')
            print(f"     {c['company']:30s} {c['count']} app(s)  [{statuses}]")

    # Recent activity
    if summary['recent_activity']:
        print(f"\n  🕐 Recent Activity (Last 7 Days):")
        for r in summary['recent_activity'][:8]:
            date = r.get('updated_date', '')[:10]
            print(f"     {date}  {r['title']} @ {r['company']} → {r['status']}")

    print("\n" + "=" * 60 + "\n")


def handle_delete_app(args):
    """Delete an application."""
    db = JobDatabase()
    if db.delete_application(args.app_id):
        print(f"✅ Application #{args.app_id} deleted.")
    else:
        print(f"❌ Application #{args.app_id} not found.")


def main():
    parser = argparse.ArgumentParser(
        description="🤖 Job Search Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                              # Daily scrape + notify
  python main.py --dry-run                    # Scrape without notifications
  python main.py --stats                      # Show database stats
  python main.py --weekly-summary             # Send weekly summary now
  python main.py apply --company NVIDIA --title "Data Analyst" --url https://...
  python main.py update 5 --status interview --notes "Phone screen went well"
  python main.py apps                         # List all applications
  python main.py apps --status interview      # Filter by status
  python main.py pipeline                     # Visual pipeline summary
  python main.py delete-app 5                 # Delete application #5
        """
    )

    # Use subparsers for application tracking commands
    subparsers = parser.add_subparsers(dest="command", help="Application tracking commands")

    # ---- APPLY: Track a new application ----
    apply_parser = subparsers.add_parser("apply", help="Track a new job application")
    apply_parser.add_argument("--company", "-c", required=True, help="Company name")
    apply_parser.add_argument("--title", "-t", required=True, help="Job title")
    apply_parser.add_argument("--url", "-u", help="Job posting URL")
    apply_parser.add_argument("--location", "-l", help="Job location")
    apply_parser.add_argument("--resume", "-r", help="Resume version used (e.g., 'robotics_v2')")
    apply_parser.add_argument("--notes", "-n", help="Additional notes")
    apply_parser.add_argument("--salary", help="Expected salary range")
    apply_parser.add_argument("--contact", help="Contact person name/email")

    # ---- UPDATE: Update application status ----
    update_parser = subparsers.add_parser("update", help="Update an application")
    update_parser.add_argument("app_id", type=int, help="Application ID number")
    update_parser.add_argument("--status", "-s",
                               choices=JobDatabase.APPLICATION_STATUSES,
                               help="New status")
    update_parser.add_argument("--notes", "-n", help="Update notes")
    update_parser.add_argument("--interview-date", help="Interview date (YYYY-MM-DD)")
    update_parser.add_argument("--response-date", help="Response date (YYYY-MM-DD)")
    update_parser.add_argument("--salary", help="Salary range offered")
    update_parser.add_argument("--contact", help="Contact person")
    update_parser.add_argument("--resume", help="Resume version")

    # ---- APPS: List applications ----
    apps_parser = subparsers.add_parser("apps", help="List tracked applications")
    apps_parser.add_argument("--status", "-s", help="Filter by status")
    apps_parser.add_argument("--company", "-c", help="Filter by company name")

    # ---- PIPELINE: Visual pipeline ----
    subparsers.add_parser("pipeline", help="Show application pipeline summary")

    # ---- DELETE-APP: Remove application ----
    del_parser = subparsers.add_parser("delete-app", help="Delete an application")
    del_parser.add_argument("app_id", type=int, help="Application ID to delete")

    # ---- Main flags (for scraping mode) ----
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--files", nargs="+", help="Excel file(s) with companies")
    parser.add_argument("--dry-run", action="store_true", help="Scrape & match without notifying")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--weekly-summary", action="store_true", help="Send weekly summary now")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()
    setup_logging(args.verbose if hasattr(args, 'verbose') else False)

    # ---- Route to appropriate handler ----
    if hasattr(args, 'command') and args.command:
        if args.command == "apply":
            handle_apply(args)
        elif args.command == "update":
            handle_update(args)
        elif args.command == "apps":
            handle_apps(args)
        elif args.command == "pipeline":
            handle_pipeline(args)
        elif args.command == "delete-app":
            handle_delete_app(args)
        return

    if args.stats:
        show_stats()
        return

    if args.weekly_summary:
        config = load_config(args.config)
        send_weekly_summary_now(config)
        return

    config = load_config(args.config)
    result = run_agent(config, args.files, args.dry_run)

    # Exit with error code if there were issues
    if result["errors"] > result["companies"] * 0.5:
        sys.exit(1)


if __name__ == "__main__":
    main()
