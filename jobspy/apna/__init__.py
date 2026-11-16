from __future__ import annotations

import json
import math
import random
import re
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from jobspy.apna.constant import (
    city_aliases,
    job_type_labels,
    jobs_per_page,
    pay_intervals,
)
from jobspy.apna.model import ApnaFeedJob, ApnaJobData
from jobspy.model import (
    CompensationInterval,
    Country,
    DescriptionFormat,
    JobPost,
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


class Apna(Scraper):
    base_url = "https://apna.co"
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
        if scraper_input.hours_old and not scraper_input.fetch_description:
            self.warn(
                "hours_old needs fetch_description on Apna; the search cards "
                "have no posting date, ignoring it"
            )
        if scraper_input.job_type and scraper_input.job_type not in set(
            job_type_labels.values()
        ):
            self.warn(
                f"job_type {scraper_input.job_type.value} isn't supported, ignoring it"
            )
        self.city = self._city_slug(scraper_input.location)
        self.term = _slug(scraper_input.search_term)

        url = self._search_url()
        job_list: list[JobPost] = []
        seen: set[str] = set()
        first_page = scraper_input.offset // jobs_per_page + 1
        skip = scraper_input.offset % jobs_per_page
        page = first_page
        last_page = first_page

        while len(job_list) < scraper_input.results_wanted and page <= last_page:
            if page > first_page:
                time.sleep(random.uniform(*self.delay))
            self.log.info(f"search page: {page}")
            try:
                response = self.session.get(
                    url, params={"page": page}, allow_redirects=True
                )
                for _ in range(2):
                    if response.status_code != 404:
                        break
                    if self.term:
                        self.warn(
                            f"Apna has no page for '{scraper_input.search_term}', "
                            "searching its general listings"
                        )
                        self.term = None
                    elif self.city:
                        self.warn(
                            f"location '{scraper_input.location}' not found, "
                            "searching all of India"
                        )
                        self.city = None
                    else:
                        break
                    url = self._search_url()
                    response = self.session.get(
                        url, params={"page": page}, allow_redirects=True
                    )
                check_status(response)
                text = _rsc_text(response.text)
                jobs = _json_array(text, '"jobsList":')
                total = _int_field(text, "totalJobsCount")
                if total is not None:
                    last_page = max(1, math.ceil(total / jobs_per_page))
            except Exception as e:
                self.fail(str(e))
                break
            if not jobs:
                break

            for raw in jobs[skip if page == first_page else 0 :]:
                try:
                    job = self._process_job(raw)
                except Exception as e:
                    self.log.warning(f"skipping job: {e}")
                    continue
                if job and job.id not in seen:
                    seen.add(str(job.id))
                    job_list.append(job)
                    if len(job_list) >= scraper_input.results_wanted:
                        break
            page += 1

        return job_list

    def _search_url(self) -> str:
        if self.term and self.city:
            return f"{self.base_url}/jobs/{self.term}-jobs-in-{self.city}"
        if self.term:
            return f"{self.base_url}/jobs/{self.term}-jobs"
        if self.city:
            return f"{self.base_url}/jobs/jobs-in-{self.city}"
        return f"{self.base_url}/jobs"

    @staticmethod
    def _city_slug(location: str | None) -> str | None:
        if not location:
            return None
        city = location.split(",")[0].strip().lower()
        city = city_aliases.get(city, city)
        city = re.sub(r"[^a-z0-9]+", "-", city).strip("-")
        return city or None

    def _process_job(self, raw: dict[str, object]) -> JobPost | None:
        job = ApnaFeedJob.model_validate(raw).data
        tags = {tag.tagLabel for tag in job.jobUITags if tag.tagLabel}
        is_remote = bool(tags & {"Work from home", "Work From Home"})
        if self.scraper_input.is_remote and not is_remote:
            return None

        job_types = [job_type_labels[tag] for tag in tags if tag in job_type_labels]
        requested = self.scraper_input.job_type
        if (
            requested
            and requested in job_type_labels.values()
            and requested not in job_types
        ):
            return None

        salary = job.jobSalaryRangeDetails
        low = salary.salaryMin if salary else None
        high = salary.salaryMax if salary else None
        has_pay = bool(low or high)
        details: dict[str, object] = {}
        date_posted: date | None = None
        job_url = self._job_url(job)
        if self.scraper_input.fetch_description:
            details = self._fetch_details(job_url)
            posted_at = details.pop("posted_timestamp", None)
            posted = details.pop("date_posted", None)
            if isinstance(posted, date):
                date_posted = posted
            if isinstance(posted_at, float) and too_old(
                posted_at, self.scraper_input.hours_old
            ):
                return None
            if self.scraper_input.hours_old and not date_posted:
                return None

        return JobPost(
            id=f"ap-{job.jobID}",
            title=job.jobTitle,
            company=(
                job.jobOrganisationDetails.organisationName
                if job.jobOrganisationDetails
                else None
            ),
            company_logo=(
                job.jobOrganisationDetails.organisationLogoURL
                if job.jobOrganisationDetails
                else None
            ),
            location=_location(job.jobCardAddress),
            job_url=job_url,
            date_posted=date_posted,
            job_type=job_types or None,
            is_remote=is_remote,
            interval=CompensationInterval.MONTHLY if has_pay else None,
            min_amount=float(low) if low else None,
            max_amount=float(high) if high else None,
            currency="INR" if has_pay else None,
            work_from_home_type=_work_mode(tags),
        ).model_copy(update=details)

    def _job_url(self, job: ApnaJobData) -> str:
        if job.jobPublicURL:
            return urljoin(self.base_url, job.jobPublicURL)
        city = _city_slug(job.jobCardAddress)
        title = _slug(job.jobTitle) or "job"
        if city:
            return f"{self.base_url}/job/{city}/{title}-{job.jobID}"
        return f"{self.base_url}/jobs"

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


def _slug(text: str | None) -> str | None:
    if not text:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or None


def _city_slug(address: str | None) -> str | None:
    if not address:
        return None
    text = re.sub(r"^All areas in\s+|\s+Region$", "", address.strip())
    city = text.split(",")[0].split("/")[0].strip()
    return _slug(city)


def _location(address: str | None) -> Location | None:
    if not address:
        return None
    cleaned = re.sub(r"^All areas in\s+|\s+Region$", "", address.strip())
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    city = parts[-1].split("/")[0].strip() if parts else None
    return Location(city=city or None, country=Country.INDIA)


def _work_mode(tags: set[str]) -> str | None:
    for tag in tags:
        if "work from" in tag.lower() or "office" in tag.lower():
            return tag
    return None


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
    if isinstance(employment, str):
        job_type = job_type_labels.get(employment.title())
        if job_type:
            result["job_type"] = [job_type]
    salary = data.get("baseSalary")
    if isinstance(salary, dict):
        value = salary.get("value")
        if isinstance(value, dict):
            interval = pay_intervals.get(str(value.get("unitText", "")).upper())
            min_value = value.get("minValue")
            max_value = value.get("maxValue")
            if interval:
                result["interval"] = CompensationInterval(interval)
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
    experience = data.get("experienceRequirements")
    if isinstance(experience, dict):
        months = experience.get("monthsOfExperience")
        if isinstance(months, (int, float)) and months:
            result["experience_range"] = f"{months / 12:.1f} years"
    location = data.get("jobLocation")
    if isinstance(location, dict):
        address = location.get("address")
        if isinstance(address, dict):
            city = address.get("addressLocality")
            state = address.get("addressRegion")
            if isinstance(city, str) and city:
                result["location"] = Location(
                    city=city,
                    state=state if isinstance(state, str) else None,
                    country=Country.INDIA,
                )
    return result


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


def _int_field(text: str, name: str) -> int | None:
    match = re.search(rf'"{name}":(\d+)', text)
    return int(match[1]) if match else None
