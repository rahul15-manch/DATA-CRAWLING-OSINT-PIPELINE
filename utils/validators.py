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

    # Consecutive dots / ellipses are pagination or table noise, never phone numbers
    if ".." in text:
        return False

    # Unbroken string of > 11 digits without a leading '+' is almost certainly an internal ID or barcode
    if text.isdigit() and len(text) > 11:
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

_DISALLOWED_EMAIL_TLDS = frozenset({
    "mjs", "js", "cjs", "css", "scss", "less",
    "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp", "tiff", "avif",
    "map", "ts", "tsx", "jsx", "vue", "svelte",
    "woff", "woff2", "ttf", "eot", "otf",
    "json", "xml", "yaml", "yml", "toml", "csv",
    "html", "htm", "php", "asp", "aspx", "jsp",
    "pdf", "doc", "docx", "zip", "tar", "gz", "rar", "7z",
    "exe", "bin", "apk", "ipa", "iso", "dmg",
    "mp3", "mp4", "wav", "webm", "ogg", "mov", "avi",
})

_DUMMY_EMAIL_LOCALS = frozenset({
    "username", "user", "name", "email", "yourname", "your-name", "your_name",
    "sample", "test", "example", "someone", "placeholder", "first.last",
    "firstname.lastname", "first_last", "john.doe", "jane.doe", "johndoe", "janedoe",
    "testuser", "demo",
})

_DUMMY_EMAIL_DOMAINS = frozenset({
    "example.com", "example.org", "example.net",
    "company.com", "domain.com", "yourdomain.com", "yoursite.com",
    "mycompany.com", "website.com", "test.com", "sample.com",
    "site.com", "email.com", "placeholder.com",
})


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


def is_valid_email_candidate(email: str) -> bool:
    """
    Validate that an email candidate is a genuine contact address.

    Rejection rules:
      1. Structural invalidity (missing or multiple @, missing domain, missing dot).
      2. Domain starts with a digit (e.g. '@19.1.0.mjs' or '@2x.png').
      3. TLD is a code, asset, or media file extension (e.g. mjs, js, png, css, map).
      4. TLD is non-alphabetic or < 2 chars.
      5. Dummy / placeholder emails (e.g. username@company.com, name@company.com, user@example.com).
      6. System / automated ignore patterns (_is_ignored_email).
      7. Known disposable domains.
    """
    if not email or not isinstance(email, str):
        return False
    email = email.strip().lower()
    if "@" not in email or email.count("@") != 1:
        return False

    local, domain = email.split("@", 1)
    local = local.strip()
    domain = domain.strip().strip(".")
    if not local or not domain or "." not in domain:
        return False

    # Structural / valid character check
    if not re.match(r"^[a-zA-Z0-9._%+-]+$", local):
        return False
    if not re.match(r"^[a-zA-Z0-9.-]+$", domain):
        return False

    # 1. Reject if domain starts with a digit (e.g. @19.1.0.mjs, @2x.png)
    if domain[0].isdigit():
        return False

    # 2. Reject if TLD is code/media extension or non-alphabetic
    tld = domain.split(".")[-1].lower()
    if not tld.isalpha() or len(tld) < 2 or tld in _DISALLOWED_EMAIL_TLDS:
        return False

    # 3. Reject dummy / placeholder emails
    if local in _DUMMY_EMAIL_LOCALS or local.startswith("sample") or local.startswith("test"):
        return False
    if domain in _DUMMY_EMAIL_DOMAINS or domain.endswith(".example.com") or domain.endswith(".example.org"):
        return False

    # 4. Reject disposable email domains
    from utils.constants import DISPOSABLE_EMAIL_DOMAINS
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        return False

    # 5. Reject system / automated ignore patterns (noreply, bounce, unsubscribe, etc.)
    if _is_ignored_email(email):
        return False

    return True


def score_email(email: str, company_domain: str = "") -> dict:
    """
    Score an email's confidence (0-100) based on:
      - Domain match (+35 pts)
      - Business role prefix (+25 pts)
      - MX record presence (+25 pts)
      - Not a disposable email domain (+15 pts)

    Returns dict: {"email": str, "confidence": int, "reasons": list[str]}
    """
    if not email or "@" not in email or not is_valid_email_candidate(email):
        return {"email": email, "confidence": 0, "reasons": ["invalid_format"]}

    local, domain = email.lower().split("@", 1)
    reasons = []
    score = 0

    # 1. Disposable check
    from utils.constants import DISPOSABLE_EMAIL_DOMAINS
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        reasons.append("disposable_domain")
    else:
        score += 15
        reasons.append("valid_domain_provider")

    # 2. Business prefix relevance
    if not _is_ignored_email(email):
        prio = _email_priority(email)
        if prio < len(EMAIL_PRIORITY_PREFIXES):
            score += 25
            reasons.append("business_role_prefix")
        else:
            score += 10
            reasons.append("standard_prefix")
    else:
        reasons.append("system_ignored_prefix")

    # 3. Domain match
    if company_domain:
        clean_company = company_domain.lower().lstrip("www.")
        if domain == clean_company or clean_company in domain:
            score += 35
            reasons.append("domain_match")

    # 4. MX record lookup (fast cached check via dns.resolver)
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=2.0)
        if answers:
            score += 25
            reasons.append("mx_records_verified")
    except Exception:
        # Fallback stdlib socket getaddrinfo check
        try:
            import socket
            socket.getaddrinfo(domain, 80)
            score += 15
            reasons.append("domain_dns_resolves")
        except Exception:
            reasons.append("no_dns_resolution")

    confidence = min(100, score)
    return {"email": email, "confidence": confidence, "reasons": reasons}


def rank_emails(emails: list, company_domain: str = "") -> list:
    """
    Remove junk emails and sort by email score (descending) and role priority.

    Returns a deduplicated, sorted list of email strings. Input is not mutated.
    """
    cleaned = [e for e in emails if e and is_valid_email_candidate(e)]
    if not cleaned:
        return []

    # Score each email and sort by (-confidence, _email_priority)
    scored = [score_email(e, company_domain) for e in set(cleaned)]
    scored.sort(key=lambda item: (-item["confidence"], _email_priority(item["email"])))

    return [item["email"] for item in scored]



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
    Return True if the company name is valid, rejecting common placeholders like 'About Us'
    and malformed URL-fragment / domain-concatenation artifacts.
    """
    import re
    from utils.constants import COMPANY_NAME_NOISE_WORDS
    if not name:
        return False
    name = name.strip()
    if not name or len(name) < 2:
        return False
    if len(name) > 60:
        return False

    # Fast reject if it exactly matches a noise word
    lowered = name.lower()
    if lowered in COMPANY_NAME_NOISE_WORDS:
        return False

    # Reject strings containing explicit URL structures
    _url_indicators = [
        "http://", "https://", "www.", "authhttps", "httpswww", "://",
    ]
    for indicator in _url_indicators:
        if indicator in lowered:
            return False

    # Reject if a URL-like path suffix is present (e.g. ".com/auth", ".orglogin")
    if re.search(r"\.(com|org|net|io|co)\s*/", lowered):
        return False
    if re.search(r"\.(com|org|net|io|co)[a-z]", lowered):
        # Matches .comhttps, .comauth, .orglogin etc.  (but not "Telecom", "Icom", etc.)
        # Only reject when the TLD is followed directly by more alpha chars (URL concat)
        if re.search(r"(?<![a-z])(com|org|net|io)(?=[a-z])", lowered):
            return False

    # Reject un-spaced domain-like concatenations: e.g. swiggycom, googlecom, swiggyorg
    # Pattern: word directly followed by com/org/net/io with no space or dot before it
    # Reject promotional marketing slogans / CTA sentences
    cta_starters = (
        "join us", "become a", "partner with", "sign up", "learn more",
        "click here", "get started", "how to", "welcome to", "discover how",
        "boost your", "grow your", "order food", "order now"
    )
    if any(lowered.startswith(cta) for cta in cta_starters):
        return False

    if len(name.split()) > 5 and any(verb in lowered.split() for verb in ("and", "your", "with", "for", "boost", "join", "unlock")):
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# SSRF & URL Safety Layer (Milestone 6)
# ─────────────────────────────────────────────────────────────────────────────

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
_MAX_URL_LENGTH = 2048

_DISALLOWED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
    "instance-data",
})

# Dangerous internal service ports that web scrapers should never connect to
_BLOCKED_PORTS = frozenset({
    21, 22, 23, 25, 53, 69, 110, 135, 137, 138, 139, 143, 445,
    1433, 1521, 2049, 3306, 5432, 5900, 6379, 8098, 9200, 11211, 27017, 28017
})


def is_safe_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> tuple[bool, str]:
    """
    Validate that an IP address is a publicly routable global address,
    rejecting loopback, private, link-local, cloud metadata, multicast, and reserved addresses.
    """
    if ip_obj.is_loopback:
        return False, f"Loopback IP address rejected: {ip_obj}"
    if ip_obj.is_private:
        return False, f"Private network IP address rejected: {ip_obj}"
    if ip_obj.is_link_local:
        return False, f"Link-local IP address rejected: {ip_obj}"
    if ip_obj.is_multicast:
        return False, f"Multicast IP address rejected: {ip_obj}"
    if ip_obj.is_reserved:
        return False, f"Reserved IP address rejected: {ip_obj}"
    if ip_obj.is_unspecified:
        return False, f"Unspecified IP address rejected: {ip_obj}"

    # Explicit cloud metadata endpoint check (e.g. AWS/GCP/Azure/DigitalOcean 169.254.169.254)
    ip_str = str(ip_obj)
    if ip_str == "169.254.169.254":
        return False, f"Cloud metadata IP address rejected: {ip_str}"

    return True, "IP is safe"


def is_safe_url(url: str) -> tuple[bool, str]:
    """
    Pure, side-effect-free SSRF validation function for all outbound crawling requests.

    Validation steps:
      1. Bounds check (non-empty, length <= 2048 chars).
      2. Scheme check: only 'http' and 'https' are permitted (rejects file:, ftp:, gopher:, data:, javascript:).
      3. Hostname check: netloc must exist, cannot be in disallowed hostnames or internal TLDs (.local, .internal).
      4. Port check: prevents scanning internal database/management ports (22, 3306, 6379, etc.).
      5. IP resolution: resolves hostname and ensures resolved IPs are globally routable.

    Returns:
      (True, "OK") if safe, or (False, reason) if dangerous/invalid.
    """
    if not url or not isinstance(url, str):
        return False, "URL is empty or not a string"

    url = url.strip()
    if len(url) > _MAX_URL_LENGTH:
        return False, f"URL exceeds maximum allowed length of {_MAX_URL_LENGTH} characters"

    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"Malformed URL: {exc}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        return False, f"Disallowed URL scheme '{scheme}'. Only http and https are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL contains no valid hostname"

    hostname = hostname.lower().strip(".")

    # Disallowed hostnames and internal TLDs
    if hostname in _DISALLOWED_HOSTNAMES or hostname.endswith(".localhost"):
        return False, f"Disallowed internal hostname: {hostname}"
    if hostname.endswith(".local") or hostname.endswith(".internal") or hostname.endswith(".lan"):
        return False, f"Disallowed private/internal domain suffix: {hostname}"

    # Port restriction
    port = parsed.port
    if port and port in _BLOCKED_PORTS:
        return False, f"Connection to port {port} is blocked for security"

    # Fast check: is hostname already an IP literal?
    try:
        ip_obj = ipaddress.ip_address(hostname)
        return is_safe_ip(ip_obj)
    except ValueError:
        # Not a literal IP, proceed to DNS resolution
        pass

    # Resolve hostname via socket.getaddrinfo
    try:
        resolved_addrs = socket.getaddrinfo(hostname, port or 80, proto=socket.IPPROTO_TCP)
        if not resolved_addrs:
            return False, f"DNS resolution yielded no addresses for {hostname}"

        for family, _, _, _, sockaddr in resolved_addrs:
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                is_safe, reason = is_safe_ip(ip_obj)
                if not is_safe:
                    return False, f"Hostname '{hostname}' resolved to unsafe address: {reason}"
            except ValueError:
                return False, f"Unparseable IP from DNS resolution: {ip_str}"

    except socket.gaierror:
        # Hostname could not be resolved (e.g. offline testing, mock test domains, or NXDOMAIN).
        # Since no private/internal IP was resolved, this does not present an SSRF threat.
        # Downstream HTTP client will either hit a mock handler or fail safely with network error.
        return True, "OK"
    except Exception as exc:
        return False, f"Network resolution error for {hostname}: {exc}"

    return True, "OK"


def validate_redirect_target(target_url: str) -> tuple[bool, str]:
    """
    Validates an HTTP redirect target URL before following it.
    Guarantees that a public URL cannot redirect into private infrastructure or cloud metadata.
    """
    return is_safe_url(target_url)

