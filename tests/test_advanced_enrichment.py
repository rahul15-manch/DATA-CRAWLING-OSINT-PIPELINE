import pytest
from extraction.tech_detector import detect_tech_stack
from utils.validators import score_email, rank_emails, is_valid_email_candidate
from extraction.page_extractor import extract_emails
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


def test_is_valid_email_candidate():
    # Valid emails
    assert is_valid_email_candidate("support@swiggy.in") is True
    assert is_valid_email_candidate("careers@pizzahut.com") is True
    assert is_valid_email_candidate("contact@acme-corp.com") is True

    # Reject if domain starts with digit (e.g. JS packages or retina assets)
    assert is_valid_email_candidate("react-dom-client@19.1.0.mjs") is False
    assert is_valid_email_candidate("avatar@2x.png") is False

    # Reject code/media extensions as TLD
    assert is_valid_email_candidate("style@domain.css") is False
    assert is_valid_email_candidate("script@domain.js") is False
    assert is_valid_email_candidate("bundle@domain.map") is False
    assert is_valid_email_candidate("logo@domain.svg") is False

    # Reject dummy/placeholder emails
    assert is_valid_email_candidate("username@company.com") is False
    assert is_valid_email_candidate("name@company.com") is False
    assert is_valid_email_candidate("user@example.com") is False
    assert is_valid_email_candidate("email@example.com") is False
    assert is_valid_email_candidate("yourname@email.com") is False
    assert is_valid_email_candidate("sample@somewhere.com") is False

    # Reject system / automated ignore patterns
    assert is_valid_email_candidate("noreply@company.com") is False
    assert is_valid_email_candidate("bounce@company.com") is False
    assert is_valid_email_candidate("unsubscribe@company.com") is False


def test_extract_emails_filtered():
    raw_html = """
    <html>
      <head>
        <script src="react-dom-client@19.1.0.mjs"></script>
        <link rel="stylesheet" href="main@1.2.css">
      </head>
      <body>
        <img src="avatar@2x.png" alt="User">
        <p>Please contact our support team at <a href="mailto:support@swiggy.in">support@swiggy.in</a></p>
        <p>Careers inquiry: careers@swiggy.in</p>
        <p>Template sample: username@company.com and user@example.com</p>
        <p>Notifications sent by noreply@swiggy.in</p>
      </body>
    </html>
    """
    emails = extract_emails(raw_html)
    assert "support@swiggy.in" in emails
    assert "careers@swiggy.in" in emails
    assert "react-dom-client@19.1.0.mjs" not in emails
    assert "avatar@2x.png" not in emails
    assert "username@company.com" not in emails
    assert "user@example.com" not in emails
    assert "noreply@swiggy.in" not in emails

