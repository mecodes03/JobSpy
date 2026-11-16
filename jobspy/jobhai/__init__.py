from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from jobspy.jobhai.constant import (
    city_aliases,
    default_city,
    job_type_labels,
    jobs_per_page,
)
from jobspy.jobhai.model import JobHaiJob
from jobspy.model import (
    Compensation,
    CompensationInterval,
    Country,
    DescriptionFormat,
    JobPost,
    JobType,
    Location,
    Scraper,
    ScraperInput,
)
from jobspy.util import (
    TLSRotating,
    check_status,
    create_session,
    description_fields,
    too_old,
    utc_date,
)

work_modes = {
    "FIELD_JOB": "Field job",
    "WORK_FROM_HOME": "Remote",
    "WORK_FROM_OFFICE": "Work from office",
}


class JobHai(Scraper):
    base_url = "https://www.jobhai.com"
    delay = (2, 5)

    def scrape(self, scraper_input: ScraperInput) -> list[JobPost]:
        self.scraper_input = scraper_input
        self.session = create_session(
            TLSRotating(scraper_input.proxies),
            scraper_input,
            {"accept": "text/html,application/xhtml+xml"},
        )
        if scraper_input.easy_apply:
            self.warn("easy_apply isn't supported, ignoring it")
        if scraper_input.job_type and scraper_input.job_type not in set(
            job_type_labels.values()
        ):
            self.warn(
                f"job_type {scraper_input.job_type.value} isn't supported, ignoring it"
            )
        self.city = self._city_slug(scraper_input.location)
        if not self.city:
            self.city = default_city
            self.warn("Job Hai searches by city, so defaulting to Delhi")

        job_list: list[JobPost] = []
        seen: set[int] = set()
        first_page = scraper_input.offset // jobs_per_page + 1
        skip = scraper_input.offset % jobs_per_page
        page = first_page

        while len(job_list) < scraper_input.results_wanted:
            if page > first_page:
                time.sleep(random.uniform(*self.delay))
            self.log.info(f"search page: {page}")
            jobs = self._fetch_jobs(page)
            if not jobs:
                break

            for raw in jobs[skip if page == first_page else 0 :]:
                try:
                    job = JobHaiJob.model_validate(raw)
                except Exception as e:
                    self.log.warning(f"skipping job: {e}")
                    continue
                if job.job_id in seen:
                    continue
                seen.add(job.job_id)
                try:
                    job_post = self._process_job(job)
                except Exception as e:
                    self.log.warning(f"skipping job: {e}")
                    continue
                if job_post:
                    job_list.append(job_post)
                    if len(job_list) >= scraper_input.results_wanted:
                        break
            page += 1

        return job_list

    def _page_url(self, page: int) -> str:
        if page == 1:
            return f"{self.base_url}/jobs-in-{self.city}-cty"
        return f"{self.base_url}/jobs-in-{self.city}-page-{page}-cty"

    def _fetch_jobs(self, page: int) -> list[dict[str, object]] | None:
        term = self.scraper_input.search_term
        params = {"search": term} if term else None
        try:
            response = self.session.get(
                self._page_url(page), params=params, allow_redirects=True
            )
            if response.status_code == 404 and page == 1 and self.city != default_city:
                self.warn(
                    f"location '{self.scraper_input.location}' not found, "
                    "searching Delhi"
                )
                self.city = default_city
                response = self.session.get(
                    self._page_url(page), params=params, allow_redirects=True
                )
            check_status(response)
            return _json_array(_rsc_text(response.text), '"jobs_data":')
        except Exception as e:
            self.fail(str(e))
            return None

    @staticmethod
    def _city_slug(location: str | None) -> str | None:
        if not location:
            return None
        city = location.split(",")[0].strip().lower()
        city = city_aliases.get(city, city)
        city = re.sub(r"[^a-z0-9]+", "-", city).strip("-")
        return city or None

    def _process_job(self, job: JobHaiJob) -> JobPost | None:
        posted = _timestamp(job.live_date)
        if posted and too_old(posted, self.scraper_input.hours_old):
            return None

        is_remote = bool(job.is_wfh) or job.job_type_location == "WORK_FROM_HOME"
        if self.scraper_input.is_remote and not is_remote:
            return None

        job_types = _job_types(job.job_type)
        requested = self.scraper_input.job_type
        if (
            requested
            and requested in job_type_labels.values()
            and requested not in job_types
        ):
            return None

        job_url = urljoin(self.base_url, job.page_url)
        details = description_fields(
            job.job_summary, self.scraper_input.description_format
        )
        if self.scraper_input.fetch_description:
            page = self._fetch_details(job_url)
            timestamp = page.pop("posted_timestamp", None)
            if isinstance(timestamp, float):
                posted = timestamp
            if too_old(posted or 0, self.scraper_input.hours_old):
                return None
            details |= {name: value for name, value in page.items() if value}

        return JobPost(
            id=f"jh-{job.job_id}",
            title=job.job_title,
            company=job.company_name,
            company_logo=_logo(job.brand_logo),
            location=_location(job.job_location),
            job_url=job_url,
            date_posted=utc_date(posted),
            job_type=job_types or None,
            is_remote=is_remote,
            work_from_home_type=work_modes.get(job.job_type_location or ""),
            **self._parse_salary(job).model_dump(),
            job_function=job.category_name,
            company_industry=job.industry or None,
            skills=None,
            experience_range=_experience(job),
            vacancy_count=job.no_of_openings,
        ).model_copy(update=details)

    @staticmethod
    def _parse_salary(job: JobHaiJob) -> Compensation:
        return Compensation(
            interval=CompensationInterval.MONTHLY,
            min_amount=float(job.min_sal) if job.min_sal else None,
            max_amount=float(job.max_sal) if job.max_sal else None,
            currency="INR" if job.min_sal or job.max_sal else None,
        )

    def _fetch_details(self, job_url: str) -> dict[str, object]:
        try:
            response = self.session.get(job_url, allow_redirects=True)
            check_status(response)
            soup = BeautifulSoup(response.text, "html.parser")
            for script in soup.select('script[type="application/ld+json"]'):
                try:
                    data = json.loads(script.string or "")
                except ValueError:
                    continue
                if not isinstance(data, dict) or data.get("@type") != "JobPosting":
                    continue
                return _job_posting_fields(data, self.scraper_input.description_format)
        except Exception as e:
            self.log.warning(f"job page: {e}")
        return {}


def _rsc_text(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    return "".join(json.loads(f'"{chunk}"') for chunk in chunks)


def _json_array(text: str, marker: str) -> list[dict[str, object]]:
    start = text.find(marker)
    if start < 0:
        return []
    start = text.find("[", start + len(marker))
    if start < 0:
        return []
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                data: list[dict[str, object]] = json.loads(text[start : index + 1])
                return data
    return []


def _timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _job_types(value: str | None) -> list[JobType]:
    if not value:
        return []
    return [
        job_type_labels[part.strip()]
        for part in value.split("/")
        if part.strip() in job_type_labels
    ]


def _location(address: str | None) -> Location | None:
    if not address:
        return None
    address = re.sub(r"\s*\([^)]*\)\s*$", "", address.strip())
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if parts and parts[-1].lower() == "india":
        parts.pop()
    city = parts[-1] if parts else None
    if city and city.lower() in {"remote", "work from home"}:
        city = None
    return Location(city=city, country=Country.INDIA)


def _logo(url: str | None) -> str | None:
    if not url or "dummy-job-logo" in url:
        return None
    return url


def _experience(job: JobHaiJob) -> str | None:
    if job.min_exp is not None and job.max_exp is not None:
        if not job.min_exp and not job.max_exp:
            return None
        return f"{job.min_exp / 12:g} - {job.max_exp / 12:g} years"
    return job.exp_text


def _job_posting_fields(
    data: dict[str, Any], description_format: DescriptionFormat
) -> dict[str, object]:
    fields = description_fields(data.get("description"), description_format)
    result: dict[str, object] = dict(fields)
    date_posted = data.get("datePosted")
    if isinstance(date_posted, str):
        try:
            posted = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            result["posted_timestamp"] = posted.timestamp()
            result["date_posted"] = utc_date(posted.timestamp())
    employment = data.get("employmentType")
    types = employment if isinstance(employment, list) else [employment]
    job_types = [job_type_labels.get(str(value).title()) for value in types]
    job_types = [job_type for job_type in job_types if job_type]
    if job_types:
        result["job_type"] = job_types
    salary = data.get("baseSalary")
    if isinstance(salary, dict):
        value = salary.get("value")
        if isinstance(value, dict):
            min_value = value.get("minValue")
            max_value = value.get("maxValue")
            if isinstance(min_value, (int, float)):
                result["min_amount"] = float(min_value)
            if isinstance(max_value, (int, float)):
                result["max_amount"] = float(max_value)
            if salary.get("currency"):
                result["currency"] = salary["currency"]
    skills = data.get("skills")
    if isinstance(skills, list):
        result["skills"] = [str(skill) for skill in skills if skill]
    if data.get("industry"):
        result["company_industry"] = data["industry"]
    if data.get("occupationalCategory"):
        result["job_function"] = data["occupationalCategory"]
    return result
