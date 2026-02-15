"""
Job platform scrapers - extract job listings from various career page platforms.
Supports: Greenhouse, Lever, Workday, SmartRecruiters, Recruitee, Taleo, Oracle HCM Cloud, and generic HTML.
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
    if "amazon.jobs" in url_lower:
        return "amazon"
    elif "greenhouse.io" in url_lower or "boards.greenhouse" in url_lower:
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
    elif "recruitee.com" in url_lower:
        return "recruitee"
    elif "/go/" in url_lower and re.search(r'/go/[\w-]+/\d+', url_lower):
        return "taleo"
    elif ".oraclecloud.com" in url_lower or "candidateexperience" in url_lower:
        return "oraclecloud"
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
        elif platform == "amazon":
            # https://amazon.jobs/content/en/teams/ftr/amazon-robotics#search
            # Extract team slug from the URL path
            match = re.search(r'/teams?/(?:ftr/)?([\w-]+)', url)
            return match.group(1) if match else None
        elif platform == "recruitee":
            # https://1x.recruitee.com/ → "1x"
            match = re.search(r'([\w-]+)\.recruitee\.com', url)
            return match.group(1) if match else None
        elif platform == "oraclecloud":
            # https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs
            # Extract base host identifier (e.g., "hctz") and cloud region (e.g., "fa.us2")
            match = re.search(r'([\w-]+)\.(fa\.\w+)\.oraclecloud\.com', url)
            return f"{match.group(1)}.{match.group(2)}" if match else None
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
            if platform == "amazon":
                jobs = self._scrape_amazon(company_name, career_url)
            elif platform == "greenhouse":
                jobs = self._scrape_greenhouse(company_name, career_url)
            elif platform == "lever":
                jobs = self._scrape_lever(company_name, career_url)
            elif platform == "workday":
                jobs = self._scrape_workday(company_name, career_url)
            elif platform == "smartrecruiters":
                jobs = self._scrape_smartrecruiters(company_name, career_url)
            elif platform == "ashby":
                jobs = self._scrape_ashby(company_name, career_url)
            elif platform == "recruitee":
                jobs = self._scrape_recruitee(company_name, career_url)
            elif platform == "taleo":
                jobs = self._scrape_taleo(company_name, career_url)
            elif platform == "oraclecloud":
                jobs = self._scrape_oracle_hcm(company_name, career_url)
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
        Returns description text (truncated to 5000 chars to ensure
        qualifications/requirements sections are captured for filtering).
        """
        platform = job.get("platform", "")
        job_url = job.get("url", "")
        job_id = job.get("job_id", "")
        source_url = job.get("source_url", "")

        try:
            if platform == "amazon":
                # Amazon API returns full descriptions inline; already stored
                return self._fetch_desc_amazon(job)
            elif platform == "greenhouse":
                return self._fetch_desc_greenhouse(job_id, source_url)
            elif platform == "lever":
                return self._fetch_desc_lever(job_url)
            elif platform == "workday":
                return self._fetch_desc_workday(job_url, source_url)
            elif platform == "smartrecruiters":
                return self._fetch_desc_smartrecruiters(job_id, source_url)
            elif platform == "ashby":
                return self._fetch_desc_ashby(job_id, source_url)
            elif platform == "recruitee":
                return self._fetch_desc_recruitee(job)
            elif platform == "taleo":
                return self._fetch_desc_taleo(job_url)
            elif platform == "oraclecloud":
                return self._fetch_desc_oracle_hcm(job)
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
            return text[:5000]
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
                return content.get_text(separator=" ", strip=True)[:5000]
        return ""

    def _fetch_desc_workday(self, job_url: str, source_url: str) -> str:
        if not job_url:
            return ""
        slug = extract_company_slug(source_url, "workday")
        if not slug:
            slug = extract_company_slug(job_url, "workday")
        if not slug:
            return ""
        # Extract job path for Workday API
        parsed = urlparse(job_url)
        job_path = parsed.path

        # Strip locale prefix (e.g., /en-US/) — the CXS API doesn't accept it
        job_path = re.sub(r'^/[a-z]{2}[-_][A-Z]{2}/', '/', job_path)

        # Detect wd domain from the job URL itself (e.g., wd5 from generalmotors.wd5.myworkdayjobs.com)
        wd_match = re.search(r'\.wd(\d+)\.myworkdayjobs\.com', job_url)
        wd_nums = [int(wd_match.group(1))] if wd_match else list(range(1, 6))

        for wd_num in wd_nums:
            api_url = f"https://{slug}.wd{wd_num}.myworkdayjobs.com/wday/cxs/{slug}{job_path}"
            try:
                resp = self.session.get(api_url, timeout=self.timeout,
                                        headers={"Accept": "application/json"})
                if resp.status_code == 200:
                    data = resp.json()
                    posting_info = data.get("jobPostingInfo", {})
                    # Combine all description fields — Workday often puts
                    # visa/legal requirements in additionalInformation or
                    # qualifications, NOT in the main jobDescription
                    parts = []
                    for field in ["jobDescription", "qualifications", "additionalInformation"]:
                        html = posting_info.get(field, "")
                        if html:
                            text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
                            parts.append(text)
                    if parts:
                        return " ".join(parts)[:5000]
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
            return " ".join(parts)[:5000]
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
                    return text[:5000]
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
                    return container.get_text(separator=" ", strip=True)[:5000]
            # Fallback: grab all paragraph text
            paragraphs = soup.find_all("p")
            text = " ".join(p.get_text(strip=True) for p in paragraphs)
            if len(text) > 100:
                return text[:5000]
        return ""

    # ========== AMAZON JOBS ==========
    def _fetch_desc_amazon(self, job: Dict) -> str:
        """Amazon API returns full descriptions inline; just clean up HTML tags."""
        raw = job.get("description", "")
        if not raw:
            return ""
        # Strip HTML tags from the API response
        text = re.sub(r'<[^>]+>', ' ', raw)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:5000]

    def _scrape_amazon(self, company: str, url: str) -> List[Dict]:
        """
        Scrape Amazon Jobs using the public search.json API.
        Supports team_category filtering (e.g., amazon-robotics) and
        country filtering with automatic pagination.
        """
        # Extract team category from URL if present
        # e.g., https://amazon.jobs/content/en/teams/ftr/amazon-robotics#search
        team_slug = extract_company_slug(url, "amazon")
        team_category = f"team-{team_slug}" if team_slug else None

        all_jobs = []
        page_size = 25
        offset = 0
        max_pages = 20  # Safety limit: 500 jobs max

        for page in range(max_pages):
            api_url = (
                f"https://amazon.jobs/en/search.json"
                f"?base_query="
                f"&result_limit={page_size}"
                f"&sort=recent"
                f"&offset={offset}"
                f"&country=USA"
            )
            if team_category:
                api_url += f"&team_category[]={team_category}"

            # Use explicit headers to avoid zstd encoding issues
            try:
                resp = self.session.get(
                    api_url, timeout=self.timeout,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip, deflate",
                    }
                )
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.warning(f"Amazon API request failed at offset {offset}: {e}")
                break

            try:
                data = resp.json()
            except Exception as e:
                logger.warning(f"Amazon API JSON parse error: {e}")
                break

            total_hits = data.get("hits", 0)
            jobs_data = data.get("jobs", [])

            if not jobs_data:
                break

            for j in jobs_data:
                # Combine description + qualifications for full text
                desc = j.get("description", "")
                basic_quals = j.get("basic_qualifications", "")
                pref_quals = j.get("preferred_qualifications", "")
                full_desc = f"{desc}\n{basic_quals}\n{pref_quals}"

                job_id = j.get("id_icims", j.get("id", ""))
                job_path = j.get("job_path", "")
                job_url = f"https://amazon.jobs{job_path}" if job_path else ""

                all_jobs.append({
                    "title": j.get("title", ""),
                    "job_id": job_id,
                    "location": j.get("normalized_location", j.get("location", "")),
                    "url": job_url,
                    "department": j.get("job_category", ""),
                    "description": full_desc,
                })

            logger.debug(f"  Amazon page {page+1}: {len(jobs_data)} jobs (total: {total_hits})")

            offset += page_size
            if offset >= total_hits:
                break
            time.sleep(self.delay)

        logger.info(f"  Amazon: found {len(all_jobs)} jobs" +
                    (f" in team '{team_category}'" if team_category else ""))
        return all_jobs

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
            base_domain = f"{slug}.wd{wd_num}.myworkdayjobs.com"
            test_url = f"https://{base_domain}/wday/cxs/{slug}/{site_name}/jobs"
            try:
                test_resp = self.session.post(test_url, json={"limit": 1, "offset": 0}, timeout=10,
                                              headers={
                                                  "Content-Type": "application/json",
                                                  "Accept": "application/json",
                                                  "Referer": f"https://{base_domain}/{site_name}/",
                                                  "Origin": f"https://{base_domain}",
                                              })
                if test_resp.status_code == 200 and test_resp.text.strip().startswith("{"):
                    wd_domain = f"wd{wd_num}"
                    break
            except Exception:
                continue

        if not wd_domain:
            wd_domain = "wd1"  # fallback

        base_domain = f"{slug}.{wd_domain}.myworkdayjobs.com"
        api_url = f"https://{base_domain}/wday/cxs/{slug}/{site_name}/jobs"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": f"https://{base_domain}/{site_name}/",
            "Origin": f"https://{base_domain}",
        }
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

                # Validate response is JSON before parsing
                if not resp.text.strip().startswith("{"):
                    logger.warning(f"Workday returned non-JSON response for {company} (page {page+1})")
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
                    "description": desc_text[:5000],
                }
                jobs.append(job)
            return jobs
        except Exception as e:
            logger.warning(f"Ashby parse error for {company}: {e}")
            return self._scrape_generic(company, url)

    # ========== RECRUITEE ==========
    def _scrape_recruitee(self, company: str, url: str) -> List[Dict]:
        """Scrape jobs via the Recruitee public API."""
        slug = extract_company_slug(url, "recruitee")
        if not slug:
            return self._scrape_generic(company, url)

        api_url = f"https://{slug}.recruitee.com/api/offers"
        resp = self._request(api_url, accept_json=True)
        if not resp:
            return self._scrape_generic(company, url)

        try:
            data = resp.json()
            offers = data.get("offers", [])
            jobs = []
            for o in offers:
                # Strip HTML from description for a preview
                raw_desc = o.get("description", "") or ""
                desc_text = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ", strip=True) if raw_desc else ""

                job = {
                    "title": o.get("title", ""),
                    "job_id": str(o.get("id", "")),
                    "location": o.get("location", ""),
                    "url": o.get("careers_url", ""),
                    "department": o.get("department", ""),
                    "description": desc_text[:5000],
                }
                jobs.append(job)

            logger.info(f"  Recruitee: fetched {len(jobs)} jobs")
            return jobs
        except Exception as e:
            logger.warning(f"Recruitee parse error for {company}: {e}")
            return self._scrape_generic(company, url)

    def _fetch_desc_recruitee(self, job: Dict) -> str:
        """Recruitee descriptions are fetched inline during scraping; just return stored text."""
        return job.get("description", "")

    # ========== TALEO ==========
    def _scrape_taleo(self, company: str, url: str) -> List[Dict]:
        """Scrape jobs from a Taleo career board with pagination."""
        # Extract the base search path (e.g., /go/Search/8797500)
        parsed = urlparse(url)
        base_match = re.search(r'(/go/[\w-]+/\d+)', parsed.path)
        if not base_match:
            return self._scrape_generic(company, url)

        base_path = base_match.group(1)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        page_size = 25
        max_pages = 40  # Safety cap: 40 pages x 25 = 1000 jobs
        all_jobs = []
        seen_ids = set()

        for page in range(max_pages):
            offset = page * page_size
            if offset == 0:
                page_url = f"{base_url}{base_path}/?q=&sortColumn=referencedate&sortDirection=desc"
            else:
                page_url = f"{base_url}{base_path}/{offset}/?q=&sortColumn=referencedate&sortDirection=desc"

            resp = self._request(page_url)
            if not resp:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", id="searchresults")
            if not table:
                break

            rows = table.find_all("tr", class_="data-row")
            if not rows:
                break

            for row in rows:
                tds = row.find_all("td")
                if len(tds) < 2:
                    continue

                # Title and URL from the first column
                title_link = row.find("a", href=lambda h: h and "/job/" in h)
                if not title_link:
                    continue

                title = title_link.get_text(strip=True)
                href = title_link["href"]
                job_url = urljoin(base_url, href)

                # Extract job ID from URL: /job/.../1350587900/
                id_match = re.search(r'/(\d{5,})/?$', href)
                job_id = id_match.group(1) if id_match else job_url

                # Skip duplicates (Taleo shows each job twice: desktop + mobile)
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                # Location from second column
                location = tds[1].get_text(strip=True) if len(tds) > 1 else ""

                all_jobs.append({
                    "title": title,
                    "job_id": job_id,
                    "location": location,
                    "url": job_url,
                    "department": "",
                    "description": "",
                })

            logger.debug(f"  Taleo page {page+1}: {len(rows)} rows, {len(all_jobs)} unique jobs so far")

            # Stop if fewer rows than expected (last page)
            if len(rows) < page_size:
                break

            time.sleep(self.delay)

        if all_jobs:
            logger.info(f"  Taleo: fetched {len(all_jobs)} total jobs across {page+1} page(s)")
            return all_jobs

        return self._scrape_generic(company, url)

    def _fetch_desc_taleo(self, job_url: str) -> str:
        """Fetch description from a Taleo job detail page."""
        if not job_url:
            return ""
        resp = self._request(job_url)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Taleo job pages put description in a div with class containing 'job-description'
            desc_div = soup.find("div", class_=re.compile(r"job.?desc|description", re.I))
            if not desc_div:
                desc_div = soup.find("div", id=re.compile(r"job.?desc|description", re.I))
            if not desc_div:
                # Fallback: try the main content area
                desc_div = soup.find("div", class_="contentWrapper") or soup.find("main")
            if desc_div:
                return desc_div.get_text(separator=" ", strip=True)[:5000]
        return ""

    # ========== ORACLE HCM CLOUD ==========
    def _scrape_oracle_hcm(self, company: str, url: str) -> List[Dict]:
        """Oracle HCM Cloud / Oracle Recruiting Cloud career sites.
        Uses the public recruitingCEJobRequisitions REST API."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.hostname}"

        # Extract site number from URL path (e.g., CX_1001 from /sites/CX_1001/)
        site_match = re.search(r'/sites/([\w_]+)', url)
        if not site_match:
            logger.warning(f"Oracle HCM: could not extract site number from {url}")
            return self._scrape_generic(company, url)
        site_number = site_match.group(1)

        api_url = f"{base_url}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": url,
            "Origin": base_url,
        }
        page_size = 25
        max_pages = 40  # Safety cap: 40 pages x 25 = 1000 jobs max
        all_jobs = []

        try:
            # First, visit the career page to establish session cookies
            self.session.get(url, timeout=self.timeout, headers={"Accept": "text/html"})

            for page in range(max_pages):
                offset = page * page_size
                params = {
                    "onlyData": "true",
                    "expand": "requisitionList.secondaryLocations,flexFieldsFacet.values",
                    "finder": (
                        f"findReqs;siteNumber={site_number},"
                        f"facetsList=LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS,"
                        f"limit={page_size},offset={offset}"
                    ),
                }
                resp = self.session.get(api_url, params=params, timeout=self.timeout, headers=headers)

                if resp.status_code != 200:
                    logger.warning(f"Oracle HCM API returned {resp.status_code} for {company} (page {page+1})")
                    break

                if not resp.text.strip().startswith(("{", "[")):
                    logger.warning(f"Oracle HCM returned non-JSON response for {company} (page {page+1})")
                    break

                data = resp.json()
                items = data.get("items", [])
                if not items:
                    break

                requisitions = items[0].get("requisitionList", [])
                total_count = items[0].get("TotalJobsCount", 0)

                if not requisitions:
                    break

                for r in requisitions:
                    req_id = str(r.get("Id", ""))
                    title = r.get("Title", "")
                    location = r.get("PrimaryLocation", "")
                    department = r.get("DepartmentName", "") or r.get("BusinessUnitName", "")
                    # Build the candidate-facing URL for this job
                    job_url = f"{base_url}/hcmUI/CandidateExperience/en/sites/{site_number}/job/{req_id}"

                    job = {
                        "title": title,
                        "job_id": req_id,
                        "location": location,
                        "url": job_url,
                        "department": department,
                        "description": "",
                        "_oracle_base_url": base_url,
                        "_oracle_site_number": site_number,
                    }
                    all_jobs.append(job)

                logger.debug(f"  Oracle HCM page {page+1}: got {len(requisitions)} jobs (API total: {total_count})")

                if len(requisitions) < page_size:
                    break

                time.sleep(1)

            if all_jobs:
                logger.info(f"  Oracle HCM pagination: fetched {len(all_jobs)} total jobs across {page+1} page(s)")
                return all_jobs

        except Exception as e:
            logger.warning(f"Oracle HCM API failed for {company}: {e}")

        return self._scrape_generic(company, url)

    def _fetch_desc_oracle_hcm(self, job: Dict) -> str:
        """Fetch full description from Oracle HCM job detail API."""
        req_id = job.get("job_id", "")
        base_url = job.get("_oracle_base_url", "")
        site_number = job.get("_oracle_site_number", "")

        if not req_id or not base_url or not site_number:
            return self._fetch_desc_generic(job.get("url", ""))

        detail_url = (
            f"{base_url}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/{req_id}"
            f"?onlyData=true&expand=all&siteNumber={site_number}"
        )
        headers = {
            "Accept": "application/json",
            "Referer": job.get("url", base_url),
            "Origin": base_url,
        }

        try:
            resp = self.session.get(detail_url, timeout=self.timeout, headers=headers)
            if resp.status_code != 200:
                return ""

            if not resp.text.strip().startswith(("{", "[")):
                return ""

            data = resp.json()
            items = data.get("items", [])
            if not items:
                return ""

            detail = items[0] if items else {}
            parts = []
            for field in ("ExternalDescriptionStr", "ExternalQualificationsStr", "ExternalResponsibilitiesStr"):
                html_content = detail.get(field, "")
                if html_content:
                    text = BeautifulSoup(html_content, "html.parser").get_text(separator=" ", strip=True)
                    parts.append(text)

            return " ".join(parts)[:5000]
        except Exception as e:
            logger.debug(f"  Oracle HCM description fetch failed: {e}")
            return ""

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
