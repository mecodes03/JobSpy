from pydantic import BaseModel


class JobHaiJob(BaseModel):
    job_id: int
    page_url: str
    job_title: str
    company_name: str | None = None
    job_location: str | None = None
    salary: str | None = None
    min_sal: int | None = None
    max_sal: int | None = None
    live_date: str | None = None
    exp_text: str | None = None
    min_exp: int | None = None
    max_exp: int | None = None
    job_type: str | None = None
    job_type_location: str | None = None
    is_wfh: bool | None = None
    no_of_openings: int | None = None
    qualification: str | None = None
    shift_type: str | None = None
    category_name: str | None = None
    industry: str | None = None
    job_summary: str | None = None
    brand_logo: str | None = None
