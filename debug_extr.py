import sys, sqlite3, glob, json, os
# Add both root and pillar1 subdirectory to path (same as main.py)
ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "pillar1"))

from extraction.page_extractor import extract_from_website

# -- Find a real website from leads.db --------------------------------------
website = None
for db_path in glob.glob("**/*.db", recursive=True):
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        for table in ("leads","companies","final_leads","raw_leads"):
            try:
                rows = conn.execute(
                    f"SELECT * FROM [{table}] WHERE website IS NOT NULL AND website != '' LIMIT 1"
                ).fetchall()
                if rows:
                    d = dict(rows[0])
                    website = d.get("website")
                    name = d.get("company_name") or d.get("company") or "?"
                    print(f"[DB] {db_path} / {table}: {name!r} -> {website!r}")
                    break
            except: continue
        conn.close()
        if website: break
    except Exception as e: print("ERR", db_path, e)

if not website:
    website = "https://anthropic.com"
    print(f"[fallback] {website}")

print(f"\nRunning extract_from_website({website!r}) ...\n")
extracted = extract_from_website(website)

SEP = "=" * 60
print(SEP)
print("TECH STACK  :", extracted.get("tech_stack"))
print("PEOPLE      :", json.dumps(extracted.get("people"), ensure_ascii=False))
print("DESCRIPTION :", repr((extracted.get("description") or "")[:200]))
print("EMPLOYEES   :", repr(extracted.get("employees")))
print("FOUNDED     :", repr(extracted.get("founded")))
print("COUNTRY     :", repr(extracted.get("country")))
print("LOCATION    :", repr(extracted.get("location")))
print("SOCIAL LINKS:", extracted.get("social_links"))
print("EMAILS      :", extracted.get("emails"))
print("PHONES      :", extracted.get("phones"))
print(SEP)

populated = [k for k in ("tech_stack","people","description","employees","founded","country") if extracted.get(k)]
empty     = [k for k in ("tech_stack","people","description","employees","founded","country") if not extracted.get(k)]
print("POPULATED:", populated)
print("EMPTY    :", empty)
if populated:
    print("\n[VERDICT] Extraction IS working. If DB is empty -> card/ETL mapping is the problem.")
else:
    print("\n[VERDICT] Extraction returned ALL EMPTY -> fix page_extractor.py / tech_detector.py.")
