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
