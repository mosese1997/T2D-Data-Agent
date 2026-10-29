"""SQL validation with sqlglot (postgres dialect — DWS/GaussDB is PG-family).

Checks (task book §10):
- exactly one statement, and it is a SELECT (WITH ... SELECT allowed);
- every referenced table/view is inside the caller's authorized dataset
  whitelist (the DB-level read-only role is the final constraint);
- system catalogs (pg_catalog / information_schema / pg_*) rejected;
- dangerous functions rejected (blacklist below);
- an outer LIMIT is enforced by the gateway, not trusted from the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

FORBIDDEN_FUNCTIONS = {
    "pg_sleep", "pg_sleep_for", "pg_terminate_backend", "pg_cancel_backend",
    "dblink", "dblink_exec", "pg_read_file", "pg_read_binary_file",
    "lo_import", "lo_export", "lo_get", "set_config", "copy",
    "pg_ls_dir", "pg_stat_file", "current_setting",
}

FORBIDDEN_SCHEMAS = {"pg_catalog", "information_schema"}

# Statements that must never appear, even inside CTEs.
_MUTATING_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop,
    exp.Alter, exp.TruncateTable, exp.Grant, exp.Command, exp.Copy,
    exp.Transaction, exp.Commit, exp.Rollback,
)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized_sql: str = ""
    objects_referenced: list[str] = field(default_factory=list)


def validate_sql(sql: str, *, allowed_objects: set[str]) -> ValidationResult:
    """Validate one SQL string. allowed_objects: lowercase table/view names
    (schema-qualified names are matched on their full dotted form)."""
    errors: list[dict[str, str]] = []
    warnings: list[str] = []

    if not sql or not sql.strip():
        return ValidationResult(False, errors=[{
            "code": "empty_sql", "message": "SQL 为空",
        }])

    try:
        expressions = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.ParseError as exc:
        return ValidationResult(False, errors=[{
            "code": "parse_error",
            "message": f"SQL 解析失败: {_first_line(str(exc))}",
        }])

    statements = [e for e in expressions if e is not None]
    if len(statements) != 1:
        return ValidationResult(False, errors=[{
            "code": "multi_statement",
            "message": f"必须恰好一条语句，实际 {len(statements)} 条",
        }])

    tree = statements[0]

    # WITH ... SELECT is a Select at the root; anything else is rejected.
    if not isinstance(tree, exp.Select):
        return ValidationResult(False, errors=[{
            "code": "not_select",
            "message": f"只允许 SELECT 查询，实际为 {tree.key}",
        }])

    # No mutating nodes anywhere (covers sneak paths inside CTEs).
    for node in tree.walk():
        node = node[0] if isinstance(node, tuple) else node
        if isinstance(node, _MUTATING_TYPES):
            return ValidationResult(False, errors=[{
                "code": "mutating_statement",
                "message": f"检测到禁止的语句类型: {node.key}",
            }])

    # Referenced objects. CTE names defined in the WITH clause are not
    # warehouse objects — exclude them from the whitelist check.
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    referenced: list[str] = []
    for table in tree.find_all(exp.Table):
        catalog = table.catalog or ""
        schema = (table.db or "").lower()
        name = (table.name or "").lower()
        if name in cte_names:
            continue
        if catalog:
            errors.append({
                "code": "catalog_reference",
                "message": f"禁止跨库引用: {catalog}",
            })
            continue
        if schema in FORBIDDEN_SCHEMAS or name.startswith("pg_"):
            errors.append({
                "code": "system_object",
                "message": f"禁止访问系统对象: {schema}.{name}" if schema else name,
            })
            continue
        full = f"{schema}.{name}" if schema else name
        if full not in referenced:
            referenced.append(full)
        if full not in allowed_objects and name not in allowed_objects:
            errors.append({
                "code": "object_not_authorized",
                "message": f"对象不在授权范围内: {full}",
            })

    # Function blacklist. Unknown functions parse as exp.Anonymous whose
    # sql_name() is the class name — read the real name from `this`.
    for func in tree.find_all(exp.Func):
        if isinstance(func, exp.Anonymous):
            func_name = str(func.this).lower() if func.this else ""
        else:
            func_name = (func.sql_name() or "").lower()
        if func_name in FORBIDDEN_FUNCTIONS:
            errors.append({
                "code": "forbidden_function",
                "message": f"禁止使用函数: {func_name}",
            })

    # Outer LIMIT is required by the gateway; warn when the model already
    # added one so the gateway can clamp instead of trusting it.
    limit = tree.args.get("limit")
    if limit is None:
        warnings.append("缺少外层 LIMIT，将由网关强制追加")

    normalized = tree.sql(dialect="postgres", pretty=False)
    return ValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        normalized_sql=normalized,
        objects_referenced=referenced,
    )


def _first_line(text: str) -> str:
    return text.splitlines()[0][:200] if text else ""
