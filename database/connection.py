"""
database/connection.py
======================
Centralized SQLite connection management and schema initialization
for the canonical `flowiz_leads` storage.
"""

import os
import sqlite3
from typing import Optional

# Canonical database path resolved relative to repository root
DEFAULT_DB_FILE = "leads.db"
DB_SCHEMA_VERSION = "1.0.0"


def get_db_path(override_path: Optional[str] = None) -> str:
    """Resolve the canonical database path."""
    if override_path:
        return override_path
    env_path = os.getenv("FLOWIZ_DB_PATH")
    if env_path:
        return env_path
    return DEFAULT_DB_FILE


def get_default_db_path() -> str:
    """Convenience alias for get_db_path()."""
    return get_db_path()



def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Creates and returns a SQLite connection with Row factory enabled.
    Ensures connection isolation and deterministic timeout.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database(cursor: sqlite3.Cursor) -> None:
    """
    Initializes the canonical `flowiz_leads` table schema.
    Auto-migrates any missing columns safely without destroying existing rows.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS flowiz_leads (
            domain TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            website TEXT,
            industry TEXT,
            location TEXT,
            contact_page TEXT,
            about_page TEXT,
            emails TEXT,
            phones TEXT,
            social_links TEXT,
            people TEXT,
            tech_stack TEXT,
            lead_score INTEGER,
            description TEXT,
            employees TEXT,
            founded TEXT,
            country TEXT,
            domain_intel TEXT,
            org_graph TEXT,
            confidence_score REAL,
            lead_quality TEXT,
            keyword TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Auto-migrate any missing columns for backward compatibility
    cursor.execute("PRAGMA table_info(flowiz_leads)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    canonical_cols = [
        ("tech_stack", "TEXT"),
        ("lead_score", "INTEGER"),
        ("description", "TEXT"),
        ("employees", "TEXT"),
        ("founded", "TEXT"),
        ("country", "TEXT"),
        ("domain_intel", "TEXT"),
        ("org_graph", "TEXT"),
        ("confidence_score", "REAL"),
        ("lead_quality", "TEXT"),
        ("keyword", "TEXT"),
        ("created_at", "TIMESTAMP"),
    ]


    for col_name, col_type in canonical_cols:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE flowiz_leads ADD COLUMN {col_name} {col_type}")
