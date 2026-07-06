PERSON_KEYWORDS = {

    "engineer",
    "developer",
    "designer",
    "manager",
    "director",
    "founder",
    "ceo",
    "cto",
    "coo",
    "cfo",
    "president",
    "consultant",
    "architect",
    "freelancer",
    "recruiter",
    "hr",
    "marketing",
    "sales",
    "analyst",
    "intern",

}


COMPANY_KEYWORDS = {

    "company",
    "companies",
    "agency",
    "startup",
    "startups",
    "firm",
    "firms",
    "business",
    "businesses",
    "consultancy",
    "software",
    "it",
    "technology",
    "technologies",
    "solution",
    "solutions",
    "services",

}


def detect_category(keyword: str) -> str:
    """
    Returns

    company

    or

    person
    """

    keyword = keyword.lower().strip()

    words = keyword.split()

    # Check for person-related words first
    for word in words:

        if word in PERSON_KEYWORDS:

            return "person"

    # Then check company words
    for word in words:

        if word in COMPANY_KEYWORDS:

            return "company"

    # Default
    return "company"


if __name__ == "__main__":

    while True:

        keyword = input("\nKeyword : ")

        print("Category :", detect_category(keyword))