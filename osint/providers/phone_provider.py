"""
osint/providers/phone_provider.py
=================================
Phone number parsing, validation, and E.164 formatting provider.
Reuses the verified phonenumbers library.
"""

import asyncio
import re
from typing import Any, Dict, List
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus

try:
    import phonenumbers
except ImportError:
    phonenumbers = None


class PhoneValidationProvider(BaseOSINTProvider):
    name = "phone_validation"
    capability = ProviderCapability.PHONE
    default_timeout = 3.0

    def _validate_single_phone(self, raw_phone: str, default_region: str = "IN") -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "raw": raw_phone,
            "valid": False,
            "e164": None,
            "country_code": None,
        }

        if not phonenumbers:
            info["error"] = "phonenumbers_library_missing"
            return info

        cleaned = re.sub(r"^(?:phone|tel(?:ephone)?|call(?:\s*us)?|mob(?:ile)?|fax|contact|ph)\s*[:\-]?\s*", "", raw_phone.strip(), flags=re.I).strip()
        if not cleaned or len(cleaned) < 5:
            return info

        for region in [default_region, "US", "GB", "CA", "AU"]:
            try:
                parsed = phonenumbers.parse(cleaned, region)
                if phonenumbers.is_valid_number(parsed):
                    info["valid"] = True
                    info["e164"] = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                    info["national"] = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
                    info["country_code"] = parsed.country_code
                    return info
                elif phonenumbers.is_possible_number(parsed) and not info.get("e164"):
                    info["possible_e164"] = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            except Exception:
                continue

        return info

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        phones = lead.phones or []
        if not phones:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.NO_RESULT,
                data={"verified_phones": []},
                evidence={"reason": "no_phones_available"},
            )

        if not phonenumbers:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.NOT_AVAILABLE,
                error="phonenumbers library is not installed",
            )

        results = await asyncio.to_thread(lambda: [self._validate_single_phone(p) for p in phones])

        valid_phones = [r["e164"] for r in results if r.get("valid") and r.get("e164")]
        if not valid_phones:
            # Fall back to possible e164 if valid strictly fails
            valid_phones = [r["possible_e164"] for r in results if r.get("possible_e164")]

        data = {
            "verified_phones": valid_phones,
            "phone_details": results,
        }

        evidence = {
            "input_phone_count": len(phones),
            "validated_phone_count": len(valid_phones),
        }

        return ProviderResult(
            provider=self.name,
            capability=self.capability,
            status=ProviderStatus.SUCCESS if valid_phones else ProviderStatus.NO_RESULT,
            data=data,
            evidence=evidence,
        )
