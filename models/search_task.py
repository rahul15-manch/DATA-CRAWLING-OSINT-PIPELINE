from dataclasses import dataclass

@dataclass
class SearchTask:
    source: str
    query: str
    priority: int
    category: str