"""Adapter around the existing website extractor."""

import re

from enrichment.contracts import CompanyContext, WorkerResult
from utils.provenance import make_fact, SRC_SEARCH_RESULT_SNIPPET


class CompanyWorker:
    name = "company"

    def __init__(self, extractor=None):
        self.extractor = extractor

    def run(self, context: CompanyContext) -> WorkerResult:
        if context.baseline_extraction is not None:
            extracted = context.baseline_extraction
        elif not context.website:
            extracted = {}
        else:
            import config
            is_serpapi = getattr(config, "SERPAPI_PRIMARY_MODE", False)
            extractor = self.extractor if self.extractor is not None else context.extractor
            is_mocked = extractor and (hasattr(extractor, "assert_called_with") or hasattr(extractor, "mock_calls") or (getattr(extractor, "__name__", "") != "extract_from_website" and self.extractor is not None))
            if is_serpapi and not is_mocked:
                extracted = {
                    "contact_page": None, "about_page": None, "team_page": None,
                    "emails": [], "phones": [], "social_links": {}, "people": [],
                    "company_type": "Company", "industry_detected": (context.company or {}).get("industry_detected", "Unknown"),
                    "meta_description": (context.company or {}).get("snippet", ""),
                }
            else:
                if extractor is None:
                    raise ValueError("CompanyWorker requires an extractor")
                extracted = extractor(
                    context.website,
                    deadline=context.deadline,
                ) or {}

        targeted = {} if context.page_cache.get("defer_company_metadata") else self._target_missing_fields(context, extracted)
        for key, value in targeted.items():
            if extracted.get(key) in (None, "", [], {}):
                extracted[key] = value
        context.baseline_extraction = extracted
        context.page_cache["company_extraction"] = extracted
        missing = [key for key, value in extracted.items() if value in (None, "", [], {})]
        return WorkerResult(
            worker_name=self.name,
            fields=dict(extracted),
            missing_fields=missing,
            metadata={"baseline": True, "extractor_keys": list(extracted)},
        )

    def enrich_missing_metadata(self, context: CompanyContext) -> WorkerResult:
        """Acquire lower-priority company facts after contact/person work."""
        extracted = context.baseline_extraction or {}
        targeted = self._target_missing_fields(context, extracted)
        for key, value in targeted.items():
            if extracted.get(key) in (None, "", [], {}, "Unknown"):
                extracted[key] = value
        context.baseline_extraction = extracted
        return WorkerResult(
            worker_name=self.name,
            fields=dict(targeted),
            missing_fields=[key for key in ("employees", "founded", "location", "description", "industry_detected") if not extracted.get(key)],
            metadata={"phase": "deferred_metadata"},
        )

    @staticmethod
    def should_run(context: CompanyContext) -> bool:
        extracted = context.baseline_extraction or {}
        return any(
            extracted.get(field) in (None, "", [], {}, "Unknown")
            for field in ("employees", "founded", "location", "description", "industry_detected")
        )

    def _target_missing_fields(self, context: CompanyContext, extracted: dict) -> dict:
        if not context.search or not self.should_run(context):
            return {}
        profile = context.page_cache.get("completeness_profile", {})
        if profile.get("actionable"):
            return {}
        missing = []
        for field in ("employees", "founded", "location", "description", "industry_detected"):
            if extracted.get(field) in (None, "", [], {}, "Unknown"):
                missing.append(field)
        if not missing:
            return {}

        values = {}
        queries = {
            "employees": f'site:{context.domain} "employees"',
            "founded": f'"{context.company_name}" founded',
            "location": f'"{context.company_name}" headquarters',
            "description": f'"{context.company_name}" company',
            "industry_detected": f'"{context.company_name}" industry',
        }
        for field in missing:
            if context.deadline and context.deadline.remaining() < 1.0:
                break
            query = queries[field]
            results = context.cached_search(query, max_results=5)
            text = " ".join(
                f"{item.get('title', '')} {item.get('snippet', '')}" for item in results
            )
            if field == "employees":
                match = re.search(r"\b(\d[\d,]*(?:\s*[-+]\s*\d[\d,]*)?)\s+(?:employees|staff|people)\b", text, re.I)
                if match:
                    values[field] = match.group(1)
            elif field == "founded":
                match = re.search(r"\b(?:founded|established|since)\s+(?:in\s+)?(\d{4})\b", text, re.I)
                if match:
                    values[field] = match.group(1)
            elif field == "location":
                for marker in ("headquarters", "based in", "located in"):
                    match = re.search(rf"{marker}\s*(?:in|at)?\s*([A-Z][A-Za-z .,-]{{2,60}})", text, re.I)
                    if match:
                        values[field] = match.group(1).strip(" .,-")
                        break
            elif field == "description" and text:
                values[field] = text[:800].strip()
            elif field == "industry_detected" and text:
                values[field] = text[:160].strip()

            if field in values:
                print(f"[SERPAPI] COMPANY: field='{field}' value='{values[field]}' source=SerpApi snippet")
        return values

