"""
Job platform scrapers - extract job listings from various career page platforms.
Supports: Greenhouse, Lever, Workday, SmartRecruiters, and generic HTML.
"""

import re
import json
import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def detect_platform(url: str) -> str:
    """Auto-detect which job platform a career URL uses."""
    url_lower = url.lower()
    if "greenhouse.io" in url_lower or "boards.greenhouse" in url_lower:
        return "greenhouse"
    elif "lever.co" in url_lower or "jobs.lever.co" in url_lower:
        return "lever"
    elif ".myworkdayjobs.com" in url_lower or "workday" in url_lower:
        return "workday"
    elif "smartrecruiters.com" in url_lower:
        return "smartrecruiters"
    elif "jobvite.com" in url_lower:
        return "jobvite"
    elif "icims.com" in url_lower:
        return "icims"
    elif "ashbyhq.com" in url_lower:
        return "ashby"
    else:
        return "generic"


def extract_company_slug(url: str, platform: str) -> Optional[str]:
    """Extract company identifier from career URL."""
    try:
        if platform == "greenhouse":
            # https://boards.greenhouse.io/company or https://job-boards.greenhouse.io/company-name
            # or ?for=company
            match = re.search(r'greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)', url)
            if match:
                return match.group(1)
            parts = urlparse(url).path.strip('/').split('/')
            return parts[-1] if parts else None
        elif platform == "lever":
            # https://jobs.lever.co/company
            parts = urlparse(url).path.strip('/').split('/')
            return parts[0] if parts else None
        elif platform == "workday":
            # https://company.wd1.myworkdayjobs.com/...
            match = re.search(r'([\w-]+)\.wd\d+\.myworkdayjobs\.com', url)
            return match.group(1) if match else None
        elif platform == "smartrecruiters":
            match = re.search(r'smartrecruiters\.com/([\w-]+)', url)
            return match.group(1) if match else None
        elif platform == "ashby":
            # https://jobs.ashbyhq.com/company-name
            match = re.search(r'ashbyhq\.com/([\w-]+)', url)
            return match.group(1) if match else None
    except Exception:
        pass
    return None


class JobScraper:
    """Unified job scraper supporting multiple platforms."""

    def __init__(self, config: dict):
        self.session = requests.Session()
        scrape_cfg = config.get("scraping", {})
        self.session.headers.update({
            "User-Agent": scrape_cfg.get("user_agent", "Mozilla/5.0"),
            "Accept": "application/json, text/html",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.delay = scrape_cfg.get("delay_between_requests", 2)
        self.timeout = scrape_cfg.get("timeout", 30)
        self.max_retries = scrape_cfg.get("max_retries", 2)

    def _request(self, url: str, accept_json: bool = False) -> Optional[requests.Response]:
        """Make HTTP request with retries."""
        headers = {}
        if accept_json:
            headers["Accept"] = "application/json"
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, headers=headers)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt+1}): {url} - {e}")
                if attempt < self.max_retries:
                    time.sleep(self.delay * (attempt + 1))
        return None

    def scrape_company(self, company_name: str, career_url: str) -> List[Dict]:
        """Scrape jobs from a company career page. Returns list of job dicts."""
        platform = detect_platform(career_url)
        logger.info(f"Scraping {company_name} [{platform}]: {career_url}")

        try:
            if platform == "greenhouse":
                jobs = self._scrape_greenhouse(company_name, career_url)
            elif platform == "lever":
                jobs = self._scrape_lever(company_name, career_url)
            elif platform == "workday":
                jobs = self._scrape_workday(company_name, career_url)
            elif platform == "smartrecruiters":
                jobs = self._scrape_smartrecruiters(company_name, career_url)
            elif platform == "ashby":
                jobs = self._scrape_ashby(company_name, career_url)
            else:
                jobs = self._scrape_generic(company_name, career_url)
        except Exception as e:
            logger.error(f"Error scraping {company_name}: {e}")
            jobs = []

        for job in jobs:
            job["company"] = company_name
            job["platform"] = platform
            job["source_url"] = career_url

        time.sleep(self.delay)
        return jobs

    def fetch_job_description(self, job: Dict) -> str:
        """
        Second-pass: fetch the full description for a single job.
        Called only for jobs that already matched primary keywords in title.
        Returns description text (truncated to 2000 chars).
        """
        platform = job.get("platform", "")
        job_url = job.get("url", "")
        job_id = job.get("job_id", "")
        source_url = job.get("source_url", "")

        try:
            if platform == "greenhouse":
                return self._fetch_desc_greenhouse(job_id, source_url)
            elif platform == "lever":
                return self._fetch_desc_lever(job_url)
            elif platform == "workday":
                return self._fetch_desc_workday(job_url, source_url)
            elif platform == "smartrecruiters":
                return self._fetch_desc_smartrecruiters(job_id, source_url)
            elif platform == "ashby":
                return self._fetch_desc_ashby(job_id, source_url)
            else:
                return self._fetch_desc_generic(job_url)
        except Exception as e:
            logger.debug(f"  Could not fetch description: {e}")
            return ""

    def _fetch_desc_greenhouse(self, job_id: str, source_url: str) -> str:
        slug = extract_company_slug(source_url, "greenhouse")
        if not slug or not job_id:
            return ""

        # job_id might be a numeric ID ("4136373008") or a full URL
        # (happens when generic scraper was used as fallback)
        numeric_id = job_id
        if '/' in job_id or 'http' in job_id:
            # Extract numeric ID from URL like ".../jobs/4136373008"
            match = re.search(r'/jobs/(\d+)', job_id)
            if match:
                numeric_id = match.group(1)
            else:
                # Can't extract ID, try fetching the URL directly instead
                return self._fetch_desc_generic(job_id)

        api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{numeric_id}"
        resp = self._request(api_url, accept_json=True)
        if resp:
            data = resp.json()
            content = data.get("content", "")
            text = BeautifulSoup(content, "html.parser").get_text(separator=" ", strip=True)
            return text[:2000]
        return ""

    def _fetch_desc_lever(self, job_url: str) -> str:
        if not job_url:
            return ""
        # Lever hosted pages have readable HTML
        resp = self._request(job_url)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Lever puts description in div.section-wrapper
            content = soup.find("div", class_="section-wrapper")
            if not content:
                content = soup.find("div", {"class": re.compile(r"content|description|posting", re.I)})
            if content:
                return content.get_text(separator=" ", strip=True)[:2000]
        return ""

    def _fetch_desc_workday(self, job_url: str, source_url: str) -> str:
        if not job_url:
            return ""
        slug = extract_company_slug(source_url, "workday")
        if not slug:
            return ""
        # Extract job path for Workday API
        parsed = urlparse(job_url)
        job_path = parsed.path
        # Try multiple wd domains
        for wd_num in range(1, 6):
            api_url = f"https://{slug}.wd{wd_num}.myworkdayjobs.com/wday/cxs{job_path}"
            try:
                resp = self.session.get(api_url, timeout=self.timeout,
                                        headers={"Accept": "application/json"})
                if resp.status_code == 200:
                    data = resp.json()
                    desc = data.get("jobPostingInfo", {}).get("jobDescription", "")
                    if desc:
                        text = BeautifulSoup(desc, "html.parser").get_text(separator=" ", strip=True)
                        return text[:2000]
            except Exception:
                continue
        return ""

    def _fetch_desc_smartrecruiters(self, job_id: str, source_url: str) -> str:
        slug = extract_company_slug(source_url, "smartrecruiters")
        if not slug or not job_id:
            return ""
        api_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}"
        resp = self._request(api_url, accept_json=True)
        if resp:
            data = resp.json()
            sections = data.get("jobAd", {}).get("sections", {})
            parts = []
            for key in ["jobDescription", "qualifications", "additionalInformation"]:
                section = sections.get(key, {})
                text = section.get("text", "")
                if text:
                    parts.append(BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True))
            return " ".join(parts)[:2000]
        return ""

    def _fetch_desc_ashby(self, job_id: str, source_url: str) -> str:
        slug = extract_company_slug(source_url, "ashby")
        if not slug or not job_id:
            return ""

        # The individual posting API (/posting/{id}) now returns 401.
        # Fallback: scrape the public job page URL directly.
        job_page_url = f"https://jobs.ashbyhq.com/{slug}/{job_id}"
        try:
            resp = self._request(job_page_url)
            if resp:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Ashby job pages render description in a main content area
                desc_div = soup.find("div", {"class": lambda c: c and "posting-" in c})
                if not desc_div:
                    desc_div = soup.find("main") or soup.find("article") or soup.find("body")
                if desc_div:
                    text = desc_div.get_text(separator=" ", strip=True)
                    return text[:2000]
        except Exception as e:
            logger.debug(f"  Ashby page scrape failed: {e}")
        return ""

    def _fetch_desc_generic(self, job_url: str) -> str:
        if not job_url:
            return ""
        resp = self._request(job_url)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Try common description containers
            for selector in [
                {"class": re.compile(r"job.?desc|posting.?desc|description", re.I)},
                {"class": re.compile(r"content|body|main", re.I)},
                {"id": re.compile(r"job.?desc|description", re.I)},
            ]:
                container = soup.find("div", selector)
                if container and len(container.get_text(strip=True)) > 100:
                    return container.get_text(separator=" ", strip=True)[:2000]
            # Fallback: grab all paragraph text
            paragraphs = soup.find_all("p")
            text = " ".join(p.get_text(strip=True) for p in paragraphs)
            if len(text) > 100:
                return text[:2000]
        return ""

    # ========== GREENHOUSE ==========
    def _scrape_greenhouse(self, company: str, url: str) -> List[Dict]:
        slug = extract_company_slug(url, "greenhouse")
        if not slug:
            return self._scrape_generic(company, url)

        # Greenhouse API supports pagination via 'page' and 'per_page' params
        page_size = 100
        max_pages = 10
        all_jobs = []

        try:
            for page in range(1, max_pages + 1):
                api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?per_page={page_size}&page={page}"
                resp = self._request(api_url, accept_json=True)
                if not resp:
                    break

                data = resp.json()
                postings = data.get("jobs", [])
                total = data.get("meta", {}).get("total", 0)

                for j in postings:
                    loc = j.get("location", {}).get("name", "")
                    job = {
                        "title": j.get("title", ""),
                        "job_id": str(j.get("id", "")),
                        "location": loc,
                        "url": j.get("absolute_url", ""),
                        "department": "",
                        "description": "",
                    }
                    depts = j.get("departments", [])
                    if depts:
                        job["department"] = depts[0].get("name", "")
                    all_jobs.append(job)

                logger.debug(f"  Greenhouse page {page}: got {len(postings)} jobs (total: {total})")

                if len(postings) < page_size:
                    break

                time.sleep(1)

            if all_jobs:
                logger.info(f"  Greenhouse pagination: fetched {len(all_jobs)} total jobs")
                return all_jobs

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Greenhouse JSON parse error for {company}: {e}")

        return self._scrape_generic(company, url)

    # ========== LEVER ==========
    def _scrape_lever(self, company: str, url: str) -> List[Dict]:
        slug = extract_company_slug(url, "lever")
        if not slug:
            return self._scrape_generic(company, url)

        # Lever API returns all postings at once (no built-in pagination needed),
        # but uses cursor-based pagination via 'skip' for very large boards
        page_size = 100
        max_pages = 10
        all_jobs = []

        try:
            for page in range(max_pages):
                skip = page * page_size
                api_url = f"https://api.lever.co/v0/postings/{slug}?mode=json&limit={page_size}&skip={skip}"
                resp = self._request(api_url, accept_json=True)
                if not resp:
                    break

                data = resp.json()
                if not isinstance(data, list):
                    break

                for j in data:
                    cats = j.get("categories", {})
                    job = {
                        "title": j.get("text", ""),
                        "job_id": j.get("id", ""),
                        "location": cats.get("location", ""),
                        "url": j.get("hostedUrl", ""),
                        "department": cats.get("team", ""),
                        "description": j.get("descriptionPlain", "")[:500],
                    }
                    all_jobs.append(job)

                logger.debug(f"  Lever page {page+1}: got {len(data)} jobs")

                # Stop if fewer results than page size (last page)
                if len(data) < page_size:
                    break

                time.sleep(1)

            if all_jobs:
                logger.info(f"  Lever pagination: fetched {len(all_jobs)} total jobs")
                return all_jobs

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Lever JSON parse error for {company}: {e}")

        return self._scrape_generic(company, url)

    # ========== WORKDAY ==========
    def _scrape_workday(self, company: str, url: str) -> List[Dict]:
        """Workday sites are JS-heavy. Try the search API endpoint with pagination."""
        slug = extract_company_slug(url, "workday")
        if not slug:
            return self._scrape_generic(company, url)

        # Try to extract the site path from the URL
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        # Typical: /en-US/SiteName/jobs or just /SiteName
        site_name = None
        for part in path_parts:
            if part not in ('en-US', 'en', 'jobs', 'details', ''):
                site_name = part
                break
        if not site_name:
            site_name = slug

        # Try multiple Workday domain variants (wd1 through wd5)
        wd_domain = None
        for wd_num in range(1, 6):
            test_url = f"https://{slug}.wd{wd_num}.myworkdayjobs.com/wday/cxs/{slug}/{site_name}/jobs"
            try:
                test_resp = self.session.post(test_url, json={"limit": 1, "offset": 0}, timeout=10,
                                              headers={"Content-Type": "application/json"})
                if test_resp.status_code == 200:
                    wd_domain = f"wd{wd_num}"
                    break
            except Exception:
                continue

        if not wd_domain:
            wd_domain = "wd1"  # fallback

        api_url = f"https://{slug}.{wd_domain}.myworkdayjobs.com/wday/cxs/{slug}/{site_name}/jobs"
        headers = {"Content-Type": "application/json"}
        page_size = 20
        max_pages = 50  # Safety cap: 50 pages × 20 = 1000 jobs max
        all_jobs = []

        try:
            for page in range(max_pages):
                offset = page * page_size
                payload = {"appliedFacets": {}, "limit": page_size, "offset": offset, "searchText": ""}
                resp = self.session.post(api_url, json=payload, timeout=self.timeout, headers=headers)

                if resp.status_code != 200:
                    break

                data = resp.json()
                postings = data.get("jobPostings", [])
                total = data.get("total", 0)

                if not postings:
                    break  # No more results

                for j in postings:
                    job = {
                        "title": j.get("title", ""),
                        "job_id": j.get("bulletFields", [""])[0] if j.get("bulletFields") else "",
                        "location": j.get("locationsText", ""),
                        "url": f"https://{slug}.{wd_domain}.myworkdayjobs.com{j.get('externalPath', '')}",
                        "department": "",
                        "description": "",
                    }
                    all_jobs.append(job)

                logger.debug(f"  Workday page {page+1}: got {len(postings)} jobs (API total: {total})")

                # Stop ONLY if we got fewer results than requested (last page)
                # Do NOT trust 'total' — many Workday sites report incorrect totals
                if len(postings) < page_size:
                    break

                time.sleep(1)  # Be respectful between pages

            if all_jobs:
                logger.info(f"  Workday pagination: fetched {len(all_jobs)} total jobs across {page+1} page(s)")
                return all_jobs

        except Exception as e:
            logger.warning(f"Workday API failed for {company}: {e}")

        return self._scrape_generic(company, url)

    # ========== SMARTRECRUITERS ==========
    def _scrape_smartrecruiters(self, company: str, url: str) -> List[Dict]:
        slug = extract_company_slug(url, "smartrecruiters")
        if not slug:
            return self._scrape_generic(company, url)

        page_size = 100  # SmartRecruiters supports up to 100 per page
        max_pages = 10   # Safety cap: 10 pages × 100 = 1000 jobs max
        all_jobs = []

        try:
            for page in range(max_pages):
                offset = page * page_size
                api_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit={page_size}&offset={offset}"
                resp = self._request(api_url, accept_json=True)
                if not resp:
                    break

                data = resp.json()
                postings = data.get("content", [])
                total = data.get("totalFound", 0)

                for j in postings:
                    loc = j.get("location", {})
                    loc_str = f"{loc.get('city', '')}, {loc.get('region', '')}".strip(', ')
                    job = {
                        "title": j.get("name", ""),
                        "job_id": j.get("id", ""),
                        "location": loc_str,
                        "url": j.get("ref", ""),
                        "department": j.get("department", {}).get("label", ""),
                        "description": "",
                    }
                    all_jobs.append(job)

                logger.debug(f"  SmartRecruiters page {page+1}: got {len(postings)} jobs (total: {total})")

                if len(all_jobs) >= total or len(postings) < page_size:
                    break

                time.sleep(1)

            if all_jobs:
                logger.info(f"  SmartRecruiters pagination: fetched {len(all_jobs)} total jobs")
                return all_jobs

        except Exception as e:
            logger.warning(f"SmartRecruiters parse error for {company}: {e}")

        return self._scrape_generic(company, url)

    # ========== ASHBY ==========
    def _scrape_ashby(self, company: str, url: str) -> List[Dict]:
        slug = extract_company_slug(url, "ashby")
        if not slug:
            return self._scrape_generic(company, url)

        api_url = "https://api.ashbyhq.com/posting-api/job-board/" + slug
        resp = self._request(api_url, accept_json=True)
        if not resp:
            return self._scrape_generic(company, url)

        try:
            data = resp.json()
            jobs = []
            for j in data.get("jobs", []):
                # The listing API returns descriptionPlain — grab it now
                # so we don't need a second-pass fetch.
                desc_text = j.get("descriptionPlain", "") or ""
                if not desc_text and j.get("descriptionHtml"):
                    desc_text = BeautifulSoup(j["descriptionHtml"], "html.parser").get_text(separator=" ", strip=True)
                job = {
                    "title": j.get("title", ""),
                    "job_id": j.get("id", ""),
                    "location": j.get("location", ""),
                    "url": j.get("jobUrl", ""),
                    "department": j.get("departmentName", ""),
                    "description": desc_text[:2000],
                }
                jobs.append(job)
            return jobs
        except Exception as e:
            logger.warning(f"Ashby parse error for {company}: {e}")
            return self._scrape_generic(company, url)

    # ========== GENERIC HTML SCRAPER ==========
    def _scrape_generic(self, company: str, url: str) -> List[Dict]:
        """Fallback HTML scraper - extracts job-like links from any career page."""
        resp = self._request(url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        jobs = []
        seen_urls = set()

        # Look for job-like links
        job_patterns = [
            r'/job[s]?/',
            r'/position[s]?/',
            r'/opening[s]?/',
            r'/career[s]?/',
            r'/role[s]?/',
            r'job[-_]?id',
            r'posting',
            r'requisition',
            r'apply',
        ]
        pattern = re.compile('|'.join(job_patterns), re.IGNORECASE)

        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True)

            if not text or len(text) < 5 or len(text) > 200:
                continue
            # Skip navigation/generic links
            skip_words = ['login', 'sign in', 'about us', 'contact', 'privacy', 'terms',
                          'home', 'back', 'menu', 'blog', 'news', 'cookie']
            if any(w in text.lower() for w in skip_words):
                continue

            full_url = urljoin(url, href)
            if full_url in seen_urls:
                continue

            # Check if it looks like a job link
            if pattern.search(href) or pattern.search(text):
                seen_urls.add(full_url)
                jobs.append({
                    "title": text,
                    "job_id": full_url,
                    "location": "",
                    "url": full_url,
                    "department": "",
                    "description": "",
                })

        # Deduplicate by title
        unique = {}
        for j in jobs:
            key = j["title"].lower().strip()
            if key not in unique:
                unique[key] = j
        return list(unique.values())
