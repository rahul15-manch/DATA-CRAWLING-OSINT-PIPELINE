import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from search.google_response_classifier import classify_google_response

def run_regression():
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_pages")
    
    test_cases = {
        "desktop_serp.html": "NORMAL_DESKTOP_SERP",
        "mobile_serp.html": "NORMAL_MOBILE_SERP",
        "ai_overview.html": "AI_OVERVIEW_PAGE",
        "knowledge_panel.html": "KNOWLEDGE_PANEL_PAGE",
        "people_also_ask.html": "PEOPLE_ALSO_ASK_PAGE",
        "captcha.html": "CAPTCHA_PAGE",
        "enablejs.html": "ENABLE_JS_PAGE",
        "consent.html": "CONSENT_PAGE",
        "zero_results.html": "ZERO_RESULTS_PAGE",
        "localized.html": "LOCALIZED_SERP",
        "unknown_layout.html": "UNKNOWN_LAYOUT"
    }

    print("==================================================")
    print("RUNNING GOOGLE HTML CLASSIFIER REGRESSION TESTS")
    print("==================================================")
    
    all_passed = True
    
    for filename, expected_type in test_cases.items():
        path = os.path.join(base_dir, filename)
        if not os.path.exists(path):
            print(f"[FAIL] Missing test file: {filename}")
            all_passed = False
            continue
            
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
            
        # Call classifier
        # For localized mock we mock the url redirect to hit co.in
        url = "https://www.google.co.in/search" if filename == "localized.html" else "https://www.google.com/search"
        res = classify_google_response(html, 200, url)
        
        actual_type = res["page_type"]
        if actual_type == expected_type:
            print(f"[PASS] {filename:<22} -> {actual_type}")
        else:
            print(f"[FAIL] {filename:<22} -> Expected: {expected_type}, Got: {actual_type} (Signals: {res['detected_signals']})")
            all_passed = False
            
    print("==================================================")
    if all_passed:
        print("RESULT: ALL REGRESSION TESTS PASSED!")
        sys.exit(0)
    else:
        print("RESULT: SOME TESTS FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    run_regression()
