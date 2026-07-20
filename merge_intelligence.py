import json

# Files load karein
with open("enriched_leads.json", "r", encoding="utf-8") as f:
    enriched = json.load(f)

with open("registry_matched_leads.json", "r", encoding="utf-8") as f:
    registry = json.load(f)

# Registry data ko map karein company_name ke basis par
registry_map = {item['company_name']: item.get('_registry') for item in registry}

# Merge karein
for record in enriched:
    name = record.get("company_name")
    record["_registry"] = registry_map.get(name, {"matched": False, "reason": "not_processed"})

# Final output save karein
with open("final_b2b_profile.json", "w", encoding="utf-8") as f:
    json.dump(enriched, f, indent=2, ensure_ascii=False)

print("Pipeline Complete! Final profile saved in final_b2b_profile.json")