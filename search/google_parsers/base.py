"""
search/google_parsers/base.py
==============================
Base interface for all Google SERP parsers.

Adding a new parser:
1. Create search/google_parsers/my_parser.py  subclassing BaseGoogleParser
2. Register it in google_parser_registry.PARSER_REGISTRY
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List
from search.result import SearchResult


class BaseGoogleParser(ABC):
    """Abstract base class every Google parser must implement."""

    name: str = "base"

    @abstractmethod
    def parse(
        self,
        html: str,
        max_results: int,
        query: str,
        page: int,
    ) -> List[SearchResult]:
        """
        Parse raw Google HTML and return a list of SearchResult objects.

        Returns an empty list if no results could be extracted.
        Never raises — callers treat an empty list as a failure.
        """
        ...
