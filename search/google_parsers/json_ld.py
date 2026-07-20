"""
search/google_parsers/json_ld.py
=================================
JsonLdParser — Extracts results from JSON-LD ItemList schemas.

Google embeds structured data as JSON-LD scripts in some SERP variants.
This parser finds and decodes those schemas to extract organic URLs.
"""
from __future__ import annotations

import json
import time
from typing import List

from bs4 import BeautifulSoup

from search.google_parsers.base import BaseGoogleParser
from search.result import SearchResult


class JsonLdParser(BaseGoogleParser):
    """JSON-LD ItemList schema extractor."""

    name = "JsonLdParser"

    def parse(
        self,
        html: str,
        max_results: int,
        query: str,
        page: int,
    ) -> List[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: List[SearchResult] = []
        ts = time.time()
        rank = 0

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = []
                if isinstance(data, dict) and data.get("@type") == "ItemList":
                    items = data.get("itemListElement", [])
                elif isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict) and entry.get("@type") == "ItemList":
                            items.extend(entry.get("itemListElement", []))

                for item in items:
                    url = item.get("url")
                    title = item.get("name")
                    if url and title:
                        rank += 1
                        results.append(SearchResult(
                            url=url, title=title, snippet=None,
                            provider="google_html", source="Google",
                            provider_rank=rank, query=query, page=page, timestamp=ts,
                        ))
                        if len(results) >= max_results:
                            return results
            except Exception:
                continue

        return results
