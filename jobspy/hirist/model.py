from pydantic import BaseModel, ConfigDict, Field


class HiristLocation(BaseModel):
    id: int | None = None
    name: str | None = None


class HiristCompany(BaseModel):
    companyName: str | None = None
    companyNameNotAnalyzed: str | None = None
    logo: str | None = None


class HiristRecruiter(BaseModel):
    recruiterName: str | None = None
    logoPath: str | None = None


class HiristTag(BaseModel):
    name: str | None = None


class HiristJob(BaseModel):
    id: int
    title: str
    jobDetailUrl: str
    min: int | None = None
    max: int | None = None
    locations: list[HiristLocation] = Field(default_factory=list)
    tags: list[HiristTag] = Field(default_factory=list)
    companyData: HiristCompany | None = None
    recruiter: HiristRecruiter | None = None
    createdTime: int | None = None
    minSal: int | None = None
    maxSal: int | None = None
    hideSal: int | None = None
    workFromHome: int | None = None
    applyUrl: str | None = None
    industry: str | None = None


class HiristSearch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[HiristJob] = Field(default_factory=list)
    totalPages: int | None = None
    hasMore: bool | None = None


class HiristDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    introText: str | None = None
    createdTime: int | None = None
    applyUrl: str | None = None
