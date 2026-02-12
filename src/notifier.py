"""
Notification system - sends job alerts via Email, Telegram, Discord, or Console.
"""

import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class Notifier:
    """Send job match notifications through configured channel."""

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
        print("\n" + "=" * 70)
        print(f"  🤖 JOB SEARCH AGENT — {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
        print(f"  Found {len(jobs)} NEW matching job(s)")
        print("=" * 70)

        for i, job in enumerate(jobs, 1):
            score = job.get('relevance_score', 0)
            stars = '⭐' * min(int(score / 5), 5)
            print(f"\n  [{i}] {job['title']}")
            print(f"      🏢 {job['company']}  |  📍 {job.get('location', 'N/A')}")
            print(f"      🏷️  {job.get('department', 'N/A')}")
            print(f"      📊 Score: {score} {stars}")
            kw = job.get('matched_keywords', [])
            if kw:
                print(f"      🔑 Matched: {', '.join(kw[:6])}")
            print(f"      🔗 {job.get('url', 'N/A')}")

        print(f"\n{'─' * 70}")
        print(f"  📈 Stats: {stats.get('total_jobs_tracked', 0)} total tracked | "
              f"{stats.get('unique_companies', 0)} companies | "
              f"Run #{stats.get('total_runs', 0)}")
        print("=" * 70 + "\n")
        return True

    # ==================== EMAIL ====================
    def _send_email(self, jobs: List[Dict], stats: Dict) -> bool:
        email_cfg = self.config.get("email", {})
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"🤖 {len(jobs)} New Job Match{'es' if len(jobs) > 1 else ''} — {datetime.now().strftime('%b %d')}"
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
        rows = ""
        for job in jobs:
            score = job.get('relevance_score', 0)
            keywords = ', '.join(job.get('matched_keywords', [])[:5])
            color = '#27ae60' if score >= 20 else '#f39c12' if score >= 10 else '#95a5a6'
            rows += f"""
            <tr>
                <td style="padding:12px;border-bottom:1px solid #eee;">
                    <strong><a href="{job.get('url','#')}" style="color:#2c3e50;text-decoration:none;">
                        {job['title']}
                    </a></strong><br>
                    <span style="color:#7f8c8d;">🏢 {job['company']} &nbsp;|&nbsp; 📍 {job.get('location','N/A')}</span><br>
                    <span style="color:#95a5a6;font-size:12px;">🔑 {keywords}</span>
                </td>
                <td style="padding:12px;border-bottom:1px solid #eee;text-align:center;">
                    <span style="background:{color};color:white;padding:4px 10px;border-radius:12px;font-size:13px;">
                        {score}
                    </span>
                </td>
            </tr>"""

        return f"""
        <div style="font-family:Arial,sans-serif;max-width:650px;margin:0 auto;">
            <div style="background:#2c3e50;color:white;padding:20px;border-radius:8px 8px 0 0;">
                <h2 style="margin:0;">🤖 Job Search Agent</h2>
                <p style="margin:5px 0 0;opacity:0.8;">{len(jobs)} new matching job(s) found — {datetime.now().strftime('%B %d, %Y')}</p>
            </div>
            <table style="width:100%;border-collapse:collapse;background:white;">
                <tr style="background:#f8f9fa;">
                    <th style="padding:10px;text-align:left;">Job</th>
                    <th style="padding:10px;text-align:center;width:80px;">Score</th>
                </tr>
                {rows}
            </table>
            <div style="background:#f8f9fa;padding:15px;border-radius:0 0 8px 8px;font-size:12px;color:#95a5a6;">
                📊 {stats.get('total_jobs_tracked',0)} jobs tracked across {stats.get('unique_companies',0)} companies
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
        header = f"🤖 *Job Alert — {datetime.now().strftime('%b %d')}*\n"
        header += f"Found *{len(jobs)}* new match{'es' if len(jobs)>1 else ''}!\n\n"

        messages = [header]
        current = header
        for i, job in enumerate(jobs, 1):
            entry = (
                f"*{i}. {self._tg_escape(job['title'])}*\n"
                f"🏢 {self._tg_escape(job['company'])}  📍 {self._tg_escape(job.get('location','N/A'))}\n"
                f"📊 Score: {job.get('relevance_score',0)}\n"
                f"[Apply →]({job.get('url','#')})\n\n"
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
                    {"name": "🏢 Company", "value": job["company"], "inline": True},
                    {"name": "📍 Location", "value": job.get("location", "N/A"), "inline": True},
                    {"name": "📊 Score", "value": str(score), "inline": True},
                ],
            })

        payload = {
            "content": f"🤖 **Job Alert** — {len(jobs)} new match{'es' if len(jobs)>1 else ''}!",
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
        print(f"  📅 WEEKLY SUMMARY — {s['week_start']} to {s['week_end']}")
        print("=" * 70)

        # Run stats
        print(f"\n  🔄 Runs this week: {runs.get('runs', 0)}")
        print(f"  📊 Total scraped: {runs.get('total_scraped', 0)} jobs")
        print(f"  🆕 New matches: {runs.get('total_new', 0)}")
        print(f"  ⚠️  Errors: {runs.get('total_errors', 0)}")

        # New jobs by company
        if by_company:
            print(f"\n  📋 New Jobs by Company ({len(new_jobs)} total):")
            for row in by_company[:15]:
                print(f"     {row['company']:35s} {row['count']} new")

        # Top scoring jobs
        if top:
            print(f"\n  ⭐ Top Scoring Active Jobs:")
            for j in top[:10]:
                print(f"     [{j['relevance_score']:.0f}] {j['title']}")
                print(f"          🏢 {j['company']}  📍 {j.get('location', 'N/A')}")

        # Stale jobs (disappeared)
        if stale:
            print(f"\n  ⏰ Possibly Closed ({len(stale)} jobs not seen this week):")
            for j in stale[:5]:
                print(f"     {j['title']} @ {j['company']} (last seen: {j['last_seen'][:10]})")

        # Application pipeline
        if active_apps:
            print(f"\n  📝 Active Applications ({len(active_apps)}):")
            for a in active_apps:
                status_icon = {
                    'applied': '📤', 'screening': '📞', 'interview': '🎯',
                    'final_round': '🔥', 'offer': '🎉', 'accepted': '✅',
                }.get(a['status'], '📋')
                print(f"     {status_icon} {a['title']} @ {a['company']} [{a['status']}]")
        else:
            print(f"\n  📝 No active applications tracked yet")
            print(f"     Tip: Use 'python main.py apply --company X --title Y' to track")

        print("\n" + "=" * 70 + "\n")
        return True

    def _send_weekly_email(self, s: Dict) -> bool:
        email_cfg = self.config.get("email", {})
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"📅 Weekly Job Search Summary — {s['week_start']} to {s['week_end']}"
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
                    <span style="color:#7f8c8d;">🏢 {j['company']} | 📍 {j.get('location','N/A')}</span>
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
                <h2 style="margin:0;">📅 Weekly Job Search Summary</h2>
                <p style="margin:5px 0 0;opacity:0.8;">{s['week_start']} — {s['week_end']}</p>
            </div>

            <div style="background:#ecf0f1;padding:15px;display:flex;justify-content:space-around;text-align:center;">
                <div><strong style="font-size:24px;color:#2c3e50;">{len(new_jobs)}</strong><br><span style="color:#7f8c8d;font-size:12px;">New Jobs</span></div>
                <div><strong style="font-size:24px;color:#2c3e50;">{runs.get('runs', 0)}</strong><br><span style="color:#7f8c8d;font-size:12px;">Runs</span></div>
                <div><strong style="font-size:24px;color:#2c3e50;">{len(active_apps)}</strong><br><span style="color:#7f8c8d;font-size:12px;">Active Apps</span></div>
                <div><strong style="font-size:24px;color:#2c3e50;">{runs.get('total_errors', 0)}</strong><br><span style="color:#7f8c8d;font-size:12px;">Errors</span></div>
            </div>

            <div style="background:white;padding:15px;">
                <h3 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:5px;">⭐ Top Scoring Jobs</h3>
                <table style="width:100%;border-collapse:collapse;">{top_rows}</table>
            </div>

            <div style="background:#f8f9fa;padding:15px;">
                <h3 style="color:#2c3e50;border-bottom:2px solid #27ae60;padding-bottom:5px;">📋 New Jobs by Company</h3>
                <table style="width:100%;border-collapse:collapse;">{company_rows}</table>
            </div>

            <div style="background:white;padding:15px;">
                <h3 style="color:#2c3e50;border-bottom:2px solid #9b59b6;padding-bottom:5px;">📝 Application Pipeline</h3>
                {'<table style="width:100%;border-collapse:collapse;"><tr style="background:#f8f9fa;"><th style="padding:6px;text-align:left;">Job</th><th style="padding:6px;text-align:center;">Status</th><th style="padding:6px;text-align:center;">Applied</th></tr>' + app_rows + '</table>' if app_rows else '<p style="color:#95a5a6;">No applications tracked yet. Use: python main.py apply --company X --title Y</p>'}
            </div>

            <div style="background:#2c3e50;color:white;padding:12px;border-radius:0 0 8px 8px;font-size:12px;text-align:center;">
                🤖 Job Search Agent — Automated Weekly Digest
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

        msg = f"📅 *Weekly Summary* — {s['week_start']} to {s['week_end']}\n\n"
        msg += f"🆕 New jobs: *{len(new_jobs)}*\n"
        msg += f"🔄 Runs: *{runs.get('runs', 0)}*\n"
        msg += f"📝 Active applications: *{len(active_apps)}*\n\n"

        if top:
            msg += "⭐ *Top Jobs:*\n"
            for j in top[:7]:
                msg += f"  \\[{j['relevance_score']:.0f}\\] {self._tg_escape(j['title'])} @ {self._tg_escape(j['company'])}\n"

        if active_apps:
            msg += "\n📝 *Application Pipeline:*\n"
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
            "content": f"📅 **Weekly Summary** — {s['week_start']} to {s['week_end']}",
            "embeds": [{
                "color": 0x3498db,
                "fields": [
                    {"name": "🆕 New Jobs", "value": str(len(new_jobs)), "inline": True},
                    {"name": "🔄 Runs", "value": str(runs.get('runs', 0)), "inline": True},
                    {"name": "📝 Active Apps", "value": str(len(active_apps)), "inline": True},
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
