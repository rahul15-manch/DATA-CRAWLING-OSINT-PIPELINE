from typing import Dict, Any, List, Optional
from .etl import LeadSchema

class LeadBuilder:
    """
    Item Loader that accumulates and pre-normalizes lead fields
    before validating them against LeadSchema.
    """
    def __init__(self, item: Optional[Dict[str, Any]] = None):
        self._fields: Dict[str, Any] = item or {}

    def add_value(self, field_name: str, value: Any) -> None:
        """Add a value to the field, merging lists and dicts appropriately."""
        if value is None:
            return

        if field_name in ("emails", "phones"):
            if not isinstance(value, list):
                value = [value]
            self._fields[field_name] = list(set(self._fields.get(field_name, []) + value))
        elif field_name == "social_links":
            if isinstance(value, dict):
                self._fields.setdefault("social_links", {}).update(value)
        elif field_name == "people":
            if not isinstance(value, list):
                value = [value]
            self._fields.setdefault("people", []).extend(value)
        else:
            self._fields[field_name] = value

    def load_item(self) -> Dict[str, Any]:
        """Validates fields using LeadSchema and returns a clean, dumpable dict."""
        lead = LeadSchema(**self._fields)
        return lead.model_dump(exclude_none=True)
