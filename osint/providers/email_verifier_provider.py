"""
osint/providers/email_verifier_provider.py
=========================================
Email syntax, domain MX, and optional Scout SMTP handshake verifier provider.
"""

import asyncio
import os
from typing import Any, Dict, List
from models.lead_record import LeadRecord
from osint.base import BaseOSINTProvider
from osint.models import ProviderCapability, ProviderResult, ProviderStatus
from utils.validators import is_valid_email_candidate


class EmailVerificationProvider(BaseOSINTProvider):
    name = "email_verifier"
    capability = ProviderCapability.EMAIL_VERIFICATION
    default_timeout = 5.0

    def __init__(self, timeout: float = 5.0, enable_smtp_handshake: bool = False):
        super().__init__(timeout=timeout)
        self.enable_smtp = enable_smtp_handshake or os.getenv("ENABLE_SMTP_VERIFICATION", "false").lower() in ("true", "1", "yes")

    def _verify_email(self, email: str) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "email": email,
            "syntax_valid": False,
            "deliverable": None,
            "status": "unverified",
        }

        if not is_valid_email_candidate(email):
            info["status"] = "syntax_invalid"
            return info

        info["syntax_valid"] = True
        info["status"] = "syntax_ok"

        # Check domain MX
        try:
            domain = email.split("@")[-1].strip().lower()
            import dns.resolver
            ans = dns.resolver.resolve(domain, "MX", lifetime=2.0)
            if ans:
                info["mx_valid"] = True
                info["status"] = "mx_verified"
        except Exception:
            info["mx_valid"] = False

        # Optional Scout SMTP handshake
        if self.enable_smtp:
            try:
                from scout_smtp_verifier import verify_email_via_scout_smtp
                ok, reason = verify_email_via_scout_smtp(email, timeout=2.0)
                info["smtp_checked"] = True
                info["smtp_deliverable"] = ok
                info["smtp_reason"] = reason
                if ok:
                    info["status"] = "smtp_verified"
                    info["deliverable"] = True
            except Exception as exc:
                info["smtp_error"] = str(exc)

        return info

    async def enrich(self, lead: LeadRecord) -> ProviderResult:
        emails = lead.emails or []
        if not emails:
            return ProviderResult(
                provider=self.name,
                capability=self.capability,
                status=ProviderStatus.NO_RESULT,
                data={"verified_emails": []},
                evidence={"reason": "no_emails_to_verify"},
            )

        results = await asyncio.to_thread(lambda: [self._verify_email(e) for e in emails])

        valid_emails = [r["email"] for r in results if r.get("syntax_valid") and r.get("mx_valid", True)]
        invalid_emails = [r["email"] for r in results if not r.get("syntax_valid")]

        data = {
            "verified_emails": valid_emails,
            "invalid_emails": invalid_emails,
            "verification_details": results,
        }

        evidence = {
            "total_tested": len(emails),
            "valid_count": len(valid_emails),
            "smtp_enabled": self.enable_smtp,
        }

        return ProviderResult(
            provider=self.name,
            capability=self.capability,
            status=ProviderStatus.SUCCESS if valid_emails else ProviderStatus.NO_RESULT,
            data=data,
            evidence=evidence,
        )
