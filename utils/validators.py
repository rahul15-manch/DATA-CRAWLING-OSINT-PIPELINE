"""
utils/validators.py
===================
Reusable, pure validation functions for Pillar 1.

All functions are side-effect-free and independently testable.
They are shared across discovery, extraction, and main modules.
"""

import re

from utils.constants import (
    ARTICLE_AUTHOR_PREFIXES,
    EMAIL_IGNORE_PATTERNS,
    EMAIL_PRIORITY_PREFIXES,
    FORUM_DOMAIN_BLOCKLIST,
    GOVERNMENT_DOMAIN_SUFFIXES,
    PERSON_NAME_NOISE_WORDS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Phone validation  (Task 7)
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that LOOK like phones but are actually dates or year ranges.
# These are tested before any phone acceptance logic.
_DATE_REJECT_PATTERNS = [
    # DD.MM.YYYY  |  DD-MM-YYYY  |  DD/MM/YYYY
    re.compile(r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}$"),
    # YYYY-YYYY  or  YYYY – YYYY  (year ranges)
    re.compile(r"^\d{4}\s*[-–]\s*\d{4}$"),
    # "1950 - 1999 1950" style (year range with trailing year)
    re.compile(r"^\d{4}\s*[-–]\s*\d{4}\s+\d{4}$"),
    # Time ranges like "10.30-12.00" or "2.30-04.00"
    re.compile(r"^\d{1,2}\.\d{2}\s*[-–]\s*\d{2}\.\d{2}$"),
    # Pure year "2026" or "20260705" (8-digit date compact)
    re.compile(r"^\d{4}$"),
    re.compile(r"^\d{8}$"),
]

# A captured string must match this broad shape to even be considered
_PHONE_SHAPE = re.compile(r"^[+\d(][\d\s\-().]{5,20}[\d]$")

_MIN_PHONE_DIGITS = 7
_MAX_PHONE_DIGITS = 15


def is_valid_phone(text: str) -> bool:
    """
    Return True only for realistic phone number strings.

    Rejects
    -------
    - Multi-line strings (table data, newline-separated numbers)
    - Date patterns:  DD.MM.YYYY, DD-MM-YYYY, DD/MM/YYYY
    - Year ranges:    2025-2026, 1950 - 1999
    - Time ranges:    10.30-12.00
    - Too few or too many digits

    Accepts
    -------
    - +91XXXXXXXXXX, +1 877.319.9304
    - 9876543210, 9876543210
    - 011-27871018, (408)5551234
    """
    if not text:
        return False

    text = text.strip()

    # Multi-line strings are never phone numbers
    if "\n" in text or "\r" in text:
        return False

    # Reject date / year-range patterns first (cheap check)
    for pattern in _DATE_REJECT_PATTERNS:
        if pattern.match(text):
            return False

    # Count pure digit characters
    digits_only = re.sub(r"\D", "", text)
    if len(digits_only) < _MIN_PHONE_DIGITS or len(digits_only) > _MAX_PHONE_DIGITS:
        return False

    # Ensure the string has a phone-like shape
    if not _PHONE_SHAPE.match(text):
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# URL validators  — government & forum rejection
# ─────────────────────────────────────────────────────────────────────────────

def is_government_url(url: str) -> bool:
    """
    Return True if the URL belongs to a government domain.

    Checks both TLD suffixes (.gov, .gov.in, .nic.in, etc.) and common
    government hostname keywords.

    Examples
    --------
    is_government_url("https://data.gov.in/resource/...")   # True
    is_government_url("https://acme.com")                    # False
    """
    if not url:
        return False
    lower = url.lower()
    for suffix in GOVERNMENT_DOMAIN_SUFFIXES:
        # Match against the netloc portion: the suffix must appear before
        # the first slash after the scheme (or at end of string).
        # Simple approach: check that the suffix appears in the host part.
        try:
            from urllib.parse import urlparse
            host = urlparse(lower).netloc
            if host.endswith(suffix) or (suffix.lstrip(".") in host.split(".")):
                return True
        except Exception:
            if suffix in lower:
                return True
    return False


def is_forum_url(url: str) -> bool:
    """
    Return True if the URL belongs to a known forum / community platform.

    Examples
    --------
    is_forum_url("https://www.reddit.com/r/...")     # True
    is_forum_url("https://stackoverflow.com/q/...") # True
    is_forum_url("https://acme.com")                 # False
    """
    if not url:
        return False
    lower = url.lower()
    for domain in FORUM_DOMAIN_BLOCKLIST:
        if domain in lower:
            return True
    return False


def is_lead_url_valid(url: str) -> bool:
    """
    Combined URL gate: reject government and forum URLs.

    Use this single call in the discovery pipeline instead of calling
    is_government_url and is_forum_url separately.
    """
    return not is_government_url(url) and not is_forum_url(url)


# ─────────────────────────────────────────────────────────────────────────────
# Email validation and ranking  (Task 6)
# ─────────────────────────────────────────────────────────────────────────────

def _email_priority(email: str) -> int:
    """Lower index = higher priority in output list."""
    local = email.split("@")[0].lower()
    for i, prefix in enumerate(EMAIL_PRIORITY_PREFIXES):
        if local == prefix or local.startswith(prefix):
            return i
    return len(EMAIL_PRIORITY_PREFIXES)  # lowest priority bucket


def _is_ignored_email(email: str) -> bool:
    """Return True for system/automation emails that are not real contacts."""
    local = email.split("@")[0].lower()
    return any(pat in local for pat in EMAIL_IGNORE_PATTERNS)


def rank_emails(emails: list) -> list:
    """
    Remove junk emails and sort the remainder by business relevance.

    Priority order:  founder > ceo > cto > … > support
    Filtered:        noreply, tracking, unsubscribe, notifications, etc.

    Returns a deduplicated, sorted new list. Input is not mutated.
    """
    cleaned = [e for e in emails if e and not _is_ignored_email(e)]
    return sorted(set(cleaned), key=_email_priority)


# ─────────────────────────────────────────────────────────────────────────────
# Person / name validation  (Task 8)
# ─────────────────────────────────────────────────────────────────────────────

# Characters allowed in a human name (letters, space, hyphen, apostrophe, dot)
_NAME_CHARS = re.compile(r"^[A-Za-z][A-Za-z.\-' ]{1,59}$")


def is_valid_person_name(name: str) -> bool:
    """
    Return True only when the string plausibly represents a real human name.

    Rules
    -----
    - Must be 2 to 5 space-separated words
    - No digits anywhere
    - No PERSON_NAME_NOISE_WORDS (Certificate, Course, College, …)
    - No special characters beyond  . - ' (space)
    - Not an address fragment (contains : & @ / \\ ,)

    Accepts:   "Thomas Kurian",  "Satya Nadella",  "Rahul Sharma"
    Rejects:   "Certificate",  "Best College Recommendations",
               "Corporate & Communications Address:",  None,  "CTO"
    """
    if not name:
        return False

    name = name.strip()
    if not name:
        return False

    # ─ Strip article author prefixes ("By ...", "Written by ...", etc.) ───
    lower_check = name.lower()
    for prefix in ARTICLE_AUTHOR_PREFIXES:
        if lower_check.startswith(prefix):
            name = name[len(prefix):].strip()
            if not name:
                return False
            lower_check = name.lower()
            break

    words = name.split()
    if len(words) < 2 or len(words) > 5:
        return False

    # No digits in a person name
    if re.search(r"\d", name):
        return False

    # Must match the allowed character set
    if not _NAME_CHARS.match(name):
        return False

    # Reject address / structural fragments
    if any(ch in name for ch in (":", "&", "@", "/", "\\", ",")):
        return False

    # Reject noise words (case-insensitive substring match)
    lowered = name.lower()
    for noise in PERSON_NAME_NOISE_WORDS:
        if noise in lowered:
            return False

    return True


def is_valid_person_record(person: dict) -> bool:
    """
    Return True only when a person dict has BOTH a valid name and a designation.

    A designation alone (with a bad/missing name) is never enough.
    """
    name = (person.get("name") or "").strip()
    designation = (person.get("designation") or "").strip()
    return bool(designation) and is_valid_person_name(name)

def is_valid_company_name(name: str) -> bool:
    """
    Return True if the company name is valid, rejecting common placeholders like 'About Us'.
    """
    from utils.constants import COMPANY_NAME_NOISE_WORDS
    if not name:
        return False
    name = name.strip()
    if not name or len(name) < 2:
        return False
    
    # Fast reject if it exactly matches a noise word
    lowered = name.lower()
    if lowered in COMPANY_NAME_NOISE_WORDS:
        return False
        
    return True
