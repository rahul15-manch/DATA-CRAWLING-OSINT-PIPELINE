"""
semantic/company_semantic_extractor.py
======================================
Parses crawled HTML or search result snippets into a structured CompanyProfile
with provenance mapping, company type classification, and confidence scoring.
"""

import time
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from semantic.semantic_profile import CompanyProfile
from semantic.ontology_manager import ConceptNormalizer

class CompanySemanticExtractor:
    def __init__(self):
        pass

    def extract_from_snippet(self, title: str, snippet: str, url: str, ontology_version: str) -> CompanyProfile:
        """Lightweight extraction from Search Snippet (Title + Snippet + URL)."""
        profile = CompanyProfile(ontology_version=ontology_version, is_snippet=True)
        profile.last_crawled = time.strftime("%Y-%m-%d")
        
        # Populate description
        profile.description = {
            "value": snippet,
            "source": "search_snippet"
        }
        profile.sections["homepage"] = title
        
        # Parse title for company name / technology hint
        combined_text = (title + " " + snippet).lower()
        
        # Match common role hints for positions
        roles_list = ["engineer", "developer", "founder", "ceo", "director", "manager", "team", "president", "architect", "programmer"]
        for role in roles_list:
            if re.search(r'\b' + re.escape(role) + r'\b', combined_text):
                profile.positions.append({
                    "value": role.title(),
                    "source": "title_or_snippet"
                })
                
        # Detect locations from title/snippet
        # Populate website for non-platform direct URLs in snippet
        from urllib.parse import urlparse
        from utils.constants import PLATFORM_DOMAINS
        domain = urlparse(url or "").netloc.lower()
        is_platform = any(platform in domain for platform in PLATFORM_DOMAINS)
        if not is_platform:
            profile.website = url
            profile.website_source = "homepage"

        # Guess company type from URL
        profile.company_type = self._classify_type(combined_text, url)
        
        # Calculate profile confidence (lower for snippet-only)
        profile.profile_confidence = 0.4
        
        return profile

    def extract_from_html(self, html: str, url: str, ontology_version: str, concepts: set[str] = None) -> CompanyProfile:
        """Deep extraction from crawled homepage HTML content."""
        profile = CompanyProfile(ontology_version=ontology_version)
        profile.last_crawled = time.strftime("%Y-%m-%d")
        
        soup = BeautifulSoup(html, "html.parser")

        # Extract website
        web_url, web_src = self._extract_website(soup, html, url)
        profile.website = web_url
        profile.website_source = web_src
        
        # 1. Populate Description from head tags
        meta_desc = ""
        meta_source = "meta_description"
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag:
            meta_desc = meta_tag.get("content", "")
        if not meta_desc:
            og_tag = soup.find("meta", attrs={"property": "og:description"})
            if og_tag:
                meta_desc = og_tag.get("content", "")
                meta_source = "og_description"

        # Extract meta keywords
        meta_keywords = ""
        keywords_tag = soup.find("meta", attrs={"name": "keywords"})
        if keywords_tag:
            meta_keywords = keywords_tag.get("content", "").strip()

        # Parse JSON-LD blocks recursively
        json_ld_text = ""
        for script in soup.find_all("script", type="application/ld+json"):
            if script.string:
                try:
                    import json as pyjson
                    data = pyjson.loads(script.string)
                    def extract_metadata_from_json(obj):
                        vals = []
                        if isinstance(obj, dict):
                            for key in ("description", "keywords", "industry", "knowsAbout", "about", "name", "serviceType"):
                                if key in obj:
                                    val = obj[key]
                                    if isinstance(val, (str, int, float)):
                                        vals.append(str(val))
                                    elif isinstance(val, list):
                                        vals.extend(str(item) for item in val if isinstance(item, (str, int, float)))
                                    elif isinstance(val, dict):
                                        vals.append(val.get("name", ""))
                            for v in obj.values():
                                if isinstance(v, (dict, list)):
                                    vals.extend(extract_metadata_from_json(v))
                        elif isinstance(obj, list):
                            for item in obj:
                                vals.extend(extract_metadata_from_json(item))
                        return vals
                    
                    extracted_vals = extract_metadata_from_json(data)
                    clean_vals = [v.strip() for v in extracted_vals if v and v.strip()]
                    if clean_vals:
                        json_ld_text += " " + " ".join(clean_vals)
                except Exception:
                    pass

        additional_metadata = ""
        if meta_keywords:
            additional_metadata += f" Keywords: {meta_keywords}."
        if json_ld_text:
            additional_metadata += f" JSON-LD: {json_ld_text}."
                
        profile.description = {
            "value": (meta_desc.strip() + additional_metadata).strip(),
            "source": meta_source
        }
        
        # 2. Extract structured sections
        body = soup.find("body")
        profile.sections["homepage"] = " ".join(body.get_text().split())[:8000] if body else ""
        
        # Parse head tags for OG / JSON-LD / Schema
        og_tag_title = soup.find("meta", attrs={"property": "og:title"})
        og_title = og_tag_title.get("content", "") if og_tag_title else ""
        
        # Parse links to populate sub-page sections
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text().lower()
            if "about" in href or "about" in text or "who-we-are" in href:
                profile.sections["about"] += " " + a.get_text() + " (" + a["href"] + ")"
            if any(term in href or term in text for term in ("services", "solutions", "what-we-do", "work")):
                profile.sections["services"] += " " + a.get_text() + " (" + a["href"] + ")"
            if any(term in href or term in text for term in ("careers", "jobs", "join-us", "vacancy")):
                profile.sections["careers"] += " " + a.get_text() + " (" + a["href"] + ")"
            if any(term in href or term in text for term in ("blog", "articles", "news")):
                profile.sections["blog"] += " " + a.get_text() + " (" + a["href"] + ")"
            if "product" in href or "product" in text:
                profile.sections["products"] += " " + a.get_text() + " (" + a["href"] + ")"

        # Compile full corp text
        full_text = (
            profile.sections["homepage"] + " " +
            profile.sections["about"] + " " +
            profile.sections["services"] + " " +
            profile.sections["careers"]
        ).lower()

        # 3. Extract Technologies & Products using concepts mapping
        if concepts:
            for term in concepts:
                norm_term = ConceptNormalizer.normalize(term)
                pattern = r'\b' + re.escape(term.lower()) + r'\b'
                if re.search(pattern, full_text):
                    # Guess if it is tech or product
                    source = "homepage"
                    if term.lower() in profile.sections["services"].lower():
                        source = "services_page"
                        
                    profile.technologies.append({
                        "value": norm_term,
                        "source": source
                    })

        # 4. Extract Roles/Positions
        roles_list = ["engineer", "developer", "founder", "ceo", "director", "manager", "team", "president", "architect", "programmer"]
        for role in roles_list:
            pattern = r'\b' + re.escape(role) + r'\b'
            if re.search(pattern, full_text):
                source = "homepage"
                if role in profile.sections["careers"].lower():
                    source = "careers_page"
                profile.positions.append({
                    "value": role.title(),
                    "source": source
                })

        # 5. Extract Certifications
        cert_patterns = ["iso 9001", "iso 27001", "hipaa", "soc 2", "gdpr", "pci-dss"]
        for cert in cert_patterns:
            if cert in full_text:
                profile.certifications.append(cert.upper())
                
        # 6. Extract Partners
        partner_patterns = ["aws partner", "microsoft partner", "google cloud partner", "salesforce partner"]
        for partner in partner_patterns:
            if partner in full_text:
                profile.partners.append(partner.title())

        # 7. Classify Company Type
        profile.company_type = self._classify_type(full_text, url)
        
        # 8. Compute Profile Confidence [0.0 - 1.0] dynamically
        base_confidence = 0.4
        
        # Text length density bonus
        word_count = len(profile.sections["homepage"].split())
        word_bonus = 0.0
        if word_count > 300:
            word_bonus = 0.2
        elif word_count > 100:
            word_bonus = 0.1
        elif word_count < 30:
            word_bonus = -0.1
            
        # Structured metadata tags presence bonus
        has_json_ld = bool(soup.find("script", attrs={"type": "application/ld+json"}))
        has_schema = bool(soup.find(attrs={"itemtype": re.compile(r"schema\.org")}))
        has_og = bool(soup.find("meta", attrs={"property": re.compile(r"^og:")}))
        meta_bonus = 0.0
        if has_json_ld: meta_bonus += 0.1
        if has_schema: meta_bonus += 0.1
        if has_og: meta_bonus += 0.1
        
        # Extraction consistency & signals bonus
        signals_bonus = 0.0
        if profile.description.get("value"): signals_bonus += 0.1
        if len(profile.technologies) > 0: signals_bonus += 0.1
        if len(profile.positions) > 0: signals_bonus += 0.1
        if profile.sections["services"] or profile.sections["about"]: signals_bonus += 0.1
        
        profile.profile_confidence = round(min(1.0, max(0.1, base_confidence + word_bonus + meta_bonus + signals_bonus)), 2)
        
        return profile

    def _classify_type(self, text: str, url: str) -> str:
        """Classify website into B2B, B2C, NGO, Gov, Education, Open Source, etc."""
        text_lower = text.lower()
        domain = urlparse(url).netloc.lower()
        
        # Check domain endings
        if domain.endswith(".org") and not any(k in domain for k in ("stripe", "paypal")):
            # Check if it is educational or non-profit
            if any(k in text_lower for k in ("foundation", "non-profit", "community", "open source")):
                return "Open Source"
            return "NGO"
        if domain.endswith(".edu") or any(k in domain for k in ("college", "univ", "school")):
            return "Education"
        if domain.endswith(".gov") or domain.endswith(".nic.in") or ".gov." in domain:
            return "Government"
            
        # Check text signals
        scores = {
            "B2B Software": len(re.findall(r'\b(b2b|enterprise|saas|software engineering|solutions provider|it services)\b', text_lower)),
            "B2C/Marketplace": len(re.findall(r'\b(shop|store|buy|cart|consumer|ecommerce|marketplace|shipping|retail)\b', text_lower)),
            "NGO": len(re.findall(r'\b(non-profit|charity|donation|ngo|association|society)\b', text_lower)),
            "Education": len(re.findall(r'\b(syllabus|course|university|college|academy|learn|tutorial)\b', text_lower)),
            "Consultancy": len(re.findall(r'\b(consulting|consultancy|agency|firm|services firm)\b', text_lower)),
        }
        
        max_type = max(scores, key=scores.get)
        if scores[max_type] > 0:
            return max_type
            
        return "B2B Software"  # Default fallback

    def _extract_website(self, soup, html: str, url: str) -> tuple[str, str]:
        """Extract company website and its source attribution from parsed profile or direct URL."""
        if not url:
            return "", ""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        
        from utils.constants import PLATFORM_DOMAINS
        is_platform = any(platform in domain for platform in PLATFORM_DOMAINS)
        if not is_platform:
            return url, "homepage"

        # A. LinkedIn company profile redirect link or text
        if "linkedin.com" in domain:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if "linkedin.com/redir/redirect" in href:
                    import urllib.parse as up
                    parsed_href = up.urlparse(href)
                    query_params = up.parse_qs(parsed_href.query)
                    target_url = query_params.get("url")
                    if target_url:
                        return target_url[0], "linkedin"
            # Text regex search fallback for "Website <url> External link"
            text_content = soup.get_text()
            match = re.search(r"\bWebsite\s+(https?://[^\s]+)", text_content)
            if match:
                clean_url = match.group(1).strip().rstrip("/").rstrip(")")
                return clean_url, "linkedin"

        # B. General platform: look for button anchors
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text().strip().lower()
            if text in {"visit website", "website", "visit site", "website link", "go to website"}:
                href_lower = href.lower()
                if href.startswith("http") and not any(p in href_lower for p in PLATFORM_DOMAINS):
                    src = "schema"
                    if "clutch.co" in domain:
                        src = "clutch"
                    elif "goodfirms.co" in domain:
                        src = "goodfirms"
                    return href, src

        # C. Search links inside HTML for non-platform links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("http") and not any(p in href.lower() for p in PLATFORM_DOMAINS):
                if not any(soc in href.lower() for soc in ["facebook.com", "twitter.com", "instagram.com", "youtube.com", "google.com", "apple.com"]):
                    return href, "inferred"

        return "", ""
