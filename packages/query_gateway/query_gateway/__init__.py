"""query_gateway — the only path from agent SQL to the business warehouse."""

from .validator import validate_sql, ValidationResult
from .limits import QueryLimits
from .gateway import QueryGateway, QueryResult

__all__ = [
    "validate_sql", "ValidationResult",
    "QueryLimits",
    "QueryGateway", "QueryResult",
]
