from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime
from urllib.parse import quote

from bs4 import BeautifulSoup

from jobspy.model import (
    Compensation,
    CompensationInterval,
    Country,
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
from jobspy.workindia.constant import (
    city_aliases,
    job_type_labels,
    jobs_per_page,
)
from jobspy.workindia.model import WorkIndiaJob


class WorkIndia(Scraper):
    base_url = "https://www.workindia.in"
    delay = (2, 5)

    def scrape(self, scraper_input: ScraperInput) -> list[JobPost]:
        self.scraper_input = scraper_input
        self.session = create_session(
            TLSRotating(scraper_input.proxies),
            scraper_input,
            {"accept": "text/html,application/xhtml+xml"},
        )
        if scraper_input.search_term and (
            scraper_input.offset + scraper_input.results_wanted > jobs_per_page
        ):
            self.warn(
                f"WorkIndia text search returns at most {jobs_per_page} jobs; "
                "drop the search term to page through a city instead"
            )
        if scraper_input.easy_apply:
            self.warn("easy_apply isn't supported, ignoring it")
        if (
            scraper_input.job_type
            and scraper_input.job_type not in job_type_labels.values()
        ):
            self.warn(
                f"job_type {scraper_input.job_type.value} isn't supported, ignoring it"
            )

        job_list: list[JobPost] = []
        seen: set[int] = set()
        if scraper_input.search_term:
            # WorkIndia renders only the first page for a text search.
            first_page, skip = 1, scraper_input.offset
        else:
            first_page = scraper_input.offset // jobs_per_page + 1
            skip = scraper_input.offset % jobs_per_page
        page = first_page

        while len(job_list) < scraper_input.results_wanted:
            if page > first_page:
                time.sleep(random.uniform(*self.delay))
            self.log.info(f"search page: {page}")
            try:
                response = self.session.get(self._page_url(page), allow_redirects=True)
                check_status(response)
                data = _route_data(response.text)
                jobs = data.get("data")
                urls = _item_list_urls(response.text)
            except Exception as e:
                self.fail(str(e))
                break
            if not isinstance(jobs, list) or not jobs:
                break

            for raw in jobs[skip if page == first_page else 0 :]:
                if not isinstance(raw, dict):
                    continue
                try:
                    job_id = int(str(raw["id"]))
                    if job_id in seen:
                        continue
                    seen.add(job_id)
                    job = self._process_job(raw, urls)
                except Exception as e:
                    self.log.warning(f"skipping job: {e}")
                    continue
                if job:
                    job_list.append(job)
                    if len(job_list) >= scraper_input.results_wanted:
                        break

            # A text search only has a server-rendered first page.
            if scraper_input.search_term:
                break
            page += 1

        return job_list

    def _page_url(self, page: int) -> str:
        city = self._city_slug(self.scraper_input.location)
        if self.scraper_input.search_term:
            query = f"?text_search={quote(self.scraper_input.search_term)}"
            if city:
                return f"{self.base_url}/jobs-in-{city}/{query}"
            return f"{self.base_url}/jobs/{query}"
        if city:
            if page == 1:
                return f"{self.base_url}/jobs-in-{city}/"
            return f"{self.base_url}/jobs-in-{city}-page-{page}/"
        if page == 1:
            return f"{self.base_url}/jobs/"
        return f"{self.base_url}/jobs-in-india-page-{page}/"

    @staticmethod
    def _city_slug(location: str | None) -> str | None:
        if not location:
            return None
        city = location.split(",")[0].strip().lower()
        city = city_aliases.get(city, city)
        city = re.sub(r"[^a-z0-9]+", "-", city).strip("-")
        return city or None

    def _process_job(
        self, raw: dict[str, object], urls: dict[str, str]
    ) -> JobPost | None:
        job = WorkIndiaJob.model_validate(raw)
        posted = (
            datetime.fromisoformat(job.created_at.replace("Z", "+00:00"))
            if job.created_at
            else None
        )
        if posted and too_old(posted.timestamp(), self.scraper_input.hours_old):
            return None

        html = job.profile_html_description or job.profile_job_description
        text = f"{job.profile_job_title} {html or ''}".lower()
        is_remote = any(
            phrase in text
            for phrase in ("work from home", "work-from-home", "wfh", "remote job")
        )
        if self.scraper_input.is_remote and not is_remote:
            return None

        job_types = _parse_job_types(job.employment_type)
        requested = self.scraper_input.job_type
        if (
            requested
            and requested in job_type_labels.values()
            and requested not in (job_types or [])
        ):
            return None

        city = job.branch_location_city_name or job.branch_location_name
        location = Location(city=city.title(), country=Country.INDIA) if city else None
        details = description_fields(html, self.scraper_input.description_format)
        if self.scraper_input.fetch_description and not details["description"]:
            details = {"description": job.profile_job_description, "emails": None}

        return JobPost(
            id=f"wi-{job.id}",
            title=job.profile_job_title,
            company=job.branch_company_name,
            location=location,
            job_url=urls.get(str(job.id), f"{self.base_url}/jobs/{job.id}/"),
            date_posted=utc_date(posted.timestamp()) if posted else None,
            job_type=job_types,
            is_remote=is_remote,
            **self._parse_salary(job).model_dump(),
            job_function=job.profile_industry_display_name,
            company_industry=job.profile_industry_display_name,
            company_addresses=job.branch_address,
            skills=_skill_names(job.skills),
            experience_range=_experience(job.experience, job.job_experience),
            vacancy_count=job.no_of_openings,
            work_from_home_type="Remote" if is_remote else None,
        ).model_copy(update=details)

    @staticmethod
    def _parse_salary(job: WorkIndiaJob) -> Compensation:
        return Compensation(
            interval=CompensationInterval.MONTHLY,
            min_amount=float(job.min_salary) if job.min_salary else None,
            max_amount=float(job.max_salary) if job.max_salary else None,
            currency="INR" if job.min_salary or job.max_salary else None,
        )


def _parse_job_types(value: str | None) -> list[JobType] | None:
    if not value:
        return None
    types = [
        job_type_labels[part.strip().upper()]
        for part in re.split(r"[,/]", value)
        if part.strip().upper() in job_type_labels
    ]
    return types or None


def _skill_names(skills: list[object]) -> list[str] | None:
    names = [
        str(skill["name"] if isinstance(skill, dict) else skill)
        for skill in skills
        if skill
    ]
    return names or None


def _experience(experience: str | None, job_experience: str | None) -> str | None:
    if experience:
        return experience.replace("_", " ")
    if job_experience:
        return job_experience.replace("_", " ")
    return None


def _route_data(html: str) -> dict[str, object]:
    """The search payload WorkIndia embeds in the page for its own client."""
    marker = "window.__ROUTE_DATA__"
    start = html.find(marker)
    if start < 0:
        raise ValueError("no route data")
    start = html.find("{", html.find("=", start) + 1)
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                data: dict[str, object] = json.loads(html[start : index + 1])
                return data
    raise ValueError("unterminated route data")


def _item_list_urls(html: str) -> dict[str, str]:
    """Job detail URLs, keyed by id, from the page's ItemList JSON-LD."""
    urls: dict[str, str] = {}
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "ItemList":
            continue
        items = data.get("itemListElement")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str):
                continue
            match = re.search(r"-(\d+)/?$", url)
            if match:
                urls[match[1]] = url
    return urls
