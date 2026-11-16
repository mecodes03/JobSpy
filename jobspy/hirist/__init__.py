from __future__ import annotations

import math
import random
import time

from jobspy.hirist.constant import (
    cities_abroad,
    city_aliases,
    city_ids,
    jobs_per_page,
    posting_windows,
)
from jobspy.hirist.model import HiristDetail, HiristJob, HiristSearch
from jobspy.model import (
    Compensation,
    CompensationInterval,
    Country,
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


class Hirist(Scraper):
    base_url = "https://www.hirist.tech"
    search_url = "https://gladiator.hirist.tech/job/search"
    detail_url = "https://gladiator.hirist.tech/job/detail"
    delay = (2, 5)

    def scrape(self, scraper_input: ScraperInput) -> list[JobPost]:
        self.scraper_input = scraper_input
        if not scraper_input.search_term:
            self.warn("Hirist needs a search term, returning no jobs")
            return []
        self.session = create_session(
            TLSRotating(scraper_input.proxies),
            scraper_input,
            {"accept": "application/json"},
        )
        if scraper_input.easy_apply:
            self.warn("easy_apply isn't supported, ignoring it")
        if scraper_input.job_type:
            self.warn(
                f"job_type {scraper_input.job_type.value} isn't supported, ignoring it"
            )
        location_id = self._location_id(scraper_input.location)
        self.location_name = _location_name(scraper_input.location)
        posting = self._posting(scraper_input.hours_old)

        job_list: list[JobPost] = []
        seen: set[int] = set()
        first_page = scraper_input.offset // jobs_per_page
        skip = scraper_input.offset % jobs_per_page
        page = first_page

        while len(job_list) < scraper_input.results_wanted:
            if page > first_page:
                time.sleep(random.uniform(*self.delay))
            self.log.info(f"search page: {page + 1}")
            try:
                response = self.session.get(
                    self.search_url,
                    params={
                        "query": scraper_input.search_term,
                        "page": page,
                        "minexp": 0,
                        "maxexp": 0,
                        "loc": location_id,
                        "posting": posting,
                    },
                    allow_redirects=True,
                )
                check_status(response)
                result = HiristSearch.model_validate(response.json())
            except Exception as e:
                self.fail(str(e))
                break

            for raw in result.data[skip if page == first_page else 0 :]:
                if raw.id in seen:
                    continue
                seen.add(raw.id)
                try:
                    job = self._process_job(raw)
                except Exception as e:
                    self.log.warning(f"skipping job: {e}")
                    continue
                if job:
                    job_list.append(job)
                    if len(job_list) >= scraper_input.results_wanted:
                        break

            if not result.data or not result.hasMore:
                break
            page += 1

        return job_list

    def _location_id(self, location: str | None) -> str:
        if not location:
            return ""
        name = location.split(",")[0].strip().lower()
        name = city_aliases.get(name, name)
        location_id = city_ids.get(name)
        if location_id is None:
            self.warn(f"location '{location}' isn't supported, searching all of India")
            return ""
        return str(location_id)

    def _posting(self, hours_old: int | None) -> int:
        if not hours_old:
            return 0
        days = math.ceil(hours_old / 24)
        for window in posting_windows:
            if days <= window:
                return window
        self.warn("Hirist only searches the last 90 days, older jobs are left out")
        return posting_windows[-1]

    def _process_job(self, job: HiristJob) -> JobPost | None:
        posted = job.createdTime / 1000 if job.createdTime else None
        if too_old(posted or 0, self.scraper_input.hours_old):
            return None

        names = {location.name for location in job.locations if location.name}
        is_remote = job.workFromHome == 1 or "Remote" in names
        if self.scraper_input.is_remote and not is_remote:
            return None

        details: dict[str, object] = {}
        if self.scraper_input.fetch_description:
            details = self._fetch_details(job.id)

        return JobPost(
            id=f"hr-{job.id}",
            title=job.title.strip(),
            company=_company(job),
            company_logo=_logo(job),
            location=_location(job, is_remote, self.location_name),
            job_url=job.jobDetailUrl,
            job_url_direct=job.applyUrl or None,
            date_posted=utc_date(posted),
            is_remote=is_remote,
            work_from_home_type="Remote" if is_remote else None,
            **self._parse_salary(job).model_dump(),
            job_function=job.industry or None,
            company_industry=job.industry or None,
            skills=[tag.name for tag in job.tags if tag.name] or None,
            experience_range=_experience(job.min, job.max),
        ).model_copy(update=details)

    @staticmethod
    def _parse_salary(job: HiristJob) -> Compensation:
        if job.hideSal or not (job.minSal or job.maxSal):
            return Compensation()
        return Compensation(
            interval=CompensationInterval.YEARLY,
            min_amount=float(job.minSal) * 100000 if job.minSal else None,
            max_amount=float(job.maxSal) * 100000 if job.maxSal else None,
            currency="INR",
        )

    def _fetch_details(self, job_id: int) -> dict[str, object]:
        try:
            response = self.session.get(
                self.detail_url,
                params={"jobcode": job_id},
                headers={"accept": "application/json"},
                allow_redirects=True,
            )
            check_status(response)
            detail = HiristDetail.model_validate(response.json()["data"])
            fields = description_fields(
                detail.introText, self.scraper_input.description_format
            )
            if detail.applyUrl:
                fields["job_url_direct"] = detail.applyUrl
            return fields
        except Exception as e:
            self.log.warning(f"job {job_id}: {e}")
            return {}


def _company(job: HiristJob) -> str | None:
    if job.companyData:
        return job.companyData.companyName or job.companyData.companyNameNotAnalyzed
    return job.recruiter.recruiterName if job.recruiter else None


def _logo(job: HiristJob) -> str | None:
    if job.companyData and job.companyData.logo:
        return job.companyData.logo
    return job.recruiter.logoPath if job.recruiter else None


def _location_name(location: str | None) -> str | None:
    if not location:
        return None
    name = location.split(",")[0].strip().lower()
    return city_aliases.get(name, name)


def _location(
    job: HiristJob, is_remote: bool, preferred: str | None
) -> Location | None:
    if is_remote:
        return Location(country=Country.INDIA)
    names = [location.name for location in job.locations if location.name]
    name = next((name for name in names if name.lower() == preferred), None)
    if not name:
        name = names[0] if names else None
    if not name or name.lower() in {"anywhere in india/multiple locations", "others"}:
        return Location(country=Country.INDIA)
    if name.lower() in cities_abroad:
        if name.lower() == "singapore":
            return Location(city=name, country=Country.SINGAPORE)
        return None
    return Location(city=name, country=Country.INDIA)


def _experience(low: int | None, high: int | None) -> str | None:
    if not low and not high:
        return None
    if high:
        return f"{low or 0} - {high} years"
    return f"{low}+ years"
