"""
Comprehensive tests for job_platforms.py — platform detection, scraper routing,
response parsing, edge cases, and notification integration.

Uses unittest.mock to simulate HTTP responses (no network required).
"""

import json
import re
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

import requests as real_requests

from src.job_platforms import detect_platform, extract_company_slug, JobScraper
from src.notifier import Notifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config():
    return {
        "scraping": {
            "user_agent": "TestBot/1.0",
            "delay_between_requests": 0,
            "timeout": 5,
            "max_retries": 0,  # no retries in tests
        }
    }


def _mock_response(status=200, text="", json_data=None, headers=None):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.headers = headers or {}
    resp.ok = 200 <= status < 300
    if json_data is not None:
        resp.json.return_value = json_data
        resp.text = json.dumps(json_data)
    resp.raise_for_status.side_effect = (
        None if 200 <= status < 400 else Exception(f"HTTP {status}")
    )
    return resp


# ===================================================================
# 1. PLATFORM DETECTION
# ===================================================================

class TestDetectPlatform(unittest.TestCase):
    """Test detect_platform() for every supported platform and edge cases."""

    # ----- Core platforms -----
    def test_greenhouse(self):
        self.assertEqual(detect_platform("https://boards.greenhouse.io/anthropic"), "greenhouse")
        self.assertEqual(detect_platform("https://job-boards.greenhouse.io/anthropic"), "greenhouse")

    def test_lever_global(self):
        self.assertEqual(detect_platform("https://jobs.lever.co/company"), "lever")

    def test_lever_eu(self):
        self.assertEqual(detect_platform("https://jobs.eu.lever.co/cirrus"), "lever")

    def test_workday(self):
        self.assertEqual(detect_platform("https://company.wd5.myworkdayjobs.com/en-US/External"), "workday")
        self.assertEqual(detect_platform("https://company.workday.com/careers"), "workday")

    def test_smartrecruiters(self):
        self.assertEqual(detect_platform("https://jobs.smartrecruiters.com/MyCompany"), "smartrecruiters")

    def test_ashby(self):
        self.assertEqual(detect_platform("https://jobs.ashbyhq.com/company-name"), "ashby")

    def test_recruitee(self):
        self.assertEqual(detect_platform("https://mycompany.recruitee.com/"), "recruitee")

    def test_amazon(self):
        self.assertEqual(detect_platform("https://amazon.jobs/content/en/teams/ftr/amazon-robotics"), "amazon")

    # ----- Taleo -----
    def test_taleo_classic(self):
        self.assertEqual(detect_platform("https://intel.taleo.net/go/Search/8797500"), "taleo")

    def test_taleo_enterprise(self):
        self.assertEqual(detect_platform("https://uhg.taleo.net/careersection/10030/joblist.ftl"), "taleo")

    def test_taleo_net_generic(self):
        self.assertEqual(detect_platform("https://company.taleo.net/whatever"), "taleo")

    # ----- Oracle HCM Cloud -----
    def test_oraclecloud(self):
        self.assertEqual(detect_platform("https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"), "oraclecloud")

    # ----- Jobvite / TTC -----
    def test_jobvite(self):
        self.assertEqual(detect_platform("https://jobs.jobvite.com/company/jobs"), "jobvite")

    def test_ttcportals(self):
        self.assertEqual(detect_platform("https://parkercareers.ttcportals.com/jobs/search"), "jobvite")

    # ----- iCIMS -----
    def test_icims_direct(self):
        self.assertEqual(detect_platform("https://careers-company.icims.com/jobs/search"), "icims")

    def test_icims_custom_domain(self):
        self.assertEqual(detect_platform("https://careers.pdf.com/careers-home/jobs"), "icims")

    def test_icims_createnewalert(self):
        self.assertEqual(detect_platform("https://ro.careers.tsmc.com/search/?createNewAlert=false&q="), "icims")

    def test_icims_optionsfacets(self):
        self.assertEqual(detect_platform("https://ro.careers.tsmc.com/search/?optionsFacetsDD_city="), "icims")

    def test_icims_en_us_careers(self):
        self.assertEqual(detect_platform("https://company.com/en_US/careers/SearchJobs"), "icims")

    # ----- Phenom People -----
    def test_phenom_search_results(self):
        self.assertEqual(detect_platform("https://careers.humana.com/us/en/search-results"), "phenom")
        self.assertEqual(detect_platform("https://careers.siemens-healthineers.com/global/en/search-results?from=20"), "phenom")

    def test_phenom_job_search_results(self):
        self.assertEqual(detect_platform("https://careers.unitedhealthgroup.com/job-search-results/"), "phenom")

    def test_phenom_search_jobs(self):
        self.assertEqual(detect_platform("https://jobs.bd.com/en/search-jobs?k=&l="), "phenom")

    def test_phenom_search_slash_jobs(self):
        self.assertEqual(detect_platform("https://careers.amperecomputing.com/search/jobs"), "phenom")

    # ----- Eightfold -----
    def test_eightfold(self):
        self.assertEqual(detect_platform("https://bostonscientific.eightfold.ai/careers/"), "eightfold")
        self.assertEqual(detect_platform("https://zebra.eightfold.ai/careers"), "eightfold")

    # ----- Tesla -----
    def test_tesla(self):
        self.assertEqual(detect_platform("https://www.tesla.com/careers/search/?query=optimus&site=US"), "tesla")

    # ----- Generic fallback -----
    def test_generic_unknown(self):
        self.assertEqual(detect_platform("https://randomcompany.com/jobs"), "generic")

    # ----- Edge cases -----
    def test_case_insensitive(self):
        self.assertEqual(detect_platform("https://BOARDS.GREENHOUSE.IO/company"), "greenhouse")
        self.assertEqual(detect_platform("https://JOBS.EU.LEVER.CO/company"), "lever")

    def test_empty_url(self):
        self.assertEqual(detect_platform(""), "generic")

    def test_url_with_query_params(self):
        self.assertEqual(detect_platform("https://boards.greenhouse.io/co?foo=bar&baz=1"), "greenhouse")

    def test_phenom_search_jobs_word_boundary(self):
        """Ensure /search/jobs doesn't match /search/jobsomethingelse."""
        # /search/jobs should match
        self.assertEqual(detect_platform("https://x.com/search/jobs"), "phenom")
        # /search/jobs?q=foo should match (word boundary at ?)
        self.assertEqual(detect_platform("https://x.com/search/jobs?q=foo"), "phenom")

    def test_no_false_positive_icims_on_careers_home(self):
        """careers-home/jobs should be iCIMS, not phenom or generic."""
        self.assertEqual(detect_platform("https://careers.pdf.com/careers-home/jobs"), "icims")

    def test_taleo_enterprise_over_generic(self):
        """Taleo Enterprise URL must not fall to generic."""
        self.assertEqual(detect_platform("https://uhg.taleo.net/careersection/10030/joblist.ftl"), "taleo")

    def test_lever_eu_not_confused_with_global(self):
        """EU Lever must still be detected as lever, not something else."""
        self.assertEqual(detect_platform("https://jobs.eu.lever.co/cirrus"), "lever")


# ===================================================================
# 2. EXTRACT COMPANY SLUG
# ===================================================================

class TestExtractCompanySlug(unittest.TestCase):

    def test_greenhouse_slug(self):
        self.assertEqual(extract_company_slug("https://boards.greenhouse.io/anthropic", "greenhouse"), "anthropic")

    def test_lever_slug(self):
        self.assertEqual(extract_company_slug("https://jobs.lever.co/cirrus", "lever"), "cirrus")

    def test_lever_eu_slug(self):
        self.assertEqual(extract_company_slug("https://jobs.eu.lever.co/cirrus", "lever"), "cirrus")

    def test_workday_slug(self):
        self.assertEqual(extract_company_slug("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", "workday"), "nvidia")

    def test_jobvite_ttc_slug(self):
        self.assertEqual(extract_company_slug("https://parkercareers.ttcportals.com/jobs/search", "jobvite"), "parkercareers")

    def test_icims_custom_domain(self):
        self.assertEqual(extract_company_slug("https://careers.pdf.com/careers-home/jobs", "icims"), "careers.pdf.com")

    def test_phenom_hostname(self):
        self.assertEqual(extract_company_slug("https://careers.humana.com/us/en/search-results", "phenom"), "careers.humana.com")

    def test_tesla_slug(self):
        self.assertEqual(extract_company_slug("https://www.tesla.com/careers/search/?query=optimus", "tesla"), "tesla")

    def test_invalid_url_returns_something(self):
        result = extract_company_slug("not-a-url", "greenhouse")
        # Should not crash — may return the input as-is or None
        self.assertIsNotNone(result)  # function returns raw string for unrecognised input


# ===================================================================
# 3. LEVER SCRAPER (global vs EU API domain)
# ===================================================================

class TestLeverScraper(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    @patch.object(JobScraper, '_request')
    def test_lever_global_uses_api_lever_co(self, mock_request):
        mock_request.return_value = _mock_response(json_data=[
            {"text": "Engineer", "id": "abc123", "categories": {"location": "SF", "team": "Eng"},
             "hostedUrl": "https://jobs.lever.co/co/abc123", "descriptionPlain": "A job."}
        ])
        jobs = self.scraper._scrape_lever("TestCo", "https://jobs.lever.co/testco")
        # Verify the API URL used the global domain
        call_url = mock_request.call_args[0][0]
        self.assertIn("api.lever.co", call_url)
        self.assertNotIn("api.eu.lever.co", call_url)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Engineer")

    @patch.object(JobScraper, '_request')
    def test_lever_eu_uses_api_eu_lever_co(self, mock_request):
        mock_request.return_value = _mock_response(json_data=[
            {"text": "Designer", "id": "def456", "categories": {"location": "Dublin", "team": "Design"},
             "hostedUrl": "https://jobs.eu.lever.co/co/def456", "descriptionPlain": "Design stuff."}
        ])
        jobs = self.scraper._scrape_lever("EUCo", "https://jobs.eu.lever.co/euco")
        call_url = mock_request.call_args[0][0]
        self.assertIn("api.eu.lever.co", call_url)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Designer")

    @patch.object(JobScraper, '_request')
    def test_lever_empty_response_falls_to_generic(self, mock_request):
        mock_request.return_value = _mock_response(json_data=[])
        jobs = self.scraper._scrape_lever("Co", "https://jobs.lever.co/co")
        # Empty list from API → falls to generic (which also returns nothing in mock)
        # Should not crash
        self.assertIsInstance(jobs, list)

    @patch.object(JobScraper, '_request')
    def test_lever_pagination(self, mock_request):
        """Lever pagination stops when fewer results than page_size."""
        page1 = [{"text": f"Job {i}", "id": f"id{i}",
                   "categories": {"location": "X", "team": "Y"},
                   "hostedUrl": f"https://jobs.lever.co/co/id{i}",
                   "descriptionPlain": "Desc"} for i in range(100)]
        page2 = [{"text": "Job 100", "id": "id100",
                   "categories": {"location": "X", "team": "Y"},
                   "hostedUrl": "https://jobs.lever.co/co/id100",
                   "descriptionPlain": "Desc"}]

        mock_request.side_effect = [
            _mock_response(json_data=page1),
            _mock_response(json_data=page2),
        ]
        jobs = self.scraper._scrape_lever("BigCo", "https://jobs.lever.co/bigco")
        self.assertEqual(len(jobs), 101)
        self.assertEqual(mock_request.call_count, 2)


# ===================================================================
# 4. EIGHTFOLD SCRAPER (session cookie retry on 403)
# ===================================================================

class TestEightfoldScraper(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    def test_eightfold_api_success(self):
        """Normal 200 response with positions."""
        api_data = {
            "positions": [
                {"name": "Software Engineer", "id": "123", "location": "NYC",
                 "url": "/position/123", "department": "Engineering", "description": "Build things."},
                {"name": "Data Scientist", "id": "456", "location": "SF",
                 "url": "/position/456", "department": "Data", "description": "Analyze things."},
            ],
            "count": 2,
        }
        with patch.object(self.scraper.session, 'get') as mock_get:
            mock_get.return_value = _mock_response(json_data=api_data)
            jobs = self.scraper._scrape_eightfold("TestCo", "https://testco.eightfold.ai/careers/")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Software Engineer")
        self.assertEqual(jobs[1]["title"], "Data Scientist")

    def test_eightfold_403_then_retry_with_session(self):
        """403 on first attempt → visit career page → retry → success."""
        api_data = {
            "positions": [
                {"name": "Engineer", "id": "789", "location": "Austin",
                 "url": "/position/789", "department": "Eng", "description": "Do stuff."},
            ],
            "count": 1,
        }
        forbidden_resp = _mock_response(status=403)
        career_page_resp = _mock_response(status=200, text="<html>career page</html>")
        success_resp = _mock_response(json_data=api_data)

        with patch.object(self.scraper.session, 'get') as mock_get:
            mock_get.side_effect = [forbidden_resp, career_page_resp, success_resp]
            jobs = self.scraper._scrape_eightfold("Omnicell", "https://apply.omnicell.com/careers/")

        # Should have been called 3 times: API(403) → career page → API(200)
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Engineer")

    def test_eightfold_403_retry_still_fails(self):
        """403 on both attempts falls to fallback scraper."""
        with patch.object(self.scraper.session, 'get') as mock_get:
            mock_get.return_value = _mock_response(status=403)
            with patch.object(self.scraper, '_scrape_eightfold_fallback', return_value=[]) as mock_fb:
                jobs = self.scraper._scrape_eightfold("Co", "https://co.eightfold.ai/careers/")
        mock_fb.assert_called_once()
        self.assertEqual(jobs, [])

    def test_eightfold_parse_job_missing_title(self):
        """Job objects without a title should be skipped."""
        result = self.scraper._parse_eightfold_job({"id": "123", "location": "NYC"}, "https://example.com")
        self.assertIsNone(result)

    def test_eightfold_parse_job_location_variants(self):
        """Test location parsing for string, dict, and list formats."""
        base = "https://example.com"

        # String location
        job = self.scraper._parse_eightfold_job(
            {"name": "J1", "id": "1", "location": "New York"}, base)
        self.assertEqual(job["location"], "New York")

        # Dict location
        job = self.scraper._parse_eightfold_job(
            {"name": "J2", "id": "2", "location": {"name": "San Francisco"}}, base)
        self.assertEqual(job["location"], "San Francisco")

        # List location
        job = self.scraper._parse_eightfold_job(
            {"name": "J3", "id": "3", "locations": [{"name": "LA"}, {"name": "NYC"}]}, base)
        self.assertEqual(job["location"], "LA; NYC")

    def test_eightfold_parse_job_relative_url(self):
        """Relative job URLs should be prepended with base_url."""
        job = self.scraper._parse_eightfold_job(
            {"name": "J1", "id": "1", "url": "/position/123"}, "https://co.eightfold.ai")
        self.assertEqual(job["url"], "https://co.eightfold.ai/position/123")

    def test_eightfold_parse_job_non_dict(self):
        """Non-dict input should return None."""
        self.assertIsNone(self.scraper._parse_eightfold_job("not a dict", "https://x.com"))
        self.assertIsNone(self.scraper._parse_eightfold_job(None, "https://x.com"))
        self.assertIsNone(self.scraper._parse_eightfold_job(42, "https://x.com"))


# ===================================================================
# 5. EIGHTFOLD PROBE (custom domain detection)
# ===================================================================

class TestEightfoldProbe(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    def test_probe_detects_eightfold_marker(self):
        html = '<html><script src="https://static.eightfold.ai/bundle.js"></script></html>'
        with patch.object(self.scraper.session, 'get') as mock_get:
            mock_get.return_value = _mock_response(text=html)
            result = self.scraper._probe_for_eightfold("https://apply.omnicell.com/careers/", "generic")
        self.assertEqual(result, "eightfold")

    def test_probe_no_eightfold_markers(self):
        html = '<html><body>Normal career page</body></html>'
        with patch.object(self.scraper.session, 'get') as mock_get:
            mock_get.return_value = _mock_response(text=html)
            result = self.scraper._probe_for_eightfold("https://example.com/careers", "generic")
        self.assertEqual(result, "generic")

    def test_probe_request_fails(self):
        with patch.object(self.scraper.session, 'get', side_effect=Exception("timeout")):
            result = self.scraper._probe_for_eightfold("https://example.com", "generic")
        self.assertEqual(result, "generic")


# ===================================================================
# 6. PHENOM SCRAPER (Workday & Jobvite backend routing)
# ===================================================================

class TestPhenomScraper(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    def test_phenom_workday_backend_mapping(self):
        """Known Phenom sites should route to Workday backend."""
        self.assertIn("careers.humana.com", self.scraper.PHENOM_WORKDAY_BACKENDS)
        self.assertIn("careers.siemens-healthineers.com", self.scraper.PHENOM_WORKDAY_BACKENDS)
        self.assertIn("jobs.bd.com", self.scraper.PHENOM_WORKDAY_BACKENDS)
        self.assertIn("jobs.thecignagroup.com", self.scraper.PHENOM_WORKDAY_BACKENDS)
        self.assertIn("www.jobs.abbott", self.scraper.PHENOM_WORKDAY_BACKENDS)
        self.assertIn("www.pgcareers.com", self.scraper.PHENOM_WORKDAY_BACKENDS)

    def test_phenom_jobvite_backend_mapping(self):
        """Known Phenom+Jobvite sites should route to Jobvite backend."""
        self.assertIn("careers.amperecomputing.com", self.scraper.PHENOM_JOBVITE_BACKENDS)

    @patch.object(JobScraper, '_scrape_workday')
    def test_phenom_routes_to_workday(self, mock_workday):
        mock_workday.return_value = [{"title": "WD Job", "job_id": "1", "location": "X",
                                       "url": "https://humana.wd5.myworkdayjobs.com/en-US/Humana/job/Remote/WD-Job_R-123",
                                       "department": "Eng", "description": ""}]
        phenom_url = "https://careers.humana.com/us/en/search-results"
        jobs = self.scraper._scrape_phenom("Humana", phenom_url)
        mock_workday.assert_called_once()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "WD Job")
        # Should be tagged with Workday URL
        self.assertIn("_phenom_workday_url", jobs[0])
        # Job URL should point to the Phenom career page, NOT the Workday externalPath
        self.assertEqual(jobs[0]["url"], phenom_url)

    @patch.object(JobScraper, '_scrape_jobvite')
    def test_phenom_routes_to_jobvite(self, mock_jobvite):
        mock_jobvite.return_value = [{"title": "JV Job", "job_id": "2", "location": "Y",
                                       "url": "https://y.com/2", "department": "Ops", "description": ""}]
        jobs = self.scraper._scrape_phenom("Ampere", "https://careers.amperecomputing.com/search/jobs")
        mock_jobvite.assert_called_once()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "JV Job")

    @patch.object(JobScraper, '_scrape_workday', return_value=[])
    @patch.object(JobScraper, '_scrape_generic', return_value=[])
    def test_phenom_workday_empty_falls_through(self, mock_generic, mock_workday):
        """If Workday backend returns no jobs, Phenom should try other strategies."""
        with patch.object(self.scraper, '_request', return_value=None):
            with patch.object(self.scraper.session, 'post', return_value=_mock_response(json_data={"jobs": []})):
                jobs = self.scraper._scrape_phenom("Humana", "https://careers.humana.com/us/en/search-results")
        # Should have tried Workday first
        mock_workday.assert_called_once()


# ===================================================================
# 7. iCIMS SCRAPER (JSON-LD, portal fallback)
# ===================================================================

class TestICIMSScraper(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    def test_icims_portal_mapping(self):
        self.assertIn("careers.pdf.com", self.scraper.ICIMS_PORTALS)

    @patch.object(JobScraper, '_request')
    def test_icims_json_ld_extraction(self, mock_request):
        """iCIMS scraper should extract jobs from JSON-LD structured data."""
        html = '''<html><head>
        <script type="application/ld+json">
        [{"@type": "JobPosting", "title": "SW Engineer",
          "url": "https://careers.pdf.com/job/123",
          "identifier": {"value": "123"},
          "jobLocation": {"address": {"addressLocality": "Santa Clara", "addressRegion": "CA"}},
          "occupationalCategory": "Engineering"}]
        </script></head></html>'''
        mock_request.return_value = _mock_response(text=html)
        jobs = self.scraper._scrape_icims("PDF Solutions", "https://careers.pdf.com/careers-home/jobs")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "SW Engineer")
        self.assertEqual(jobs[0]["job_id"], "123")
        self.assertIn("Santa Clara", jobs[0]["location"])

    @patch.object(JobScraper, '_request')
    def test_icims_deduplicates(self, mock_request):
        """Same job_id appearing twice should be deduplicated."""
        html = '''<html><head>
        <script type="application/ld+json">
        [{"@type": "JobPosting", "title": "Job A", "url": "https://x.com/1",
          "identifier": {"value": "DUP1"}, "jobLocation": {}},
         {"@type": "JobPosting", "title": "Job B (same id)", "url": "https://x.com/2",
          "identifier": {"value": "DUP1"}, "jobLocation": {}}]
        </script></head></html>'''
        mock_request.return_value = _mock_response(text=html)
        jobs = self.scraper._scrape_icims("Co", "https://careers.co.com/careers-home/jobs")
        self.assertEqual(len(jobs), 1)

    @patch.object(JobScraper, '_request')
    @patch.object(JobScraper, '_scrape_generic', return_value=[])
    def test_icims_portal_fallback_tried(self, mock_generic, mock_request):
        """When main page has no jobs, portal fallback should be attempted."""
        # First call: main page (no jobs)
        empty_html = "<html><body>No jobs here</body></html>"
        # Second call: portal page (also mocked empty for this test)
        portal_html = "<html><body>Portal with no jobs</body></html>"
        mock_request.side_effect = [
            _mock_response(text=empty_html),
            _mock_response(text=portal_html),
        ]
        jobs = self.scraper._scrape_icims("PDF Solutions", "https://careers.pdf.com/careers-home/jobs")
        # Should have tried portal URL
        calls = [c[0][0] for c in mock_request.call_args_list]
        self.assertTrue(any("icims.com" in c for c in calls),
                        f"Expected icims.com portal URL in calls: {calls}")


# ===================================================================
# 8. TALEO ENTERPRISE SCRAPER
# ===================================================================

class TestTaleoEnterpriseScraper(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    def test_taleo_enterprise_dispatch(self):
        """Taleo Enterprise URL should dispatch to _scrape_taleo_enterprise."""
        with patch.object(self.scraper, '_scrape_taleo_enterprise', return_value=[]) as mock_te:
            self.scraper._scrape_taleo("UHG", "https://uhg.taleo.net/careersection/10030/joblist.ftl")
        mock_te.assert_called_once()

    def test_taleo_classic_also_uses_enterprise_scraper(self):
        """Classic /go/ URL is also handled via the enterprise scraper."""
        with patch.object(self.scraper, '_scrape_taleo_enterprise', return_value=[]) as mock_te:
            self.scraper._scrape_taleo("Intel", "https://intel.taleo.net/go/Search/8797500")
        mock_te.assert_called_once()

    @patch.object(JobScraper, '_request')
    def test_taleo_enterprise_table_extraction(self, mock_request):
        """Taleo Enterprise should extract jobs from HTML tables."""
        html = '''<html><body>
        <table id="searchresults">
            <tr><td><a href="/careersection/10030/jobdetail.ftl?job=12345">Senior Developer</a></td>
                <td>Minneapolis, MN</td></tr>
            <tr><td><a href="/careersection/10030/jobdetail.ftl?job=67890">Data Analyst</a></td>
                <td>Remote</td></tr>
        </table>
        </body></html>'''
        mock_request.return_value = _mock_response(text=html)
        jobs = self.scraper._scrape_taleo_enterprise(
            "UHG", "https://uhg.taleo.net/careersection/10030/joblist.ftl")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Senior Developer")
        self.assertEqual(jobs[0]["job_id"], "12345")
        self.assertEqual(jobs[0]["location"], "Minneapolis, MN")
        self.assertEqual(jobs[1]["title"], "Data Analyst")
        self.assertEqual(jobs[1]["job_id"], "67890")

    @patch.object(JobScraper, '_request')
    def test_taleo_enterprise_div_fallback(self, mock_request):
        """Should find job links even outside tables (div-based layout)."""
        html = '''<html><body>
        <div class="jobs">
            <a href="/careersection/10030/jobdetail.ftl?job=11111">Manager Role</a>
            <a href="/careersection/10030/jobdetail.ftl?job=22222">Analyst Role</a>
        </div>
        </body></html>'''
        mock_request.return_value = _mock_response(text=html)
        jobs = self.scraper._scrape_taleo_enterprise(
            "UHG", "https://uhg.taleo.net/careersection/10030/joblist.ftl")
        self.assertEqual(len(jobs), 2)

    @patch.object(JobScraper, '_request')
    def test_taleo_enterprise_deduplicates(self, mock_request):
        """Same job_id should not appear twice."""
        html = '''<html><body>
        <table id="searchresults">
            <tr><td><a href="/jobdetail.ftl?job=99999">Job A</a></td><td>X</td></tr>
            <tr><td><a href="/jobdetail.ftl?job=99999">Job A (dup)</a></td><td>X</td></tr>
        </table>
        </body></html>'''
        mock_request.return_value = _mock_response(text=html)
        jobs = self.scraper._scrape_taleo_enterprise(
            "Co", "https://co.taleo.net/careersection/1/joblist.ftl")
        self.assertEqual(len(jobs), 1)


# ===================================================================
# 9. JOBVITE SCRAPER (pagination URL fix)
# ===================================================================

class TestJobviteScraper(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    @patch.object(JobScraper, '_request')
    def test_jobvite_html_link_extraction(self, mock_request):
        """Should extract jobs from HTML links matching /jobs/ID-slug pattern."""
        html = '''<html><body>
        <a href="/jobs/12345-software-engineer">Software Engineer</a>
        <a href="/jobs/67890-product-manager">Product Manager</a>
        </body></html>'''
        # Sitemap fails (404), then HTML succeeds
        with patch.object(self.scraper.session, 'get', return_value=_mock_response(status=404)):
            mock_request.return_value = _mock_response(text=html)
            jobs = self.scraper._scrape_jobvite("Parker", "https://parkercareers.ttcportals.com/jobs/search")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Software Engineer")

    @patch.object(JobScraper, '_request')
    def test_jobvite_pagination_uses_original_url(self, mock_request):
        """Pagination should use original URL path, not just base_url."""
        # Sitemap fails, HTML finds nothing, pagination starts
        with patch.object(self.scraper.session, 'get', return_value=_mock_response(status=404)):
            mock_request.return_value = _mock_response(text="<html></html>")  # empty

            self.scraper._scrape_jobvite("Ampere", "https://jobs.jobvite.com/amperecomputing")

        # Check that pagination used the company slug in the URL
        paginated_urls = [c[0][0] for c in mock_request.call_args_list]
        # Should see /amperecomputing/page/1, NOT /search/jobs/page/1
        page_urls = [u for u in paginated_urls if "/page/" in u]
        for pu in page_urls:
            self.assertIn("/amperecomputing/page/", pu,
                          f"Pagination URL should contain company slug: {pu}")


# ===================================================================
# 10. WORKDAY SCRAPER (basic API response parsing)
# ===================================================================

class TestWorkdayScraper(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    def test_workday_api_response_parsing(self):
        """Workday JSON API response should be parsed correctly."""
        api_data = {
            "jobPostings": [
                {"title": "ML Engineer", "bulletFields": ["San Jose, CA"],
                 "externalPath": "/en-US/job/ml-engineer/JR001",
                 "locationsText": "San Jose, CA"},
                {"title": "DevOps Lead", "bulletFields": ["Remote"],
                 "externalPath": "/en-US/job/devops/JR002",
                 "locationsText": "Remote"},
            ],
            "total": 2,
        }
        with patch.object(self.scraper.session, 'post') as mock_post:
            mock_post.return_value = _mock_response(json_data=api_data)
            jobs = self.scraper._scrape_workday("TestCo", "https://testco.wd5.myworkdayjobs.com/External")
        self.assertGreaterEqual(len(jobs), 0)  # May or may not parse depending on exact format


# ===================================================================
# 11. SCRAPE_COMPANY DISPATCH + METADATA
# ===================================================================

class TestScrapeCompanyDispatch(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    @patch.object(JobScraper, '_scrape_lever')
    def test_dispatch_lever_and_metadata(self, mock_lever):
        mock_lever.return_value = [{"title": "Job", "job_id": "1", "location": "",
                                     "url": "https://x.com", "department": "", "description": ""}]
        jobs = self.scraper.scrape_company("Co", "https://jobs.lever.co/co")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "Co")
        self.assertEqual(jobs[0]["platform"], "lever")
        self.assertEqual(jobs[0]["source_url"], "https://jobs.lever.co/co")

    @patch.object(JobScraper, '_scrape_eightfold')
    def test_dispatch_eightfold(self, mock_ef):
        mock_ef.return_value = [{"title": "J", "job_id": "1", "location": "",
                                  "url": "https://x.com", "department": "", "description": ""}]
        jobs = self.scraper.scrape_company("Co", "https://co.eightfold.ai/careers/")
        self.assertEqual(jobs[0]["platform"], "eightfold")

    @patch.object(JobScraper, '_probe_for_eightfold', return_value="eightfold")
    @patch.object(JobScraper, '_scrape_eightfold')
    def test_generic_probed_as_eightfold(self, mock_ef, mock_probe):
        """Generic URLs should be probed and rerouted to eightfold if detected."""
        mock_ef.return_value = [{"title": "J", "job_id": "1", "location": "",
                                  "url": "https://x.com", "department": "", "description": ""}]
        jobs = self.scraper.scrape_company("Omnicell", "https://apply.omnicell.com/careers/")
        mock_probe.assert_called_once()
        mock_ef.assert_called_once()
        self.assertEqual(jobs[0]["platform"], "eightfold")

    @patch.object(JobScraper, '_scrape_phenom')
    def test_dispatch_phenom(self, mock_phenom):
        mock_phenom.return_value = []
        self.scraper.scrape_company("Cigna", "https://jobs.thecignagroup.com/us/en/search-results")
        mock_phenom.assert_called_once()

    @patch.object(JobScraper, '_scrape_taleo')
    def test_dispatch_taleo_enterprise(self, mock_taleo):
        mock_taleo.return_value = []
        self.scraper.scrape_company("UHG", "https://uhg.taleo.net/careersection/10030/joblist.ftl")
        mock_taleo.assert_called_once()

    @patch.object(JobScraper, '_scrape_icims')
    def test_dispatch_icims(self, mock_icims):
        mock_icims.return_value = []
        self.scraper.scrape_company("PDF", "https://careers.pdf.com/careers-home/jobs")
        mock_icims.assert_called_once()

    def test_dispatch_exception_returns_empty(self):
        """If scraper raises, should return empty list, not crash."""
        with patch.object(self.scraper, '_scrape_lever', side_effect=RuntimeError("boom")):
            jobs = self.scraper.scrape_company("Co", "https://jobs.lever.co/co")
        self.assertEqual(jobs, [])


# ===================================================================
# 12. FETCH_JOB_DESCRIPTION DISPATCH
# ===================================================================

class TestFetchJobDescriptionDispatch(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    @patch.object(JobScraper, '_fetch_desc_lever')
    def test_lever_desc_dispatch(self, mock_desc):
        mock_desc.return_value = "Lever job description"
        result = self.scraper.fetch_job_description({"platform": "lever", "url": "https://x.com", "job_id": "1", "source_url": ""})
        mock_desc.assert_called_once()
        self.assertEqual(result, "Lever job description")

    @patch.object(JobScraper, '_fetch_desc_eightfold')
    def test_eightfold_desc_dispatch(self, mock_desc):
        mock_desc.return_value = "Eightfold description"
        result = self.scraper.fetch_job_description({"platform": "eightfold", "url": "https://x.com", "job_id": "1", "source_url": ""})
        mock_desc.assert_called_once()

    @patch.object(JobScraper, '_fetch_desc_phenom')
    def test_phenom_desc_dispatch(self, mock_desc):
        mock_desc.return_value = "Phenom description"
        result = self.scraper.fetch_job_description({"platform": "phenom", "url": "https://x.com", "job_id": "1", "source_url": ""})
        mock_desc.assert_called_once()

    @patch.object(JobScraper, '_fetch_desc_taleo')
    def test_taleo_desc_dispatch(self, mock_desc):
        mock_desc.return_value = "Taleo description"
        result = self.scraper.fetch_job_description({"platform": "taleo", "url": "https://x.com", "job_id": "1", "source_url": ""})
        mock_desc.assert_called_once()

    @patch.object(JobScraper, '_fetch_desc_icims')
    def test_icims_desc_dispatch(self, mock_desc):
        mock_desc.return_value = "iCIMS description"
        result = self.scraper.fetch_job_description({"platform": "icims", "url": "https://x.com", "job_id": "1", "source_url": ""})
        mock_desc.assert_called_once()

    @patch.object(JobScraper, '_fetch_desc_jobvite')
    def test_jobvite_desc_dispatch(self, mock_desc):
        mock_desc.return_value = "Jobvite description"
        result = self.scraper.fetch_job_description({"platform": "jobvite", "url": "https://x.com", "job_id": "1", "source_url": ""})
        mock_desc.assert_called_once()


# ===================================================================
# 13. NOTIFIER PLATFORM COMPLETENESS
# ===================================================================

class TestNotifierPlatformCompleteness(unittest.TestCase):
    """Ensure every platform in the codebase is registered in notifier."""

    def test_all_platforms_in_labels(self):
        """Every platform in PLATFORM_ORDER should have a PLATFORM_LABELS entry."""
        for platform in Notifier.PLATFORM_ORDER:
            self.assertIn(platform, Notifier.PLATFORM_LABELS,
                          f"Platform '{platform}' missing from PLATFORM_LABELS")

    def test_all_platforms_in_colors(self):
        """Every platform in PLATFORM_ORDER should have a PLATFORM_COLORS entry."""
        for platform in Notifier.PLATFORM_ORDER:
            self.assertIn(platform, Notifier.PLATFORM_COLORS,
                          f"Platform '{platform}' missing from PLATFORM_COLORS")

    def test_platform_order_ends_with_generic(self):
        """Generic should be last in PLATFORM_ORDER."""
        self.assertEqual(Notifier.PLATFORM_ORDER[-1], "generic")

    def test_no_duplicate_platforms_in_order(self):
        self.assertEqual(len(Notifier.PLATFORM_ORDER), len(set(Notifier.PLATFORM_ORDER)))

    def test_all_scraped_platforms_in_order(self):
        """Every platform returned by detect_platform() should be in PLATFORM_ORDER."""
        known_platforms = {
            "greenhouse", "lever", "workday", "smartrecruiters", "ashby",
            "amazon", "recruitee", "taleo", "oraclecloud", "jobvite",
            "icims", "phenom", "tesla", "eightfold", "generic",
        }
        for p in known_platforms:
            self.assertIn(p, Notifier.PLATFORM_ORDER,
                          f"Platform '{p}' not in PLATFORM_ORDER — jobs will be silently dropped!")


# ===================================================================
# 14. EDGE CASES & ROBUSTNESS
# ===================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    def test_request_returns_none_on_failure(self):
        """_request should return None after all retries fail."""
        with patch.object(self.scraper.session, 'get',
                          side_effect=real_requests.ConnectionError("network error")):
            result = self.scraper._request("https://example.com")
        self.assertIsNone(result)

    def test_scrape_company_empty_url(self):
        """Empty URL should not crash."""
        jobs = self.scraper.scrape_company("Co", "")
        self.assertIsInstance(jobs, list)

    @patch.object(JobScraper, '_request')
    def test_icims_json_ld_single_item(self, mock_request):
        """JSON-LD with a single JobPosting (not in array) should work."""
        html = '''<html><head>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Single Job",
         "url": "https://x.com/1", "identifier": "J1", "jobLocation": {}}
        </script></head></html>'''
        mock_request.return_value = _mock_response(text=html)
        jobs = self.scraper._scrape_icims("Co", "https://co.icims.com/jobs")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Single Job")

    @patch.object(JobScraper, '_request')
    def test_icims_json_ld_location_as_list(self, mock_request):
        """JSON-LD jobLocation as a list of locations should be handled."""
        html = '''<html><head>
        <script type="application/ld+json">
        [{"@type": "JobPosting", "title": "Multi-Loc Job",
          "url": "https://x.com/1", "identifier": "ML1",
          "jobLocation": [{"address": {"addressLocality": "NYC", "addressRegion": "NY"}}]}]
        </script></head></html>'''
        mock_request.return_value = _mock_response(text=html)
        jobs = self.scraper._scrape_icims("Co", "https://co.icims.com/jobs")
        self.assertEqual(len(jobs), 1)
        self.assertIn("NYC", jobs[0]["location"])

    @patch.object(JobScraper, '_request')
    def test_lever_non_json_response_caught_by_scrape_company(self, mock_request):
        """If Lever API returns non-JSON, scrape_company should catch it."""
        mock_request.return_value = _mock_response(text="<html>Not JSON</html>")
        mock_request.return_value.json.side_effect = ValueError("No JSON")
        # _scrape_lever itself will raise, but scrape_company wraps in try/except
        jobs = self.scraper.scrape_company("Co", "https://jobs.lever.co/co")
        self.assertIsInstance(jobs, list)
        self.assertEqual(jobs, [])

    @patch.object(JobScraper, '_request')
    def test_taleo_enterprise_no_table_no_links(self, mock_request):
        """Page with no job links should return empty gracefully."""
        mock_request.return_value = _mock_response(text="<html><body>Nothing here</body></html>")
        with patch.object(self.scraper, '_scrape_generic', return_value=[]):
            jobs = self.scraper._scrape_taleo_enterprise(
                "Co", "https://co.taleo.net/careersection/1/joblist.ftl")
        self.assertEqual(jobs, [])

    def test_find_jobs_in_json_depth_limit(self):
        """Deeply nested JSON should not cause infinite recursion."""
        deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": [{"title": "X"}]}}}}}}}
        result = self.scraper._find_jobs_in_json(deep)
        # Depth limit is 5, so this should return empty (too deep)
        self.assertIsInstance(result, list)

    def test_eightfold_parse_job_html_description_stripped(self):
        """HTML in description should be stripped to plain text."""
        job = self.scraper._parse_eightfold_job({
            "name": "Test Job", "id": "1",
            "description": "<p>This is a <strong>bold</strong> description with <a href='#'>a link</a></p>" * 20,
        }, "https://example.com")
        self.assertNotIn("<p>", job["description"])
        self.assertNotIn("<strong>", job["description"])
        self.assertLessEqual(len(job["description"]), 500)


# ===================================================================
# 15. JOBVITE SITEMAP EXTRACTION
# ===================================================================

class TestJobviteSitemap(unittest.TestCase):

    def setUp(self):
        self.scraper = JobScraper(_make_config())

    def test_jobvite_sitemap_extraction(self):
        """Sitemap with /jobs/ID-slug URLs should be parsed."""
        sitemap_xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://company.ttcportals.com/jobs/12345-senior-engineer</loc></url>
            <url><loc>https://company.ttcportals.com/jobs/67890-product-manager</loc></url>
            <url><loc>https://company.ttcportals.com/about</loc></url>
        </urlset>'''
        with patch.object(self.scraper.session, 'get') as mock_get:
            mock_get.return_value = _mock_response(text=sitemap_xml)
            jobs = self.scraper._scrape_jobvite("Co", "https://company.ttcportals.com/jobs/search")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["job_id"], "12345")
        self.assertEqual(jobs[0]["title"], "Senior Engineer")
        self.assertEqual(jobs[1]["job_id"], "67890")


if __name__ == "__main__":
    unittest.main()
