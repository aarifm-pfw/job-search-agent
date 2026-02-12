"""
Job database - SQLite-based storage for deduplication, history tracking,
weekly summaries, and application tracking.
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"


class JobDatabase:
    """Track seen jobs, weekly summaries, and application status."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_key TEXT PRIMARY KEY,
                    company TEXT,
                    title TEXT,
                    location TEXT,
                    url TEXT,
                    department TEXT,
                    relevance_score REAL,
                    matched_keywords TEXT,
                    platform TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    notified INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_time TEXT,
                    companies_scraped INTEGER,
                    total_jobs_found INTEGER,
                    new_matches INTEGER,
                    errors INTEGER
                )
            """)
            # ---- APPLICATION TRACKING TABLE ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_key TEXT,
                    company TEXT,
                    title TEXT,
                    location TEXT,
                    url TEXT,
                    status TEXT DEFAULT 'applied',
                    applied_date TEXT,
                    updated_date TEXT,
                    resume_version TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    interview_date TEXT DEFAULT '',
                    response_date TEXT DEFAULT '',
                    salary_range TEXT DEFAULT '',
                    contact_person TEXT DEFAULT '',
                    UNIQUE(company, title, url)
                )
            """)
            # ---- WEEKLY SUMMARY LOG ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weekly_summary_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sent_date TEXT,
                    week_start TEXT,
                    week_end TEXT,
                    total_new_jobs INTEGER,
                    total_applications INTEGER
                )
            """)
            conn.commit()

    @staticmethod
    def _job_key(job: Dict) -> str:
        """Generate unique key for a job. Uses company + title + location."""
        company = job.get("company", "").strip().lower()
        title = job.get("title", "").strip().lower()
        job_id = job.get("job_id", "")
        if job_id and job_id != job.get("url", ""):
            return f"{company}|{job_id}"
        location = job.get("location", "").strip().lower()
        return f"{company}|{title}|{location}"

    def filter_new_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Return only jobs we haven't seen before."""
        new_jobs = []
        now = datetime.utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            for job in jobs:
                key = self._job_key(job)
                existing = conn.execute(
                    "SELECT job_key FROM jobs WHERE job_key = ?", (key,)
                ).fetchone()

                if existing:
                    conn.execute(
                        "UPDATE jobs SET last_seen = ? WHERE job_key = ?",
                        (now, key)
                    )
                else:
                    conn.execute(
                        """INSERT INTO jobs
                        (job_key, company, title, location, url, department,
                         relevance_score, matched_keywords, platform, first_seen, last_seen, notified)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (
                            key,
                            job.get("company", ""),
                            job.get("title", ""),
                            job.get("location", ""),
                            job.get("url", ""),
                            job.get("department", ""),
                            job.get("relevance_score", 0),
                            json.dumps(job.get("matched_keywords", [])),
                            job.get("platform", ""),
                            now,
                            now,
                        )
                    )
                    new_jobs.append(job)
            conn.commit()

        logger.info(f"Found {len(new_jobs)} new jobs out of {len(jobs)}")
        return new_jobs

    def mark_notified(self, jobs: List[Dict]):
        """Mark jobs as notified."""
        with sqlite3.connect(self.db_path) as conn:
            for job in jobs:
                key = self._job_key(job)
                conn.execute(
                    "UPDATE jobs SET notified = 1 WHERE job_key = ?", (key,)
                )
            conn.commit()

    def log_run(self, companies_scraped: int, total_found: int, new_matches: int, errors: int):
        """Log a scraping run."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO run_log (run_time, companies_scraped, total_jobs_found, new_matches, errors)
                VALUES (?, ?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), companies_scraped, total_found, new_matches, errors)
            )
            conn.commit()

    def get_stats(self) -> Dict:
        """Get database statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            notified = conn.execute("SELECT COUNT(*) FROM jobs WHERE notified = 1").fetchone()[0]
            companies = conn.execute("SELECT COUNT(DISTINCT company) FROM jobs").fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
            total_apps = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            active_apps = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status NOT IN ('rejected', 'withdrawn', 'closed')"
            ).fetchone()[0]
            return {
                "total_jobs_tracked": total,
                "jobs_notified": notified,
                "unique_companies": companies,
                "total_runs": runs,
                "total_applications": total_apps,
                "active_applications": active_apps,
            }

    # ================================================================
    #  WEEKLY SUMMARY
    # ================================================================

    def get_weekly_summary(self, weeks_back: int = 1) -> Dict:
        """
        Get a summary of all activity from the past week.
        Returns new jobs found, jobs by company, application status breakdown.
        """
        now = datetime.utcnow()
        week_end = now
        week_start = now - timedelta(days=7 * weeks_back)

        start_str = week_start.isoformat()
        end_str = week_end.isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # -- New jobs discovered this week --
            new_jobs = conn.execute(
                """SELECT company, title, location, url, relevance_score, matched_keywords,
                          department, first_seen
                   FROM jobs
                   WHERE first_seen >= ? AND first_seen <= ?
                   ORDER BY relevance_score DESC""",
                (start_str, end_str)
            ).fetchall()

            # -- New jobs grouped by company --
            jobs_by_company = conn.execute(
                """SELECT company, COUNT(*) as count
                   FROM jobs
                   WHERE first_seen >= ? AND first_seen <= ?
                   GROUP BY company
                   ORDER BY count DESC""",
                (start_str, end_str)
            ).fetchall()

            # -- Jobs that disappeared (seen before this week, not seen this week) --
            stale_jobs = conn.execute(
                """SELECT company, title, location, url, first_seen, last_seen
                   FROM jobs
                   WHERE last_seen < ? AND first_seen < ?
                   ORDER BY last_seen DESC
                   LIMIT 20""",
                (start_str, start_str)
            ).fetchall()

            # -- Top scoring jobs still active (seen this week) --
            top_jobs = conn.execute(
                """SELECT company, title, location, url, relevance_score, matched_keywords
                   FROM jobs
                   WHERE last_seen >= ?
                   ORDER BY relevance_score DESC
                   LIMIT 15""",
                (start_str,)
            ).fetchall()

            # -- Application activity this week --
            app_activity = conn.execute(
                """SELECT status, COUNT(*) as count
                   FROM applications
                   WHERE updated_date >= ?
                   GROUP BY status""",
                (start_str,)
            ).fetchall()

            # -- All active applications --
            active_apps = conn.execute(
                """SELECT company, title, status, applied_date, notes, url
                   FROM applications
                   WHERE status NOT IN ('rejected', 'withdrawn', 'closed')
                   ORDER BY applied_date DESC"""
            ).fetchall()

            # -- Run stats for the week --
            run_stats = conn.execute(
                """SELECT COUNT(*) as runs,
                          SUM(total_jobs_found) as total_scraped,
                          SUM(new_matches) as total_new,
                          SUM(errors) as total_errors
                   FROM run_log
                   WHERE run_time >= ? AND run_time <= ?""",
                (start_str, end_str)
            ).fetchone()

        return {
            "week_start": week_start.strftime("%B %d, %Y"),
            "week_end": week_end.strftime("%B %d, %Y"),
            "new_jobs": [dict(r) for r in new_jobs],
            "jobs_by_company": [dict(r) for r in jobs_by_company],
            "stale_jobs": [dict(r) for r in stale_jobs],
            "top_jobs": [dict(r) for r in top_jobs],
            "app_activity": [dict(r) for r in app_activity],
            "active_apps": [dict(r) for r in active_apps],
            "run_stats": dict(run_stats) if run_stats else {},
        }

    def log_weekly_summary(self, week_start: str, week_end: str, new_jobs: int, apps: int):
        """Record that a weekly summary was sent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO weekly_summary_log (sent_date, week_start, week_end, total_new_jobs, total_applications)
                VALUES (?, ?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), week_start, week_end, new_jobs, apps)
            )
            conn.commit()

    def should_send_weekly_summary(self) -> bool:
        """Check if a weekly summary should be sent (hasn't been sent in last 6 days)."""
        with sqlite3.connect(self.db_path) as conn:
            last = conn.execute(
                "SELECT sent_date FROM weekly_summary_log ORDER BY sent_date DESC LIMIT 1"
            ).fetchone()
            if not last:
                return True
            last_date = datetime.fromisoformat(last[0])
            return (datetime.utcnow() - last_date).days >= 6

    # ================================================================
    #  APPLICATION TRACKING
    # ================================================================

    # Valid statuses and their display order
    APPLICATION_STATUSES = [
        "applied",           # Just submitted
        "screening",         # Recruiter screen scheduled/completed
        "interview",         # Technical/onsite interview stage
        "final_round",       # Final round interview
        "offer",             # Received offer
        "accepted",          # Accepted offer
        "rejected",          # Got rejected
        "withdrawn",         # You withdrew
        "closed",            # Position closed/filled
        "no_response",       # No response after reasonable time
    ]

    def add_application(self, company: str, title: str, url: str = "",
                        location: str = "", resume_version: str = "",
                        notes: str = "", salary_range: str = "",
                        contact_person: str = "") -> Optional[int]:
        """Track a new job application. Returns application ID."""
        now = datetime.utcnow().isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """INSERT INTO applications
                    (job_key, company, title, location, url, status,
                     applied_date, updated_date, resume_version, notes,
                     salary_range, contact_person)
                    VALUES (?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?)""",
                    (
                        f"{company.lower()}|{title.lower()}",
                        company, title, location, url,
                        now, now, resume_version, notes,
                        salary_range, contact_person,
                    )
                )
                conn.commit()
                app_id = cursor.lastrowid
                logger.info(f"Application #{app_id} added: {title} @ {company}")
                return app_id
        except sqlite3.IntegrityError:
            logger.warning(f"Application already exists: {title} @ {company}")
            return None

    def update_application(self, app_id: int, **kwargs) -> bool:
        """
        Update application fields. Supported fields:
        status, notes, interview_date, response_date, salary_range,
        contact_person, resume_version
        """
        allowed = {"status", "notes", "interview_date", "response_date",
                    "salary_range", "contact_person", "resume_version"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}

        if not updates:
            return False

        if "status" in updates and updates["status"] not in self.APPLICATION_STATUSES:
            logger.error(f"Invalid status: {updates['status']}. Must be one of: {self.APPLICATION_STATUSES}")
            return False

        updates["updated_date"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [app_id]

        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute(
                f"UPDATE applications SET {set_clause} WHERE id = ?", values
            )
            conn.commit()
            if result.rowcount > 0:
                logger.info(f"Application #{app_id} updated: {updates}")
                return True
            logger.warning(f"Application #{app_id} not found")
            return False

    def get_applications(self, status: str = None, company: str = None) -> List[Dict]:
        """Get applications with optional filters."""
        query = "SELECT * FROM applications WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if company:
            query += " AND LOWER(company) LIKE ?"
            params.append(f"%{company.lower()}%")

        query += " ORDER BY updated_date DESC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_application_summary(self) -> Dict:
        """Get a pipeline summary of all applications by status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Count by status
            by_status = conn.execute(
                """SELECT status, COUNT(*) as count
                   FROM applications GROUP BY status ORDER BY count DESC"""
            ).fetchall()

            # Count by company
            by_company = conn.execute(
                """SELECT company, COUNT(*) as count, GROUP_CONCAT(status) as statuses
                   FROM applications GROUP BY company ORDER BY count DESC"""
            ).fetchall()

            # Recent activity (last 7 days)
            week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
            recent = conn.execute(
                """SELECT company, title, status, updated_date
                   FROM applications WHERE updated_date >= ?
                   ORDER BY updated_date DESC""",
                (week_ago,)
            ).fetchall()

            # Response rate
            total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            responded = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status NOT IN ('applied', 'no_response')"
            ).fetchone()[0]

            # Average days to response
            avg_response = conn.execute(
                """SELECT AVG(julianday(response_date) - julianday(applied_date))
                   FROM applications
                   WHERE response_date != '' AND response_date IS NOT NULL"""
            ).fetchone()[0]

        return {
            "by_status": [dict(r) for r in by_status],
            "by_company": [dict(r) for r in by_company],
            "recent_activity": [dict(r) for r in recent],
            "total_applications": total,
            "response_rate": f"{(responded/total*100):.0f}%" if total > 0 else "N/A",
            "avg_days_to_response": f"{avg_response:.1f}" if avg_response else "N/A",
        }

    def delete_application(self, app_id: int) -> bool:
        """Delete an application by ID."""
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            conn.commit()
            return result.rowcount > 0
