"""Adapter for existing people and contact-discovery records."""

import re

import config
from enrichment.contracts import CompanyContext, WorkerResult
from utils.validators import is_valid_person_name


VALID_DESIGNATION_PATTERN = re.compile(
    r"\b(CEO|CTO|CFO|COO|Founder|Co-Founder|Director|Head of Sales|Managing Director|"
    r"Chief Executive Officer|Chief Technology Officer|Chief Operating Officer|Owner|President)\b",
    re.I
)


class PeopleWorker:
    name = "people"
    priority = 1

    @staticmethod
    def should_run(context: CompanyContext) -> bool:
        return bool(context.company_name)

    def run(self, context: CompanyContext) -> WorkerResult:
        extracted = context.baseline_extraction or {}
        people = [dict(person) for person in (extracted.get("people") or [])]
        fields = {}

        if not people and context.search:
            for page_key in ("about_page", "team_page"):
                if extracted.get(page_key):
                    context.cached_page(extracted[page_key])
            people = self._search_people(context)

        fields["people"] = people

        # Also search for company size when missing
        employees = extracted.get("employees")
        if not employees and context.search:
            employees = self._search_company_size(context)
            if employees:
                fields["employees"] = employees

        missing = []
        if not people:
            missing.append("people")
        if not employees:
            missing.append("employees")

        return WorkerResult(
            worker_name=self.name,
            fields=fields,
            missing_fields=missing,
            metadata={"designation_source": "explicit_only"},
        )

    def _search_people(self, context):
        people = []
        cname = (context.company_name or "").strip()
        if not cname:
            return people

        queries = [
            f'"{cname}" CEO',
            f'"{cname}" founder',
            f'"{cname}" CTO',
            f'"{cname}" LinkedIn',
        ]

        seen_queries = set()
        for query in queries:
            if context.deadline and context.deadline.remaining() < 1.0:
                break
            if query in seen_queries:
                continue
            seen_queries.add(query)

            for result in context.cached_search(query, max_results=5):
                combined = f"{result.get('title', '')} {result.get('snippet', '')}"
                source_url = result.get("url", "")
                is_linkedin = "linkedin.com/in/" in source_url.lower()

                if not is_linkedin and not getattr(config, "SERPAPI_PRIMARY_MODE", False):
                    continue

                clean_name = re.sub(
                    r"\b(corporation|corp|inc|llc|ltd|limited|private limited|pvt ltd)\b",
                    "",
                    cname.lower(),
                    flags=re.I
                ).strip()
                domain_stem = (context.domain or "").split(".")[0].lower()
                combined_lower = combined.lower()

                if not (
                    cname.lower() in combined_lower
                    or (clean_name and clean_name in combined_lower)
                    or (domain_stem and len(domain_stem) >= 3 and domain_stem in combined_lower)
                ):
                    continue

                designation_match = VALID_DESIGNATION_PATTERN.search(combined)
                if not designation_match:
                    continue

                name = self._name_from_result(result)
                if not is_valid_person_name(name):
                    continue

                designation = designation_match.group(1).title()
                # Normalize acronyms
                if designation.upper() in ("CEO", "CTO", "CFO", "COO"):
                    designation = designation.upper()

                record = {
                    "name": name,
                    "designation": designation,
                    "linkedin": source_url if is_linkedin else None,
                    "company": context.company_name,
                    "source_url": source_url,
                    "observed": True,
                    "verified": False,
                }
                if not any(p.get("name") == name for p in people):
                    people.append(record)
                    print(f"[SERPAPI] EMPLOYEE: name='{name}' title='{designation}' source=SerpApi snippet")

            # Fallback to site:linkedin.com/in if no people found yet
            if not people and not any("site:linkedin.com/in" in q for q in seen_queries):
                queries.extend([
                    f'site:linkedin.com/in "{cname}" CEO',
                    f'site:linkedin.com/in "{cname}" founder',
                    f'site:linkedin.com/in "{cname}" CTO',
                ])

        return people

    def _search_company_size(self, context) -> str | None:
        cname = (context.company_name or "").strip()
        cdomain = (context.domain or "").strip()
        if not cname:
            return None

        size_queries = [
            f'"{cname}" employees',
            f'"{cname}" company size',
        ]
        if cdomain:
            size_queries.append(f'site:{cdomain} employees')

        for query in size_queries:
            if context.deadline and context.deadline.remaining() < 1.0:
                break
            results = context.cached_search(query, max_results=5)
            text = " ".join(f"{r.get('title', '')} {r.get('snippet', '')}" for r in results)
            # Match formats: "22,000 employees", "50-100 employees", "company size: 500+ employees"
            match = re.search(r"\b(\d[\d,]*(?:\s*[-+]\s*\d[\d,]*)?)\s+(?:employees|staff|people|workers)\b", text, re.I)
            if not match:
                match = re.search(r"\b(?:employees|company size|headcount)\s*[:\-]?\s*(\d[\d,]*(?:\s*[-+]\s*\d[\d,]*)?)\b", text, re.I)
            if match:
                emp_count = match.group(1).strip()
                print(f"[SERPAPI] COMPANY: field='employees' value='{emp_count}' source=SerpApi snippet")
                return emp_count
        return None

    @staticmethod
    def _name_from_result(result):
        title = result.get("title", "")
        candidate = re.split(r"\s+-\s+|\s+\|\s+|\s+at\s+", title, maxsplit=1)[0].strip()
        return candidate
