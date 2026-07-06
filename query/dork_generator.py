
from query.search_templates import SEARCH_TEMPLATES
from models.search_task import SearchTask


def detect_category(keyword: str) -> str:
    """
    Detect whether the keyword refers to companies or people.

    Returns:
        "company"
        "person"
    """

    person_keywords = {
        "engineer",
        "developer",
        "manager",
        "founder",
        "ceo",
        "cto",
        "director",
        "designer",
        "architect",
        "consultant",
        "freelancer",
        "hr",
        "recruiter"
    }

    keyword = keyword.lower()

    for word in person_keywords:
        if word in keyword:
            return "person"

    return "company"


def generate_search_tasks(keyword: str) -> list[SearchTask]:
    """
    Generate search tasks from a keyword.

    Parameters
    ----------
    keyword : str

    Returns
    -------
    List[SearchTask]
    """

    keyword = keyword.strip()

    category = detect_category(keyword)

    tasks = []

    priority = 1
    templates = SEARCH_TEMPLATES[category]

    for source, queries in templates.items():

        for template in queries:

            query = template.format(keyword=keyword)

            task = SearchTask(
                source=source,
                query=query,
                priority=priority,
                category=category
            )

            tasks.append(task)

            priority += 1

    return tasks


if __name__ == "__main__":

    keyword = input("Enter keyword: ")

    tasks = generate_search_tasks(keyword)

    print("\nGenerated Search Tasks\n")

    for task in tasks:
        print(task)