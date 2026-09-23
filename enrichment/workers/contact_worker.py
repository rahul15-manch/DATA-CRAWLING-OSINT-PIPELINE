"""Adapter for existing observed contact evidence and fallback outputs."""

import re
from urllib.parse import urlparse

import phonenumbers

import config
from enrichment.contracts import CompanyContext, WorkerResult
from utils.provenance import make_fact, SRC_SEARCH_RESULT_SNIPPET
from utils.validators import is_valid_email_candidate, is_valid_phone


class ContactWorker:
    name = "contact"
    priority = 1

    @staticmethod
    def should_run(context: CompanyContext) -> bool:
        return bool(context.company_name)

    def run(self, context: CompanyContext) -> WorkerResult:
        extracted = context.baseline_extraction or {}
        fields = {}
        for key in ("emails", "phones", "email_candidates"):
            if key in extracted:
                fields[key] = list(extracted.get(key) or [])
        for key in ("emails_provenance", "phones_provenance"):
            if key in extracted:
                fields[key] = list(extracted.get(key) or [])

        # Normalize baseline phones to E.164 and attach structured phone facts
        if fields.get("phones"):
            norm_phones = []
            norm_facts = []
            for idx, p in enumerate(fields["phones"]):
                norm_p, country = self._normalize_phone(p, context)
                if norm_p and norm_p not in norm_phones:
                    norm_phones.append(norm_p)
                    fact = fields.get("phones_provenance", [{}])[idx] if idx < len(fields.get("phones_provenance", [])) else {}
                    source = fact.get("source") or "official_company_page"
                    source_url = fact.get("source_url") or context.website or ""
                    norm_facts.append(self._phone_fact(norm_p, country, source, source_url))
            fields["phones"] = norm_phones
            fields["phones_provenance"] = norm_facts

        if not fields.get("emails") or not fields.get("phones"):
            page_emails, page_phones, page_email_provenance, page_phone_provenance = self._contact_pages(context)
            fields["emails"] = fields.get("emails", []) + page_emails
            fields["phones"] = fields.get("phones", []) + page_phones
            fields["emails_provenance"] = fields.get("emails_provenance", []) + page_email_provenance
            fields["phones_provenance"] = fields.get("phones_provenance", []) + page_phone_provenance
        if context.search:
            emails, phones, email_provenance, phone_provenance, found_contact_page = self._search_contacts(context)
            fields["emails"] = fields.get("emails", []) + emails
            fields["phones"] = fields.get("phones", []) + phones
            fields["emails_provenance"] = fields.get("emails_provenance", []) + email_provenance
            fields["phones_provenance"] = fields.get("phones_provenance", []) + phone_provenance
            if found_contact_page and not fields.get("contact_page"):
                fields["contact_page"] = found_contact_page
        fields["emails"], fields["emails_provenance"] = self._dedupe_facts(fields.get("emails", []), fields.get("emails_provenance", []))
        fields["phones"], fields["phones_provenance"] = self._dedupe_facts(fields.get("phones", []), fields.get("phones_provenance", []))
        missing = [key for key in ("emails", "phones") if not fields.get(key)]
        return WorkerResult(
            worker_name=self.name,
            fields=fields,
            provenance={
                "emails": fields.get("emails_provenance", []),
                "phones": fields.get("phones_provenance", []),
            },
            missing_fields=missing,
            metadata={"fallback_owner": "legacy_build_lead_card"},
        )

    def _search_contacts(self, context):
        emails, phones, email_provenance, phone_provenance = [], [], [], []
        contact_page = None
        queries = []
        cname = (context.company_name or "").strip()
        cdomain = (context.domain or "").strip()

        # 4 company queries + 3 domain queries (if domain known)
        if cname:
            queries.extend([
                f'"{cname}" phone',
                f'"{cname}" email',
                f'"{cname}" contact',
                f'"{cname}" sales',
            ])
        if cdomain:
            queries.extend([
                f"site:{cdomain} phone",
                f"site:{cdomain} email",
                f"site:{cdomain} contact",
            ])

        from extraction.page_extractor import extract_emails, extract_phone_numbers, extract_structured_contact_info

        seen_queries = set()
        for query in queries:
            if query in seen_queries:
                continue
            seen_queries.add(query)

            if context.deadline and context.deadline.remaining() < 1.0:
                break
            for result in context.cached_search(query, max_results=5):
                text = f"{result.get('title', '')} {result.get('snippet', '')}"
                source_url = result.get("url", "")
                
                # Check for contact page
                if not contact_page and source_url:
                    url_lower = source_url.lower()
                    if "contact" in url_lower:
                        if cdomain and self._is_company_domain_url(source_url, cdomain):
                            contact_page = source_url
                        elif not contact_page and not cdomain:
                            contact_page = source_url

                if cdomain and not self._is_company_domain_url(source_url, cdomain):
                    if not (getattr(config, "SERPAPI_PRIMARY_MODE", False) and cname and cname.lower() in text.lower()):
                        continue

                for email in re.findall(r"[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
                    if is_valid_email_candidate(email) and email not in emails:
                        emails.append(email)
                        email_provenance.append(make_fact(email, SRC_SEARCH_RESULT_SNIPPET, source_url=source_url, verified=False))
                        print(f"[SERPAPI] CONTACT: email='{email}' source=SerpApi snippet")
                for phone in re.findall(r"\+?[\d][\d\s().-]{6,}[\d]", text):
                    normalized, country = self._normalize_phone(phone, context)
                    if normalized and self._business_phone_context(text):
                        phone_type = self._classify_phone_type(text)
                        if normalized not in phones:
                            phones.append(normalized)
                            phone_provenance.append(self._phone_fact(normalized, country, SRC_SEARCH_RESULT_SNIPPET, source_url, phone_type=phone_type))
                            print(f"[SERPAPI] CONTACT: phone='{normalized}' source=SerpApi snippet")

                # If result URL is on the company domain and has contact path, fetch and extract directly (bypassed in SERPAPI_PRIMARY_MODE)
                if not getattr(config, "SERPAPI_PRIMARY_MODE", False) and cdomain and source_url and cdomain in source_url.lower():
                    url_lower = source_url.lower()
                    if any(marker in url_lower for marker in ("contact", "about", "support", "reach", "help")):
                        if not context.deadline or context.deadline.remaining() > 1.5:
                            html = context.cached_page(source_url)
                            if html:
                                for fe in extract_emails(html):
                                    if is_valid_email_candidate(fe) and fe not in emails:
                                        emails.append(fe)
                                        email_provenance.append(make_fact(fe, "official_contact_page", source_url=source_url, observed=True, verified=True))
                                for fp in extract_phone_numbers(html):
                                    normalized, country = self._normalize_phone(fp, context)
                                    if normalized and normalized not in phones:
                                        phones.append(normalized)
                                        phone_provenance.append(self._phone_fact(normalized, country, "official_contact_page", source_url))
                                structured = extract_structured_contact_info(html)
                                for fe in structured.get("emails", []):
                                    if is_valid_email_candidate(fe) and fe not in emails:
                                        emails.append(fe)
                                        email_provenance.append(make_fact(fe, "official_structured_data", source_url=source_url, observed=True, verified=True))
                                for fp in structured.get("phones", []):
                                    normalized, country = self._normalize_phone(fp, context)
                                    if normalized and normalized not in phones:
                                        phones.append(normalized)
                                        phone_provenance.append(self._phone_fact(normalized, country, "official_structured_data", source_url))

        return emails, phones, email_provenance, phone_provenance, contact_page

    @staticmethod
    def _is_company_domain_url(url: str, domain: str) -> bool:
        if not url or not domain:
            return False
        host = urlparse(url).netloc.lower().split(":", 1)[0].lstrip("www.")
        expected = domain.lower().split(":", 1)[0].lstrip("www.")
        return host == expected or host.endswith(f".{expected}")

    def _contact_pages(self, context):
        extracted = context.baseline_extraction or {}
        urls = [extracted.get(key) for key in ("contact_page", "about_page", "team_page")]
        emails, phones, email_facts, phone_facts = [], [], [], []
        from extraction.page_extractor import extract_emails, extract_phone_numbers, extract_structured_contact_info
        for url in [item for item in urls if item]:
            html = context.cached_page(url)
            if not html:
                continue
            source = "official_contact_page" if "contact" in url.lower() else "official_company_page"
            for email in extract_emails(html):
                emails.append(email)
                email_facts.append(make_fact(email, source, source_url=url, observed=True, verified=False))
            for phone in extract_phone_numbers(html):
                normalized, country = self._normalize_phone(phone, context)
                if normalized:
                    phones.append(normalized)
                    phone_facts.append(self._phone_fact(normalized, country, source, url))
            structured = extract_structured_contact_info(html)
            for email in structured.get("emails", []):
                emails.append(email)
                email_facts.append(make_fact(email, "official_structured_data", source_url=url, observed=True, verified=False))
            for phone in structured.get("phones", []):
                normalized, country = self._normalize_phone(phone, context)
                if normalized:
                    phones.append(normalized)
                    phone_facts.append(self._phone_fact(normalized, country, "official_structured_data", url))
        return emails, phones, email_facts, phone_facts

    @staticmethod
    def _dedupe_facts(values, facts):
        selected, seen = [], set()
        for value in values:
            key = value.lower() if isinstance(value, str) else value
            if key not in seen:
                seen.add(key)
                selected.append(value)
        return selected, [fact for fact in facts if fact.get("value") in selected]

    @staticmethod
    def _region(context):
        domain = (context.domain or "").lower()
        return {"in": "IN", "co.in": "IN", "uk": "GB", "us": "US", "com": "US"}.get(domain.rsplit(".", 1)[-1], "US")

    def _normalize_phone(self, raw, context):
        try:
            parsed = phonenumbers.parse(raw, self._region(context))
            if not phonenumbers.is_valid_number(parsed):
                return None, None
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), phonenumbers.region_code_for_number(parsed)
        except phonenumbers.NumberParseException:
            return None, None

    @staticmethod
    def _rank_source(source: str, source_url: str = "") -> str:
        s = (source or "").lower()
        if s.startswith("official") or "contact_page" in s or "structured_data" in s:
            return "high"
        if "linkedin" in s or "directory" in s or "company" in s:
            return "medium"
        return "low"

    @staticmethod
    def _business_phone_context(text: str) -> bool:
        lowered = text.lower()
        # Reject obvious non-business or non-phone noise
        if any(term in lowered for term in (
            "fax", "order", "tracking", "personal", "whatsapp me",
            "invoice", "pincode", "zipcode", "zip code", "pin code",
            "vat", "gst", "ein", "license", "copyright", "isbn",
            "date of birth", "dob", "policy number", "tracking number",
        )):
            return False
        return True

    @staticmethod
    def _classify_phone_type(text: str) -> str:
        lowered = (text or "").lower()
        if any(term in lowered for term in ("sales", "inquiry", "enquiry", "business dev")):
            return "sales"
        if any(term in lowered for term in ("support", "helpdesk", "help desk", "customer care", "service")):
            return "support"
        if any(term in lowered for term in ("main", "headquarters", "hq", "head office", "corporate")):
            return "main_line"
        return "business_contact"

    @classmethod
    def _phone_fact(cls, number: str, country: str | None, source: str, source_url: str, phone_type: str = "business_contact") -> dict:
        rank = cls._rank_source(source, source_url)
        return {
            "value": number,
            "normalized_number": number,
            "country": country,
            "phone_type": phone_type,
            "source": source,
            "source_url": source_url or "",
            "observed": True,
            "verified": False,
            "confidence": rank,
            "source_rank": rank.upper(),
        }
