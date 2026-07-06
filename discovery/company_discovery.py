from urllib.parse import urlparse

from discovery.search_backend import run_search
from query.dork_generator import generate_search_tasks


SOURCE_DOMAIN_MAP = {
    "linkedin.com": "LinkedIn",
    "clutch.co": "Clutch",
    "goodfirms.co": "GoodFirms",
    "justdial.com": "Justdial",
    "crunchbase.com": "Crunchbase",
}


def detect_source(url: str) -> str:

    domain = urlparse(url).netloc.lower()

    for key, value in SOURCE_DOMAIN_MAP.items():

        if key in domain:
            return value

    return "Google"


def guess_company_name(result: dict) -> str:

    title = (result.get("title") or "").strip()

    if title:

        for sep in [" - ", " | ", " – ", ": "]:

            if sep in title:
                return title.split(sep)[0].strip()

        return title

    url = result.get("url") or ""

    domain = urlparse(url).netloc.replace("www.", "")

    if domain:

        return domain.split(".")[0].replace("-", " ").title()

    return ""


def discover_companies(keyword: str):

    tasks = generate_search_tasks(keyword)

    merged = {}

    for task in tasks:

        print(f"\n[{task.source}] {task.query}")

        raw_results = run_search(task.query)

        print(f"Found {len(raw_results)} results")

        for result in raw_results:

            url = result.get("url")

            if not url:
                continue

            company_name = guess_company_name(result)

            if not company_name:
                continue

            key = company_name.lower()

            if key not in merged:

                merged[key] = {

                    "company": company_name,

                    "website": None,

                    "linkedin": None,

                    "industry": keyword,

                    "location": None,

                    "source": detect_source(url)

                }

            if "linkedin.com" in url:

                if not merged[key]["linkedin"]:
                    merged[key]["linkedin"] = url

            else:

                if not merged[key]["website"]:
                    merged[key]["website"] = url

    return list(merged.values())


if __name__ == "__main__":

    companies = discover_companies("Software Companies Noida")

    print()

    print("=" * 60)

    print("Companies Found")

    print("=" * 60)

    for company in companies:

        print(company)