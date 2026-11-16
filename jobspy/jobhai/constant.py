from jobspy.model import JobType

jobs_per_page = 20

default_city = "delhi"

city_aliases = {
    "bangalore": "bangalore",
    "bengaluru": "bangalore",
    "bombay": "mumbai",
    "calcutta": "kolkata",
    "delhi ncr": "delhi",
    "gurugram": "gurgaon",
    "new delhi": "delhi",
}

job_type_labels = {
    "Contract": JobType.CONTRACT,
    "Contractual": JobType.CONTRACT,
    "Full Time": JobType.FULL_TIME,
    "Internship": JobType.INTERNSHIP,
    "Part Time": JobType.PART_TIME,
    "Temporary": JobType.TEMPORARY,
}
