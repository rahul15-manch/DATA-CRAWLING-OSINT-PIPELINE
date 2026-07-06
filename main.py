import json
import os
from datetime import datetime

import config

from discovery.company_discovery import discover_companies
from discovery.contact_discovery import discover_contact
from extraction.page_extractor import extract_from_website


def build_lead_card(company: dict) -> dict:
    """
    Build one Lead Card from a discovered company.
    """

    website = company.get("website")

    if website:
        extracted = extract_from_website(website)
    else:
        extracted = {
            "contact_page": None,
            "about_page": None,
            "team_page": None,
            "emails": [],
            "phones": [],
            "social_links": {},
            "people": [],
        }

    people = list(extracted.get("people", []))
    emails = list(extracted.get("emails", []))

    if not people:

        contact = discover_contact(
            company.get("company") or ""
        )

        if contact.get("contact_name"):

            people.append({

                "name": contact.get("contact_name"),

                "designation": contact.get("designation"),

                "linkedin": contact.get("linkedin")

            })

        if contact.get("email"):

            emails.append(contact["email"])

            emails = sorted(set(emails))

    return {

        "company_name": company.get("company"),

        "website": website,

        "linkedin_company": company.get("linkedin"),

        "industry": company.get("industry"),

        "location": company.get("location"),

        "contact_page": extracted.get("contact_page"),

        "about_page": extracted.get("about_page"),

        "team_page": extracted.get("team_page"),

        "emails": emails,

        "phones": extracted.get("phones", []),

        "social_links": extracted.get("social_links", {}),

        "people": people,

        "source": company.get("source")

    }


def run_pipeline(keyword: str):

    print(f"\nSearching for: {keyword}\n")

    companies = discover_companies(keyword)

    print(f"Companies Found : {len(companies)}")

    leads = []

    for company in companies:

        print(f"Building Lead Card : {company['company']}")

        lead = build_lead_card(company)

        leads.append(lead)

    os.makedirs(config.OUTPUT_FOLDER, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = keyword.replace(" ", "_").lower()

    output_file = os.path.join(

        config.OUTPUT_FOLDER,

        f"{filename}_{timestamp}.json"

    )

    with open(output_file, "w", encoding="utf-8") as f:

        json.dump(

            leads,

            f,

            indent=4,

            ensure_ascii=False

        )

    print(f"\nSaved {len(leads)} Lead Cards")

    print(output_file)

    return leads


if __name__ == "__main__":

    keyword = input(

        "Enter Keyword : "

    ).strip()

    if keyword:

        run_pipeline(keyword)

    else:

        print("Keyword Required.")