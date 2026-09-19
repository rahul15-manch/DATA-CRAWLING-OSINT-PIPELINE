import pytest
from search.google_scheduler import get_query_expectation_score
from discovery.company_discovery import interleave_urls_by_domain

def test_query_expectation_scores():
    # High expectation queries (generic B2B / location searches)
    assert get_query_expectation_score("hardware software company") == 1.0
    assert get_query_expectation_score("custom software Noida") == 1.0
    assert get_query_expectation_score("python development firm") == 1.0
    
    # Moderate expectation queries (platform site searches without quotes)
    assert get_query_expectation_score("site:linkedin.com/company python Noida") == 0.6
    assert get_query_expectation_score("site:clutch.co automation company") == 0.6
    
    # Low expectation queries (quoted/complex dorks)
    assert get_query_expectation_score('site:clutch.co "custom software Noida"') == 0.2
    assert get_query_expectation_score('site:linkedin.com/company "AI" Noida -site:wikipedia.org') == 0.2


def test_directory_url_interleaving():
    candidates = [
        ("https://goodfirms.co/company/aero-leads", "GoodFirms", "automation"),
        ("https://goodfirms.co/company/tech-firm", "GoodFirms", "automation"),
        ("https://clutch.co/profile/aero-leads", "Clutch", "automation"),
        ("https://clutch.co/profile/tech-firm", "Clutch", "automation"),
        ("https://linkedin.com/company/aero-leads", "LinkedIn", "automation"),
    ]
    
    interleaved = interleave_urls_by_domain(candidates)
    
    # Check that they are interleaved across domains round-robin
    domains = [u[0].split("/")[2] for u in interleaved]
    
    # Expected order: goodfirms, clutch, linkedin, goodfirms, clutch
    assert domains[0] == "goodfirms.co"
    assert domains[1] == "clutch.co"
    assert domains[2] == "linkedin.com"
    assert domains[3] == "goodfirms.co"
    assert domains[4] == "clutch.co"


def test_mailto_and_structured_contact_extraction():
    from extraction.page_extractor import extract_emails, extract_structured_contact_info, find_footer_links
    
    html = """
    <html><body>
        <a href="mailto:info@empat.tech">Email Us</a>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Organization",
          "email": "hello@empat.tech",
          "telephone": "+1-111-222-3333"
        }
        </script>
        <footer id="colophon">
            <a href="/contact-us">Contact us</a>
        </footer>
    </body></html>
    """
    
    emails = extract_emails(html)
    assert "info@empat.tech" in emails
    
    struct_info = extract_structured_contact_info(html)
    assert "hello@empat.tech" in struct_info["emails"]
    assert "+1-111-222-3333" in struct_info["phones"]
    
    footer_links = find_footer_links(html, "https://empat.tech")
    assert "https://empat.tech/contact-us" in footer_links


def test_sparse_lead_rule_relaxation():
    from clean_leads import process_record
    
    # Empty name -> flagged
    rec1 = {"company_name": "", "emails": [], "phones": []}
    res1 = process_record(rec1, "test_file.json")
    assert "sparse_no_contact_channel" in res1["_flags"]
    
    # Valid name, no website/contact -> not flagged (relaxed rule allows it to enrichment)
    rec2 = {"company_name": "Valid Company", "emails": [], "phones": []}
    res2 = process_record(rec2, "test_file.json")
    assert "sparse_no_contact_channel" not in res2["_flags"]


def test_verify_domain_evidence_tiers():
    from main import verify_domain_evidence

    # Tier 1: Verified (Name match + social profile corroboration)
    company_v = {"company": "Pizza Hut", "website": "https://www.pizzahut.co.in"}
    extracted_v = {
        "social_links": {"facebook": "https://facebook.com/pizzahutindia"},
        "about_page": "https://www.pizzahut.co.in/about-us",
    }
    id_status, dom_status, evidence = verify_domain_evidence(company_v, extracted_v, keyword="Pizza Hut")
    assert id_status == "verified"
    assert dom_status == "verified"
    assert "domain_token_matches_name" in evidence
    assert "social_profile_matches_domain:facebook" in evidence

    # Tier 2: Identity Matched (Name match, but no external corroboration)
    company_im = {"company": "Stripe", "website": "https://stripe.com"}
    extracted_im = {"social_links": {}}
    id_status, dom_status, evidence = verify_domain_evidence(company_im, extracted_im, keyword="Stripe")
    assert id_status == "identity_matched"
    assert dom_status == "identity_matched"

    # Tier 3: Observed (Reachable domain from directory, but name does not match)
    company_obs = {"company": "Acme Catering", "website": "https://some-aggregator.com/profile"}
    extracted_obs = {"social_links": {}}
    id_status, dom_status, evidence = verify_domain_evidence(company_obs, extracted_obs, keyword="Acme")
    assert id_status == "observed"
    assert dom_status == "observed"

    # Tier 4: Not Found (No website)
    company_nf = {"company": "Ghost LLC", "website": None}
    extracted_nf = {}
    id_status, dom_status, evidence = verify_domain_evidence(company_nf, extracted_nf)
    assert id_status == "not_found"
    assert dom_status == "not_found"


def test_calibrated_confidence_scoring():
    from unittest.mock import patch, MagicMock
    from main import build_lead_card

    company = {
        "company": "Pizza Hut",
        "website": "https://www.pizzahut.co.in",
        "relevance_score": 100,  # Search snippet score is 100
        "relevance_tier": "HIGH",
        "source": "google",
    }
    mock_extracted = {
        "contact_page": "https://www.pizzahut.co.in/contact-us",
        "about_page": "https://www.pizzahut.co.in/about-us",
        "team_page": None,
        "emails": [],
        "emails_provenance": [],
        "phones": [],
        "phones_provenance": [],
        "social_links": {"facebook": "https://facebook.com/pizzahutindia"},
        "people": [],
        "company_type": "Retail/Restaurant",
        "industry_detected": "Food & Beverage",
        "meta_description": "Pizza Hut official site",
    }
    with patch("main.extract_from_website", return_value=mock_extracted), \
         patch("main.get_search_manager") as mock_sm:
        mock_sm.return_value.search.return_value = []
        mock_sm.return_value.providers_available.return_value = False
        card = build_lead_card(company, keyword="Pizza Hut")

    assert card is not None
    # Confidence score must NOT blindly be 100; it must reflect actual completeness
    assert card["confidence_score"] < 100
    assert card["confidence_score"] > 0
    assert card["data_quality"]["identity"] in ("verified", "identity_matched")
    assert card["data_quality"]["email"] == "not_found"
    assert card["emails"] == []  # Not hallucinated!


