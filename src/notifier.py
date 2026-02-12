"""
Notification system - sends job alerts via Email, Telegram, Discord, or Console.
"""

import json
import logging
import smtplib
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class Notifier:
    """Send job match notifications through configured channel."""

    # Platform display names and icons for grouping
    PLATFORM_LABELS = {
        "greenhouse": ("\U0001f33f", "Greenhouse"),
        "lever": ("\U0001f527", "Lever"),
        "workday": ("\U0001f4d8", "Workday"),
        "smartrecruiters": ("\U0001f4cb", "SmartRecruiters"),
        "ashby": ("\U0001f537", "Ashby"),
        "generic": ("\U0001f310", "Other / Generic"),
    }

    PLATFORM_COLORS = {
        "greenhouse": ("#27ae60", "\U0001f33f Greenhouse"),
        "lever": ("#8e44ad", "\U0001f527 Lever"),
        "workday": ("#2980b9", "\U0001f4d8 Workday"),
        "smartrecruiters": ("#f39c12", "\U0001f4cb SmartRecruiters"),
        "ashby": ("#3498db", "\U0001f537 Ashby"),
        "generic": ("#7f8c8d", "\U0001f310 Other"),
    }

    PLATFORM_ORDER = ["greenhouse", "lever", "ashby", "workday", "smartrecruiters", "generic"]

    def __init__(self, config: dict):
        notif_cfg = config.get("notification", {})
        self.method = notif_cfg.get("method", "console")
        self.config = notif_cfg

    def send(self, new_jobs: List[Dict], stats: Dict) -> bool:
        """Send notification with new job matches."""
        if not new_jobs:
            logger.info("No new jobs to notify about.")
            return True

        if self.method == "email":
            return self._send_email(new_jobs, stats)
        elif self.method == "telegram":
            return self._send_telegram(new_jobs, stats)
        elif self.method == "discord":
            return self._send_discord(new_jobs, stats)
        else:
            return self._send_console(new_jobs, stats)

    # ==================== CONSOLE ====================
    def _send_console(self, jobs: List[Dict], stats: Dict) -> bool:
        print("\n" + "=" * 120)
        print(f"  \U0001f916 JOB SEARCH AGENT \u2014 {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
        print(f"  Found {len(jobs)} NEW matching job(s)")
        print("=" * 120)

        # Group jobs by platform
        grouped = defaultdict(list)
        for job in jobs:
            grouped[job.get("platform", "generic")].append(job)

        # Display each platform group as a table
        for platform in self.PLATFORM_ORDER:
            pjobs = grouped.get(platform)
            if not pjobs:
                continue
            icon, label = self.PLATFORM_LABELS.get(platform, ("\U0001f310", platform.title()))
            print(f"\n  {icon} {label.upper()} ({len(pjobs)} job{'s' if len(pjobs) != 1 else ''})")
            print(f"  {'\u2500'*116}")
            print(f"  {'No.':<5} {'Job ID':<16} {'Title':<36} {'Company':<18} {'Location':<16} {'Score':<6} {'Visa':<6} {'Link'}")
            print(f"  {'\u2500'*116}")
            for i, job in enumerate(pjobs, 1):
                job_id = (job.get('job_id') or '\u2014')[:14]
                title = (job.get('title') or 'N/A')[:34]
                company = (job.get('company') or 'N/A')[:16]
                location = (job.get('location') or 'N/A')[:14]
                score = job.get('relevance_score', 0)
                visa = '\u26a0\ufe0f' if job.get('visa_unverified') else '\u2705'
                link = job.get('url', '')[:50] or '\u2014'
                print(f"  {i:<5} {job_id:<16} {title:<36} {company:<18} {location:<16} {score:<6} {visa:<6} {link}")

        print(f"\n  {'\u2500' * 120}")
        print(f"  \u26a0\ufe0f  = Visa/sponsorship status unverified (description unavailable)")
        print(f"  \u2705  = Description fetched, visa keywords checked")
        print(f"\n  \U0001f4c8 Stats: {stats.get('total_jobs_tracked', 0)} total tracked | "
              f"{stats.get('unique_companies', 0)} companies | "
              f"Run #{stats.get('total_runs', 0)}")
        print("=" * 120 + "\n")
        return True

    # ==================== EMAIL ====================
    def _send_email(self, jobs: List[Dict], stats: Dict) -> bool:
        email_cfg = self.config.get("email", {})
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"\U0001f916 {len(jobs)} New Job Match{'es' if len(jobs) > 1 else ''} \u2014 {datetime.now().strftime('%b %d')}"
            msg["From"] = email_cfg["sender_email"]
            msg["To"] = email_cfg["recipient_email"]

            html = self._build_email_html(jobs, stats)
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as server:
                server.starttls()
                server.login(email_cfg["sender_email"], email_cfg["sender_password"])
                server.sendmail(email_cfg["sender_email"], email_cfg["recipient_email"], msg.as_string())

            logger.info(f"Email sent to {email_cfg['recipient_email']}")
            return True
        except Exception as e:
            logger.error(f"Email failed: {e}")
            return False

    def _build_email_html(self, jobs: List[Dict], stats: Dict) -> str:
        # Group jobs by platform
        grouped = defaultdict(list)
        for job in jobs:
            grouped[job.get("platform", "generic")].append(job)

        # Build HTML sections per platform
        platform_sections = ""
        for platform in self.PLATFORM_ORDER:
            pjobs = grouped.get(platform)
            if not pjobs:
                continue
            border_color, label = self.PLATFORM_COLORS.get(platform, ("#7f8c8d", platform.title()))

            rows = ""
            for job in pjobs:
                score = job.get('relevance_score', 0)
                score_color = '#27ae60' if score >= 20 else '#f39c12' if score >= 10 else '#95a5a6'
                visa_icon = '<span style="color:#e74c3c;" title="Visa status unverified">\u26a0\ufe0f</span>' if job.get('visa_unverified') else '<span style="color:#27ae60;" title="Visa keywords checked">\u2705</span>'
                job_id = job.get('job_id', '') or '\u2014'
                job_url = job.get('url', '')
                title_cell = f'<a href="{job_url}" style="color:#2c3e50;text-decoration:none;">{job["title"]}</a>' if job_url else job['title']

                rows += f"""
                <tr>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;font-family:monospace;font-size:12px;color:#7f8c8d;">{job_id}</td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;"><strong>{title_cell}</strong></td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;color:#7f8c8d;">{job['company']}</td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;color:#7f8c8d;">{job.get('location', 'N/A')}</td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:center;">
                        <span style="background:{score_color};color:white;padding:2px 7px;border-radius:10px;font-size:12px;">{score}</span>
                    </td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:center;">{visa_icon}</td>
                </tr>"""

            platform_sections += f"""
            <div style="margin-top:10px;">
                <div style="background:{border_color};color:white;padding:8px 15px;font-size:14px;font-weight:bold;border-radius:4px 4px 0 0;">
                    {label} ({len(pjobs)} job{'s' if len(pjobs) != 1 else ''})
                </div>
                <table style="width:100%;border-collapse:collapse;background:white;">
                    <tr style="background:#f8f9fa;">
                        <th style="padding:6px 8px;text-align:left;font-size:12px;width:100px;">Job ID</th>
                        <th style="padding:6px 8px;text-align:left;font-size:12px;">Title</th>
                        <th style="padding:6px 8px;text-align:left;font-size:12px;">Company</th>
                        <th style="padding:6px 8px;text-align:left;font-size:12px;">Location</th>
                        <th style="padding:6px 8px;text-align:center;font-size:12px;width:50px;">Score</th>
                        <th style="padding:6px 8px;text-align:center;font-size:12px;width:40px;">Visa</th>
                    </tr>
                    {rows}
                </table>
            </div>"""

        return f"""
        <div style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;">
            <div style="background:#2c3e50;color:white;padding:20px;border-radius:8px 8px 0 0;">
                <h2 style="margin:0;">\U0001f916 Job Search Agent</h2>
                <p style="margin:5px 0 0;opacity:0.8;">{len(jobs)} new matching job(s) found \u2014 {datetime.now().strftime('%B %d, %Y')}</p>
            </div>
            {platform_sections}
            <div style="background:#f0f0f0;padding:10px 15px;font-size:11px;color:#7f8c8d;margin-top:5px;">
                \u26a0\ufe0f = Visa/sponsorship status unverified &nbsp;|&nbsp; \u2705 = Description fetched, visa keywords checked
            </div>
            <div style="background:#f8f9fa;padding:15px;border-radius:0 0 8px 8px;font-size:12px;color:#95a5a6;">
                \U0001f4ca {stats.get('total_jobs_tracked',0)} jobs tracked across {stats.get('unique_companies',0)} companies
            </div>
        </div>"""

    # ==================== TELEGRAM ====================
    def _send_telegram(self, jobs: List[Dict], stats: Dict) -> bool:
        tg_cfg = self.config.get("telegram", {})
        bot_token = tg_cfg.get("bot_token", "")
        chat_id = tg_cfg.get("chat_id", "")

        if not bot_token or not chat_id:
            logger.error("Telegram bot_token and chat_id required")
            return False

        # Build message (Telegram has 4096 char limit)
        header = f"\U0001f916 *Job Alert \u2014 {datetime.now().strftime('%b %d')}*\n"
        header += f"Found *{len(jobs)}* new match{'es' if len(jobs)>1 else ''}!\n\n"

        messages = [header]
        current = header
        for i, job in enumerate(jobs, 1):
            entry = (
                f"*{i}. {self._tg_escape(job['title'])}*\n"
                f"\U0001f3e2 {self._tg_escape(job['company'])}  \U0001f4cd {self._tg_escape(job.get('location','N/A'))}\n"
                f"\U0001f4ca Score: {job.get('relevance_score',0)}\n"
                f"[Apply \u2192]({job.get('url','#')})\n\n"
            )
            if len(current) + len(entry) > 3800:
                messages.append(current)
                current = entry
            else:
                current += entry
        if current != header:
            messages.append(current)

        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            for msg_text in messages:
                resp = requests.post(url, json={
                    "chat_id": chat_id,
                    "text": msg_text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
                resp.raise_for_status()
            logger.info("Telegram notification sent")
            return True
        except Exception as e:
            logger.error(f"Telegram failed: {e}")
            return False

    @staticmethod
    def _tg_escape(text: str) -> str:
        """Escape special chars for Telegram Markdown."""
        for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
            text = text.replace(ch, f'\\{ch}')
        return text

    # ==================== DISCORD ====================
    def _send_discord(self, jobs: List[Dict], stats: Dict) -> bool:
        dc_cfg = self.config.get("discord", {})
        webhook_url = dc_cfg.get("webhook_url", "")

        if not webhook_url:
            logger.error("Discord webhook_url required")
            return False

        embeds = []
        for job in jobs[:10]:  # Discord limit
            score = job.get('relevance_score', 0)
            color = 0x27ae60 if score >= 20 else 0xf39c12 if score >= 10 else 0x95a5a6
            embeds.append({
                "title": job["title"],
                "url": job.get("url", ""),
                "color": color,
                "fields": [
                    {"name": "\U0001f3e2 Company", "value": job["company"], "inline": True},
                    {"name": "\U0001f4cd Location", "value": job.get("location", "N/A"), "inline": True},
                    {"name": "\U0001f4ca Score", "value": str(score), "inline": True},
                ],
            })

        payload = {
            "content": f"\U0001f916 **Job Alert** \u2014 {len(jobs)} new match{'es' if len(jobs)>1 else ''}!",
            "embeds": embeds[:10],
        }

        try:
            resp = requests.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Discord notification sent")
            return True
        except Exception as e:
            logger.error(f"Discord failed: {e}")
            return False

    # ================================================================
    #  WEEKLY SUMMARY NOTIFICATIONS
    # ================================================================

    def send_weekly_summary(self, summary: Dict) -> bool:
        """Send weekly summary through configured channel."""
        if self.method == "email":
            return self._send_weekly_email(summary)
        elif self.method == "telegram":
            return self._send_weekly_telegram(summary)
        elif self.method == "discord":
            return self._send_weekly_discord(summary)
        else:
            return self._send_weekly_console(summary)

    def _send_weekly_console(self, s: Dict) -> bool:
        new_jobs = s.get("new_jobs", [])
        by_company = s.get("jobs_by_company", [])
        active_apps = s.get("active_apps", [])
        stale = s.get("stale_jobs", [])
        top = s.get("top_jobs", [])
        runs = s.get("run_stats", {})

        print("\n" + "=" * 70)
        print(f"  \U0001f4c5 WEEKLY SUMMARY \u2014 {s['week_start']} to {s['week_end']}")
        print("=" * 70)

        # Run stats
        print(f"\n  \U0001f504 Runs this week: {runs.get('runs', 0)}")
        print(f"  \U0001f4ca Total scraped: {runs.get('total_scraped', 0)} jobs")
        print(f"  \U0001f195 New matches: {runs.get('total_new', 0)}")
        print(f"  \u26a0\ufe0f  Errors: {runs.get('total_errors', 0)}")

        # New jobs by company
        if by_company:
            print(f"\n  \U0001f4cb New Jobs by Company ({len(new_jobs)} total):")
            for row in by_company[:15]:
                print(f"     {row['company']:35s} {row['count']} new")

        # Top scoring jobs
        if top:
            print(f"\n  \u2b50 Top Scoring Active Jobs:")
            for j in top[:10]:
                print(f"     [{j['relevance_score']:.0f}] {j['title']}")
                print(f"          \U0001f3e2 {j['company']}  \U0001f4cd {j.get('location', 'N/A')}")

        # Stale jobs (disappeared)
        if stale:
            print(f"\n  \u23f0 Possibly Closed ({len(stale)} jobs not seen this week):")
            for j in stale[:5]:
                print(f"     {j['title']} @ {j['company']} (last seen: {j['last_seen'][:10]})")

        # Application pipeline
        if active_apps:
            print(f"\n  \U0001f4dd Active Applications ({len(active_apps)}):")
            for a in active_apps:
                status_icon = {
                    'applied': '\U0001f4e4', 'screening': '\U0001f4de', 'interview': '\U0001f3af',
                    'final_round': '\U0001f525', 'offer': '\U0001f389', 'accepted': '\u2705',
                }.get(a['status'], '\U0001f4cb')
                print(f"     {status_icon} {a['title']} @ {a['company']} [{a['status']}]")
        else:
            print(f"\n  \U0001f4dd No active applications tracked yet")
            print(f"     Tip: Use 'python main.py apply --company X --title Y' to track")

        print("\n" + "=" * 70 + "\n")
        return True

    def _send_weekly_email(self, s: Dict) -> bool:
        email_cfg = self.config.get("email", {})
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"\U0001f4c5 Weekly Job Search Summary \u2014 {s['week_start']} to {s['week_end']}"
            msg["From"] = email_cfg["sender_email"]
            msg["To"] = email_cfg["recipient_email"]

            html = self._build_weekly_html(s)
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as server:
                server.starttls()
                server.login(email_cfg["sender_email"], email_cfg["sender_password"])
                server.sendmail(email_cfg["sender_email"], email_cfg["recipient_email"], msg.as_string())

            logger.info("Weekly summary email sent")
            return True
        except Exception as e:
            logger.error(f"Weekly email failed: {e}")
            return False

    def _build_weekly_html(self, s: Dict) -> str:
        new_jobs = s.get("new_jobs", [])
        by_company = s.get("jobs_by_company", [])
        active_apps = s.get("active_apps", [])
        top = s.get("top_jobs", [])
        runs = s.get("run_stats", {})

        # Company breakdown rows
        company_rows = ""
        for row in by_company[:15]:
            company_rows += f"<tr><td style='padding:6px 12px;'>{row['company']}</td><td style='padding:6px 12px;text-align:center;'><strong>{row['count']}</strong></td></tr>"

        # Top jobs rows
        top_rows = ""
        for j in top[:10]:
            score = j.get('relevance_score', 0)
            color = '#27ae60' if score >= 20 else '#f39c12' if score >= 10 else '#95a5a6'
            top_rows += f"""<tr>
                <td style='padding:8px 12px;border-bottom:1px solid #eee;'>
                    <a href="{j.get('url','#')}" style="color:#2c3e50;text-decoration:none;"><strong>{j['title']}</strong></a><br>
                    <span style="color:#7f8c8d;">\U0001f3e2 {j['company']} | \U0001f4cd {j.get('location','N/A')}</span>
                </td>
                <td style='padding:8px;text-align:center;border-bottom:1px solid #eee;'>
                    <span style="background:{color};color:white;padding:3px 8px;border-radius:10px;">{score:.0f}</span>
                </td></tr>"""

        # Application pipeline rows
        app_rows = ""
        status_colors = {
            'applied': '#3498db', 'screening': '#9b59b6', 'interview': '#f39c12',
            'final_round': '#e67e22', 'offer': '#27ae60', 'accepted': '#2ecc71',
        }
        for a in active_apps[:10]:
            col = status_colors.get(a['status'], '#95a5a6')
            app_rows += f"""<tr>
                <td style='padding:6px 12px;border-bottom:1px solid #eee;'>{a['title']}<br><span style="color:#7f8c8d;">{a['company']}</span></td>
                <td style='padding:6px;text-align:center;border-bottom:1px solid #eee;'>
                    <span style="background:{col};color:white;padding:2px 8px;border-radius:10px;font-size:12px;">{a['status']}</span>
                </td>
                <td style='padding:6px;text-align:center;border-bottom:1px solid #eee;color:#7f8c8d;font-size:12px;'>{a.get('applied_date','')[:10]}</td>
            </tr>"""

        return f"""
        <div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;">
            <div style="background:#2c3e50;color:white;padding:20px;border-radius:8px 8px 0 0;">
                <h2 style="margin:0;">\U0001f4c5 Weekly Job Search Summary</h2>
                <p style="margin:5px 0 0;opacity:0.8;">{s['week_start']} \u2014 {s['week_end']}</p>
            </div>

            <div style="background:#ecf0f1;padding:15px;display:flex;justify-content:space-around;text-align:center;">
                <div><strong style="font-size:24px;color:#2c3e50;">{len(new_jobs)}</strong><br><span style="color:#7f8c8d;font-size:12px;">New Jobs</span></div>
                <div><strong style="font-size:24px;color:#2c3e50;">{runs.get('runs', 0)}</strong><br><span style="color:#7f8c8d;font-size:12px;">Runs</span></div>
                <div><strong style="font-size:24px;color:#2c3e50;">{len(active_apps)}</strong><br><span style="color:#7f8c8d;font-size:12px;">Active Apps</span></div>
                <div><strong style="font-size:24px;color:#2c3e50;">{runs.get('total_errors', 0)}</strong><br><span style="color:#7f8c8d;font-size:12px;">Errors</span></div>
            </div>

            <div style="background:white;padding:15px;">
                <h3 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:5px;">\u2b50 Top Scoring Jobs</h3>
                <table style="width:100%;border-collapse:collapse;">{top_rows}</table>
            </div>

            <div style="background:#f8f9fa;padding:15px;">
                <h3 style="color:#2c3e50;border-bottom:2px solid #27ae60;padding-bottom:5px;">\U0001f4cb New Jobs by Company</h3>
                <table style="width:100%;border-collapse:collapse;">{company_rows}</table>
            </div>

            <div style="background:white;padding:15px;">
                <h3 style="color:#2c3e50;border-bottom:2px solid #9b59b6;padding-bottom:5px;">\U0001f4dd Application Pipeline</h3>
                {'<table style="width:100%;border-collapse:collapse;"><tr style="background:#f8f9fa;"><th style="padding:6px;text-align:left;">Job</th><th style="padding:6px;text-align:center;">Status</th><th style="padding:6px;text-align:center;">Applied</th></tr>' + app_rows + '</table>' if app_rows else '<p style="color:#95a5a6;">No applications tracked yet. Use: python main.py apply --company X --title Y</p>'}
            </div>

            <div style="background:#2c3e50;color:white;padding:12px;border-radius:0 0 8px 8px;font-size:12px;text-align:center;">
                \U0001f916 Job Search Agent \u2014 Automated Weekly Digest
            </div>
        </div>"""

    def _send_weekly_telegram(self, s: Dict) -> bool:
        tg_cfg = self.config.get("telegram", {})
        bot_token = tg_cfg.get("bot_token", "")
        chat_id = tg_cfg.get("chat_id", "")

        new_jobs = s.get("new_jobs", [])
        active_apps = s.get("active_apps", [])
        top = s.get("top_jobs", [])
        runs = s.get("run_stats", {})

        msg = f"\U0001f4c5 *Weekly Summary* \u2014 {s['week_start']} to {s['week_end']}\n\n"
        msg += f"\U0001f195 New jobs: *{len(new_jobs)}*\n"
        msg += f"\U0001f504 Runs: *{runs.get('runs', 0)}*\n"
        msg += f"\U0001f4dd Active applications: *{len(active_apps)}*\n\n"

        if top:
            msg += "\u2b50 *Top Jobs:*\n"
            for j in top[:7]:
                msg += f"  \\[{j['relevance_score']:.0f}\\] {self._tg_escape(j['title'])} @ {self._tg_escape(j['company'])}\n"

        if active_apps:
            msg += "\n\U0001f4dd *Application Pipeline:*\n"
            for a in active_apps[:7]:
                msg += f"  {self._tg_escape(a['title'])} @ {self._tg_escape(a['company'])} \\[{a['status']}\\]\n"

        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": chat_id, "text": msg,
                "parse_mode": "Markdown", "disable_web_page_preview": True,
            })
            resp.raise_for_status()
            logger.info("Weekly Telegram summary sent")
            return True
        except Exception as e:
            logger.error(f"Weekly Telegram failed: {e}")
            return False

    def _send_weekly_discord(self, s: Dict) -> bool:
        dc_cfg = self.config.get("discord", {})
        webhook_url = dc_cfg.get("webhook_url", "")
        new_jobs = s.get("new_jobs", [])
        active_apps = s.get("active_apps", [])
        runs = s.get("run_stats", {})

        payload = {
            "content": f"\U0001f4c5 **Weekly Summary** \u2014 {s['week_start']} to {s['week_end']}",
            "embeds": [{
                "color": 0x3498db,
                "fields": [
                    {"name": "\U0001f195 New Jobs", "value": str(len(new_jobs)), "inline": True},
                    {"name": "\U0001f504 Runs", "value": str(runs.get('runs', 0)), "inline": True},
                    {"name": "\U0001f4dd Active Apps", "value": str(len(active_apps)), "inline": True},
                ],
            }],
        }

        try:
            resp = requests.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Weekly Discord summary sent")
            return True
        except Exception as e:
            logger.error(f"Weekly Discord failed: {e}")
            return False
