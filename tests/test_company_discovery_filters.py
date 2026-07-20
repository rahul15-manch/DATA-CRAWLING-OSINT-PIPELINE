from discovery.company_discovery import classify_company_page, classify_result, should_ignore_result, validate_company_record


def test_validate_company_record_allows_real_company_website():
    company = {
        "company": "Vinove IT Software & Services",
        "website": "https://vinove.com",
        "linkedin": None,
        "source": "Google",
    }

    is_valid, reason = validate_company_record(company)

    assert is_valid is True
    assert reason is None


def test_validate_company_record_allows_directory_company_profile():
    company = {
        "company": "SLN Softwares",
        "website": "https://www.clutch.co/profile/sln-softwares",
        "linkedin": None,
        "source": "Clutch",
    }

    is_valid, reason = validate_company_record(company)

    assert is_valid is True
    assert reason is None


def test_validate_company_record_allows_source_url_without_website():
    company = {
        "company": "Newgen Software Technologies",
        "website": None,
        "source_url": "https://www.goodfirms.co/company/newgen-software-technologies",
        "linkedin": None,
        "source": "GoodFirms",
    }

    is_valid, reason = validate_company_record(company)

    assert is_valid is True
    assert reason is None


def test_classify_result_separates_profile_and_listing_pages():
    profile_result = {
        "title": "Vinove IT Software & Services | Clutch",
        "url": "https://www.clutch.co/profile/vinove-it-software-services",
    }
    listing_result = {
        "title": "Top Software Companies in Noida | Clutch",
        "url": "https://www.clutch.co/search?q=software+companies+noida",
    }

    profile_classification, _ = classify_result(profile_result)
    listing_classification, _ = classify_result(listing_result)

    assert profile_classification == "ALLOW"
    assert listing_classification == "REJECT"
    assert should_ignore_result(listing_result) is True
    assert should_ignore_result(profile_result) is False


def test_classify_company_page_labels_directory_profiles():
    assert classify_company_page("https://www.clutch.co/profile/vinove") == "DIRECTORY_COMPANY"
    assert classify_company_page("https://www.clutch.co/search?q=python") == "DIRECTORY_LIST"
    assert classify_company_page("https://vinove.com") == "DIRECT_COMPANY"