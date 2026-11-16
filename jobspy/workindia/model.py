from pydantic import BaseModel, Field


class WorkIndiaJob(BaseModel):
    id: int
    profile_job_title: str
    branch_company_name: str | None = None
    branch_location_city_name: str | None = None
    branch_location_name: str | None = None
    branch_address: str | None = None
    min_salary: int | None = None
    max_salary: int | None = None
    employment_type: str | None = None
    created_at: str | None = None
    profile_html_description: str | None = None
    profile_job_description: str | None = None
    profile_industry_display_name: str | None = None
    experience: str | None = None
    job_experience: str | None = None
    no_of_openings: int | None = None
    skills: list[object] = Field(default_factory=list)
