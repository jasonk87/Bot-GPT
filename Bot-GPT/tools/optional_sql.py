"""Optional SQL tool wrappers.

Keeps SQLAlchemy imports out of module import paths unless used.
"""

try:
    from .database import get_db_schema as _get_db_schema
    from .sql_query import run_sql_query as _run_sql_query
    SQL_AVAILABLE = True
except Exception:
    _get_db_schema = None
    _run_sql_query = None
    SQL_AVAILABLE = False


def get_db_schema(*args, **kwargs):
    if not SQL_AVAILABLE or _get_db_schema is None:
        return "Error: optional SQL tools require SQLAlchemy dependencies."
    return _get_db_schema(*args, **kwargs)


def run_sql_query(*args, **kwargs):
    if not SQL_AVAILABLE or _run_sql_query is None:
        return "Error: optional SQL tools require SQLAlchemy dependencies."
    return _run_sql_query(*args, **kwargs)
