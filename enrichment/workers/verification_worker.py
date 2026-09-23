"""Adapter for existing domain, quality, and confidence calculations."""

import re
from urllib.parse import urlparse

from enrichment.contracts import CompanyContext, WorkerResult


class VerificationWorker:
    name = "verification"

    def run(self, context: CompanyContext, extracted=None, people=None, emails=None) -> WorkerResult:
        extracted = extracted if extracted is not None else (context.baseline_extraction or {})
        people = people if people is not None else list(extracted.get("people") or [])
        emails = emails if emails is not None else list(extracted.get("emails") or [])

        # Imports stay local so main.py can retain its public extractor seam.
        from main import (
            _dq_level,
            calculate_completeness_score,
            verify_domain_evidence,
        )

        company = context.company
        identity, domain, evidence = verify_domain_evidence(
            company, extracted, keyword=context.keyword
        )
        completeness = calculate_completeness_score(company, extracted, people, emails)
        multiplier = {
            "verified": 1.0,
            "identity_matched": 0.85,
            "observed": 0.65,
            "not_found": 0.30,
        }.get(identity, 0.50)
        confidence = int(round(completeness * multiplier))
        provenance = {
            "email": list(extracted.get("emails_provenance") or []),
            "phone": list(extracted.get("phones_provenance") or []),
        }
        assessments = self._assess_fields(context, extracted, people, emails, identity, evidence)
        data_quality = {
            "identity": identity,
            "domain": domain,
            "email": _dq_level(provenance["email"]),
            "phone": _dq_level(provenance["phone"]),
            "location": _dq_level(extracted.get("location_provenance")),
            "employees": _dq_level(extracted.get("employees_provenance")),
            "founded": _dq_level(extracted.get("founded_provenance")),
            "people": _dq_level(people),
            "description": "observed" if extracted.get("description") else "not_found",
        }
        missing = [
            field for field, value in {
                "email": provenance["email"],
                "phone": provenance["phone"],
                "employees": extracted.get("employees_provenance"),
                "founded": extracted.get("founded_provenance"),
                "location": extracted.get("location_provenance"),
                "people": people,
            }.items() if not value
        ]
        return WorkerResult(
            worker_name=self.name,
            fields={
                "data_quality": data_quality,
                "missing_fields": missing,
                "domain_verification": {
                    "status": identity,
                    "domain": context.domain,
                    "evidence": evidence,
                },
                "confidence_score": confidence,
                "verification": assessments,
            },
            provenance={**provenance, "verification": assessments},
            missing_fields=missing,
            metadata={
                "completeness_score": completeness,
                "verification_state": identity,
                "conflicts": list(context.page_cache.get("conflicts", [])),
            },
        )

    @staticmethod
    def _assess_fields(context, extracted, people, emails, identity, evidence):
        domain = (context.domain or "").lower()
        domain_token = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
        social = extracted.get("social_links") or {}
        social_states = {}
        for platform, url in social.items():
            url_lower = str(url).lower()
            social_states[platform] = "verified" if domain_token and domain_token in re.sub(r"[^a-z0-9]", "", url_lower) else "observed"

        linkedin = context.linkedin or social.get("linkedin")
        linkedin_state = "not_found"
        if linkedin:
            linkedin_clean = re.sub(r"[^a-z0-9]", "", linkedin.lower())
            linkedin_state = "verified" if domain_token and domain_token in linkedin_clean else "observed"

        email_states = {}
        for email in emails:
            email_domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
            email_states[email] = "verified" if domain and email_domain == domain else "observed"

        people_states = []
        for person in people:
            person_linkedin = person.get("linkedin") or ""
            person_states = {
                "name": person.get("name"),
                "designation": person.get("designation"),
                "state": "observed" if person.get("name") else "not_found",
            }
            if person_linkedin:
                person_states["linkedin_state"] = "observed"
                if context.company_name.lower().split()[0] in person_linkedin.lower():
                    person_states["linkedin_state"] = "corroborated"
            people_states.append(person_states)

        return {
            "domain_company": identity,
            "linkedin_company": linkedin_state,
            "social_company": social_states,
            "email_domain": email_states,
            "people_company": people_states,
            "phone_company": "observed" if extracted.get("phones") else "not_found",
            "evidence": list(dict.fromkeys(evidence)),
        }
