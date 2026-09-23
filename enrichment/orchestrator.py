"""Phase 2 coordinator for controlled, shared-context enrichment."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from urllib.parse import urlparse

from enrichment.contracts import CompanyContext, WorkerResult
from enrichment.workers.company_worker import CompanyWorker
from enrichment.workers.contact_worker import ContactWorker
from enrichment.workers.people_worker import PeopleWorker
from enrichment.workers.social_worker import SocialWorker
from enrichment.workers.verification_worker import VerificationWorker


class EnrichmentOrchestrator:
    def __init__(self, extractor=None, legacy_builder=None, max_workers=4):
        self.extractor = extractor
        self.legacy_builder = legacy_builder
        self.max_workers = max(1, min(3, int(max_workers)))
        self.worker_executions = 0

    @staticmethod
    def context_from_company(company: dict, keyword: str = "", deadline=None) -> CompanyContext:
        website = company.get("website")
        domain = None
        if website:
            domain = urlparse(website).netloc.lower().removeprefix("www.") or None
        return CompanyContext(
            company_name=company.get("company") or "",
            website=website,
            domain=domain,
            linkedin=company.get("linkedin"),
            keyword=keyword,
            source=company.get("source"),
            relevance_score=company.get("relevance_score", 0),
            deadline=deadline,
            company=company,
            page_cache={"pages": {}, "searches": {}, "conflicts": []},
        )

    @staticmethod
    def _configure_context(context, extractor=None):
        from extraction.page_extractor import fetch_page
        from search.manager import run_search
        from main import get_search_manager

        def guarded_search(query, max_results=10, deadline=None, **kwargs):
            manager = get_search_manager()
            if not manager.providers_available():
                return []
            return run_search(
                query,
                max_results=max_results,
                deadline=deadline,
                **kwargs,
            )

        context.extractor = extractor or context.extractor
        context.search = context.search or guarded_search
        context.fetch_page = context.fetch_page or fetch_page
        return context

    @staticmethod
    def _merge_non_empty(target: dict, source: dict) -> None:
        for key, value in source.items():
            if value in (None, "", [], {}):
                continue
            if key not in target or target[key] in (None, "", [], {}):
                target[key] = value
            elif isinstance(target[key], list) and isinstance(value, list):
                merged = list(target[key])
                for item in value:
                    if item not in merged:
                        merged.append(item)
                target[key] = merged
            elif isinstance(target[key], dict) and isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    if nested_value not in (None, "", [], {}):
                        if nested_key in target[key] and target[key][nested_key] != nested_value:
                            target.setdefault("_conflicts", []).append({
                                "field": key,
                                "key": nested_key,
                                "values": [target[key][nested_key], nested_value],
                            })
                        else:
                            target[key].setdefault(nested_key, nested_value)
            elif target[key] != value:
                target.setdefault("_conflicts", []).append({
                    "field": key,
                    "values": [target[key], value],
                    "resolution": "preserved_existing",
                })

    @staticmethod
    def _merge_results(aggregate, results, context):
        for result in results:
            EnrichmentOrchestrator._merge_non_empty(aggregate, result.fields)
            if result.provenance:
                context.page_cache.setdefault("provenance", {}).update(result.provenance)
            if result.errors:
                context.page_cache.setdefault("errors", []).extend(result.errors)
        conflicts = aggregate.pop("_conflicts", [])
        if conflicts:
            context.page_cache.setdefault("conflicts", []).extend(conflicts)

    @staticmethod
    def _provenance(context, company, extracted, verification):
        def fact(value, source, observed=True, verified=False):
            return {
                "value": value,
                "source": source,
                "source_url": company.get("website") or company.get("source_url") or "",
                "observed": observed,
                "verified": verified,
            }

        provenance = {
            "company_name": fact(company.get("company"), "discovery", verified=True),
            "website": fact(company.get("website"), "discovery", verified=bool(company.get("website"))),
            "domain": fact(context.domain, "derived_from_website", verified=bool(context.domain)),
            "linkedin": fact(company.get("linkedin"), "discovery", verified=verification.get("linkedin_company") == "verified"),
            "industry": fact(extracted.get("industry_detected") or company.get("industry"), "website_or_discovery"),
            "location": fact(extracted.get("location"), "website_extraction"),
            "country": fact(extracted.get("country"), "website_extraction"),
            "employees": fact(extracted.get("employees"), "website_or_targeted_search"),
            "founded": fact(extracted.get("founded"), "website_or_targeted_search"),
            "description": fact(extracted.get("description"), "website_extraction"),
            "tech_stack": fact(extracted.get("tech_stack", []), "website_extraction"),
            "emails": list(extracted.get("emails_provenance") or []),
            "phones": list(extracted.get("phones_provenance") or []),
            "people": [fact(person, "website_or_targeted_search") for person in extracted.get("people", [])],
            "social_links": [fact({"platform": key, "url": value}, "homepage_link", verified=bool(verification.get("social_company", {}).get(key) == "verified")) for key, value in (extracted.get("social_links") or {}).items()],
        }
        return provenance

    @staticmethod
    def _observability(worker_results, context, verification, confidence):
        cache_metrics = context.page_cache.get("cache_metrics", {})
        return {
            "workers": context.page_cache.get("observability", {}).get("workers", []),
            "searches_performed": len(context.page_cache.get("searches", {})) + cache_metrics.get("search_misses", 0),
            "cache_hits": cache_metrics.get("search_hits", 0),
            "cache_misses": cache_metrics.get("search_misses", 0),
            "conflicts": len(context.page_cache.get("conflicts", [])),
            "verification": verification,
            "final_confidence": confidence,
            "run_summary": context.page_cache.get("run_summary", {}),
        }

    @staticmethod
    def completeness_profile(extracted: dict, verification: dict | None = None, context: CompanyContext | None = None) -> dict:
        """Group lead completeness by outreach value rather than raw fields."""
        extracted = extracted or {}
        verification = verification or {}
        people = extracted.get("people") or []
        emails = extracted.get("emails") or []
        phones = extracted.get("phones") or []
        social = extracted.get("social_links") or {}
        identity_checks = [
            bool(extracted.get("website") or extracted.get("domain") or (context and context.website)),
            verification.get("domain_company") in {"verified", "identity_matched"},
            bool(extracted.get("company_name") or (context and context.company_name)),
        ]
        contact_checks = [bool(emails), bool(phones), bool(extracted.get("contact_page"))]
        decision_checks = [
            bool(people),
            any(person.get("designation") for person in people),
            any(person.get("linkedin") for person in people),
        ]
        social_checks = [
            bool(social.get("linkedin")),
            bool(social.get("facebook") or social.get("instagram") or social.get("twitter")),
            bool(social.get("youtube") or social.get("github")),
        ]
        metadata_checks = [
            bool(extracted.get("industry_detected") and extracted.get("industry_detected") != "Unknown"),
            bool(extracted.get("description")),
            bool(extracted.get("location") or extracted.get("country")),
            bool(extracted.get("employees")),
            bool(extracted.get("founded")),
        ]

        def percent(checks):
            return round(sum(checks) / len(checks) * 100) if checks else 0

        profile = {
            "identity_complete": percent(identity_checks),
            "contact_complete": percent(contact_checks),
            "decision_maker_complete": percent(decision_checks),
            "social_complete": percent(social_checks),
            "company_metadata_complete": percent(metadata_checks),
        }
        profile["actionable"] = (
            profile["identity_complete"] >= 67
            and profile["contact_complete"] >= 33
            and profile["decision_maker_complete"] >= 33
        )
        profile["contact_completeness"] = {
            "email": 100 if emails else 0,
            "phone": 100 if phones else 0,
            "contact_page": 100 if extracted.get("contact_page") else 0,
        }
        profile["lead_actionability"] = {
            "company_name": 100 if (context and context.company_name) else 0,
            "usable_phone": 100 if phones else 0,
            "usable_email": 100 if emails else 0,
            "decision_maker": 100 if any(person.get("designation") for person in people) else 0,
        }
        return profile

    @staticmethod
    def should_continue_enrichment(profile: dict) -> bool:
        """Continue lower-priority enrichment only when the card is not actionable."""
        return not profile.get("actionable", False)

    def run(self, context: CompanyContext):
        if context.deadline and context.deadline.is_exceeded():
            if self.legacy_builder:
                card = self.legacy_builder(
                    context.company, context.keyword, context.deadline, baseline_extracted=context.baseline_extraction
                )
                if card is not None:
                    return card
            from main import _build_minimal_partial_card
            return _build_minimal_partial_card(context.company, context.keyword, extracted=context.baseline_extraction)

        self._configure_context(context, self.extractor)
        context.page_cache["defer_company_metadata"] = True
        company_worker = CompanyWorker(self.extractor)
        worker_results = []
        company_started = perf_counter()
        company_result = company_worker.run(context)
        baseline_duration_ms = round((perf_counter() - company_started) * 1000, 2)
        worker_results.append(company_result)
        self._record_worker(context, company_result, company_started)
        self.worker_executions += 1

        aggregate = dict(context.baseline_extraction or {})
        results = []

        # ── P0: ContactWorker (Phone & Email Acquisition) ───────────────────
        contact_worker = ContactWorker()
        if contact_worker.should_run(context):
            contact_started = perf_counter()
            try:
                contact_result = contact_worker.run(context)
                self._record_worker(context, contact_result, contact_started)
                results.append(contact_result)
                if "phones" in contact_result.fields:
                    aggregate["phones"] = contact_result.fields["phones"]
                if "phones_provenance" in contact_result.fields:
                    aggregate["phones_provenance"] = contact_result.fields["phones_provenance"]
                if "emails" in contact_result.fields and contact_result.fields["emails"]:
                    aggregate["emails"] = contact_result.fields["emails"]
                if "emails_provenance" in contact_result.fields and contact_result.fields["emails_provenance"]:
                    aggregate["emails_provenance"] = contact_result.fields["emails_provenance"]
                self._merge_results(aggregate, [contact_result], context)
                context.baseline_extraction = aggregate
            except Exception as exc:
                results.append(WorkerResult(worker_name="contact", errors=[str(exc)]))
            self.worker_executions += 1
        else:
            context.page_cache.setdefault("observability", {}).setdefault("workers", []).append({
                "worker_name": contact_worker.name,
                "duration_ms": 0.0,
                "status": "skipped",
                "fields_found": [],
                "fields_missing": [],
                "errors": [],
            })

        # ── P1: PeopleWorker (Decision Maker / Contact Person) ──────────────
        people_worker = PeopleWorker()
        if people_worker.should_run(context) and (not context.deadline or context.deadline.remaining() > 1.5):
            people_started = perf_counter()
            try:
                people_result = people_worker.run(context)
                self._record_worker(context, people_result, people_started)
                results.append(people_result)
                self._merge_results(aggregate, [people_result], context)
                context.baseline_extraction = aggregate
            except Exception as exc:
                results.append(WorkerResult(worker_name="people", errors=[str(exc)]))
            self.worker_executions += 1
        else:
            context.page_cache.setdefault("observability", {}).setdefault("workers", []).append({
                "worker_name": people_worker.name,
                "duration_ms": 0.0,
                "status": "skipped",
                "fields_found": [],
                "fields_missing": [],
                "errors": [],
            })

        # ── P2: CompanyWorker metadata (Only when deadline allows and metadata is missing)
        company_worker_enricher = CompanyWorker(self.extractor)
        if company_worker_enricher.should_run(context) and (not context.deadline or context.deadline.remaining() > 3.0):
            metadata_started = perf_counter()
            try:
                metadata_result = company_worker_enricher.enrich_missing_metadata(context)
                self._record_worker(context, metadata_result, metadata_started)
                worker_results.append(metadata_result)
                self.worker_executions += 1
                self._merge_results(aggregate, [metadata_result], context)
                context.baseline_extraction = aggregate
            except Exception as exc:
                worker_results.append(WorkerResult(worker_name="company_metadata", errors=[str(exc)]))
        else:
            context.page_cache.setdefault("observability", {}).setdefault("workers", []).append({
                "worker_name": "company_metadata",
                "duration_ms": 0.0,
                "status": "skipped",
                "fields_found": [],
                "fields_missing": [],
                "errors": [],
            })

        # ── P2/P3: SocialWorker (Only when deadline allows) ─────────────────
        social_worker = SocialWorker()
        if social_worker.should_run(context) and (not context.deadline or context.deadline.remaining() > 2.0):
            social_started = perf_counter()
            try:
                social_result = social_worker.run(context)
                self._record_worker(context, social_result, social_started)
                results.append(social_result)
                self.worker_executions += 1
                self._merge_results(aggregate, [social_result], context)
                context.baseline_extraction = aggregate
            except Exception as exc:
                results.append(WorkerResult(worker_name="social", errors=[str(exc)]))
        else:
            context.page_cache.setdefault("observability", {}).setdefault("workers", []).append({
                "worker_name": social_worker.name,
                "duration_ms": 0.0,
                "status": "skipped",
                "fields_found": [],
                "fields_missing": [],
                "errors": [],
            })

        merge_started = perf_counter()
        merge_duration_ms = round((perf_counter() - merge_started) * 1000, 2)

        context.baseline_extraction = aggregate
        verification_started = perf_counter()
        verification = VerificationWorker().run(
            context,
            extracted=aggregate,
            people=aggregate.get("people"),
            emails=aggregate.get("emails"),
        )
        self._record_worker(context, verification, verification_started)
        self.worker_executions += 1
        profile = self.completeness_profile(
            aggregate,
            verification.fields.get("verification", {}),
            context,
        )
        context.page_cache["completeness_profile"] = profile
        context.page_cache["run_summary"] = {
            "baseline_extraction_ms": baseline_duration_ms,
            "merge_ms": merge_duration_ms,
            "worker_count": len(worker_results) + len(results) + 1,
            "searches_performed": len(context.page_cache.get("searches", {})),
            "cache_hits": context.page_cache.get("cache_metrics", {}).get("search_hits", 0),
            "cache_misses": context.page_cache.get("cache_metrics", {}).get("search_misses", 0),
        }

        # The legacy builder remains authoritative for fallback searches,
        # validation, and the exact existing lead-card contract.
        if self.legacy_builder is None:
            return aggregate
        card = self.legacy_builder(
            context.company,
            context.keyword,
            context.deadline,
            baseline_extracted=aggregate,
        )
        if card is None:
            from main import _build_minimal_partial_card
            card = _build_minimal_partial_card(context.company, context.keyword, extracted=aggregate)
        if card is not None:
            verification_fields = verification.fields
            card["provenance"] = self._provenance(
                context, context.company, aggregate, verification_fields.get("verification", {})
            )
            card["conflicts"] = list(context.page_cache.get("conflicts", []))
            card["verification"] = verification_fields.get("verification", {})
            card["completeness_profile"] = profile
            card["contact_completeness"] = profile.get("contact_completeness", {})
            card["lead_actionability"] = profile.get("lead_actionability", {})
            card["observability"] = self._observability(
                worker_results + results,
                context,
                card["verification"],
                card.get("confidence_score"),
            )
            card["observability"]["enrichment_stop_reason"] = (
                "actionable_card" if profile.get("actionable") else "required_fields_incomplete"
            )
            if card["conflicts"]:
                card["confidence_score"] = max(0, int(card.get("confidence_score", 0)) - min(15, 3 * len(card["conflicts"])))
                card["lead_quality"] = "High" if card["confidence_score"] >= 70 else ("Medium" if card["confidence_score"] >= 40 else "Low")
                card["observability"]["final_confidence"] = card["confidence_score"]
        return card

    @staticmethod
    def _record_worker(context, result, started):
        context.page_cache.setdefault("observability", {}).setdefault("workers", []).append({
            "worker_name": result.worker_name,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "status": "error" if result.errors else "completed",
            "fields_found": result.fields_found,
            "fields_missing": result.missing_fields,
            "errors": result.errors,
        })
