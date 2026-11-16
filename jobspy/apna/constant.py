from jobspy.model import JobType

jobs_per_page = 25

city_aliases = {
    "bangalore": "bengaluru",
    "bombay": "mumbai",
    "calcutta": "kolkata",
    "delhi": "new-delhi",
    "new delhi": "new-delhi",
}

job_type_labels = {
    "Contract": JobType.CONTRACT,
    "Contractual": JobType.CONTRACT,
    "Full Time": JobType.FULL_TIME,
    "Internship": JobType.INTERNSHIP,
    "Part Time": JobType.PART_TIME,
}

pay_intervals = {
    "DAY": "daily",
    "HOUR": "hourly",
    "MONTH": "monthly",
    "WEEK": "weekly",
    "YEAR": "yearly",
}
