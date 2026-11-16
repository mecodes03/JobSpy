from pydantic import BaseModel, Field


class ApnaOrganisation(BaseModel):
    organisationName: str | None = None
    organisationLogoURL: str | None = None


class ApnaSalary(BaseModel):
    salaryMin: int | None = None
    salaryMax: int | None = None


class ApnaUITag(BaseModel):
    tagLabel: str | None = None


class ApnaJobData(BaseModel):
    jobID: int
    jobTitle: str
    jobOrganisationDetails: ApnaOrganisation | None = None
    jobPublicURL: str
    jobSalaryRangeDetails: ApnaSalary | None = None
    jobCardAddress: str | None = None
    jobUITags: list[ApnaUITag] = Field(default_factory=list)
    jobTopHighlights: str | None = None
    jobBottomHighlights: str | None = None


class ApnaFeedJob(BaseModel):
    data: ApnaJobData
