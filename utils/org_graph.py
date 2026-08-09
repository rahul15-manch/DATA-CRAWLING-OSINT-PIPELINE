from __future__ import annotations
from typing import Any

def build_org_graph(lead: dict[str, Any]) -> dict[str, Any]:
    if not lead:
        return {}
    company_name = lead.get("company_name") or lead.get("name") or "Unknown"
    website = lead.get("website") or ""
    nodes = []
    for email in lead.get("emails", []):
        nodes.append({"type": "email", "value": email})
    for phone in lead.get("phones", []):
        nodes.append({"type": "phone", "value": phone})
    socials = lead.get("social_links") or {}
    for platform, url in socials.items():
        nodes.append({"type": "social", "platform": platform, "url": url})
    for person in lead.get("people", []):
        if isinstance(person, dict):
            nodes.append({"type": "person", "name": person.get("name"), "designation": person.get("designation")})
    for tech in lead.get("tech_stack", []):
        nodes.append({"type": "technology", "value": tech})
    return {"company": company_name, "website": website, "node_count": len(nodes), "nodes": nodes}
