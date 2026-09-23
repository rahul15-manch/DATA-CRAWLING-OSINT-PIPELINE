from dataclasses import dataclass, field

@dataclass
class SearchTask:
    source: str
    query: str
    priority: int
    category: str
    discovery_mode: str = "expanded"   # "direct" | "expanded"
    original_keyword: str = ""         # the raw user query (preserved for provenance)
    family: str = "COMPANY"            # COMPANY | CONTACT | ABOUT_TEAM | CAREERS | DOCUMENT | REGISTRY | SOCIAL
    operator_set: list[str] = field(default_factory=list)  # e.g. ["inurl:", "site:"]
    intent: str = "discovery"          # discovery | contact | leadership | document | careers
    expected_information: str = ""     # description of expected signal