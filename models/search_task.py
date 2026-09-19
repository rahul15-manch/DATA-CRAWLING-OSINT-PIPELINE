from dataclasses import dataclass, field

@dataclass
class SearchTask:
    source: str
    query: str
    priority: int
    category: str
    discovery_mode: str = "expanded"   # "direct" | "expanded"
    original_keyword: str = ""         # the raw user query (preserved for provenance)