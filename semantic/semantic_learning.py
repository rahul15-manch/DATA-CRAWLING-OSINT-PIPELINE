"""
semantic/semantic_learning.py
==============================
Manages B2B ontology feedback learning loops. Logs dynamic concepts, 
calculates acceptance confidence, and updates learned_semantics.json once at end-of-run.
"""

import os
import json
import time

_learned_feedback = []

def record_learning_feedback(keyword: str, matched_techs: list[str], matched_prods: list[str], was_successful: bool):
    """Queue learning feedback logs during ThreadPool worker processes."""
    _learned_feedback.append((keyword, matched_techs, matched_prods, was_successful))

def apply_ontology_learning():
    """Apply batched ontology learning and save to disk exactly once."""
    if not _learned_feedback:
        return

    path = "data/learned_semantics.json"
    learned = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                learned = json.load(f)
        except Exception:
            learned = {}

    now_str = time.strftime("%Y-%m-%d")

    for kw, techs, prods, success in _learned_feedback:
        kw_key = kw.lower().strip()
        if not kw_key:
            continue
        if kw_key not in learned:
            learned[kw_key] = {}

        # Log matched technologies as concepts candidates
        for t in techs:
            if not t:
                continue
            if t not in learned[kw_key]:
                learned[kw_key][t] = {
                    "seen": 0,
                    "accepted": 0,
                    "confidence": 0.0,
                    "first_seen": now_str,
                    "last_seen": now_str,
                    "target_field": "concepts"
                }
            learned[kw_key][t]["seen"] += 1
            learned[kw_key][t]["last_seen"] = now_str
            if success:
                learned[kw_key][t]["accepted"] += 1

        # Log matched products
        for p in prods:
            if not p:
                continue
            if p not in learned[kw_key]:
                learned[kw_key][p] = {
                    "seen": 0,
                    "accepted": 0,
                    "confidence": 0.0,
                    "first_seen": now_str,
                    "last_seen": now_str,
                    "target_field": "products"
                }
            learned[kw_key][p]["seen"] += 1
            learned[kw_key][p]["last_seen"] = now_str
            if success:
                learned[kw_key][p]["accepted"] += 1

    # Recalculate confidence scores for all entries
    for kw_key, terms in learned.items():
        for t, stats in terms.items():
            seen = stats.get("seen", 0)
            accepted = stats.get("accepted", 0)
            if seen > 0:
                stats["confidence"] = round(accepted / seen, 2)

    os.makedirs("data", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(learned, f, indent=2, ensure_ascii=False)
        print("[SemanticLearning] Successfully updated learned ontology candidates.")
    except Exception as e:
        print(f"[SemanticLearning] Error saving dynamic ontology: {e}")

    _learned_feedback.clear()
