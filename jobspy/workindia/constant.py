from jobspy.model import JobType

jobs_per_page = 20

city_aliases = {
    "bangalore": "bengaluru",
    "bombay": "mumbai",
    "calcutta": "kolkata",
    "gurgaon": "gurugram",
    "new delhi": "delhi",
}

job_type_labels = {
    "CONTRACT": JobType.CONTRACT,
    "CONTRACTUAL": JobType.CONTRACT,
    "FULL TIME": JobType.FULL_TIME,
    "FULL_TIME": JobType.FULL_TIME,
    "INTERNSHIP": JobType.INTERNSHIP,
    "PART TIME": JobType.PART_TIME,
    "PART_TIME": JobType.PART_TIME,
    "TEMPORARY": JobType.TEMPORARY,
}
