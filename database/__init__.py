"""Database package for authoritative storage and data access."""
from .connection import get_db_connection, setup_database, get_default_db_path, DB_SCHEMA_VERSION
from .repository import LeadRepository

__all__ = [
    "get_db_connection",
    "setup_database",
    "get_default_db_path",
    "DB_SCHEMA_VERSION",
    "LeadRepository",
]
