import pytest
from extraction.tech_detector import detect_tech_stack
from utils.validators import score_email, rank_emails
from utils.lead_scorer import compute_lead_score
from utils.domain_intel import get_domain_intel
from utils.org_graph import build_org_graph

def test_tech_detector():
    html = "<script src='/react.js'></script><link href='/tailwind.css'>"
    techs = detect_tech_stack(html, {})
    assert "React" in techs
    assert "Tailwind CSS" in techs

def test_score_email():
    res = score_email("ceo@anthropic.com", "anthropic.com")
    assert res["confidence"] > 50
    assert "domain_match" in res["reasons"]

def test_lead_scorer():
    lead = {
        "emails": ["contact@acme.com"],
        "phones": ["+1 555 0199"],
        "social_links": {"linkedin": "http://linkedin.com/company/acme"},
        "tech_stack": ["React", "Cloudflare"],
        "industry_detected": "AI",
        "source": "google"
    }
    score = compute_lead_score(lead)
    assert score >= 40

def test_org_graph():
    lead = {
        "company_name": "Acme Inc",
        "emails": ["sales@acme.com"],
        "tech_stack": ["Next.js"]
    }
    graph = build_org_graph(lead)
    assert graph["company"] == "Acme Inc"
    assert graph["node_count"] == 2
