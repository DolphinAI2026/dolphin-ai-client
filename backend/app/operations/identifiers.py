"""编码/字段标识符工具——generator_v2 与 step_executor / incremental_executor
三条路径共享。

内容：
  _RESERVED           SQL 关键字 + 平台短名集合（用于编码冲突兜底）
  _rand(n)            随机后缀（受 settings.enable_code_suffix 控制）
  _apply_suffix       为编码追加 _suffix（suffix 为空则原样返回）
  _sanitize_code      确保 code 纯 ASCII、字母开头
  _safe_field_code    优先保留原始字段编码，缺失时兜底生成
  _extract_fields     从平台返回的模型中提取 {fieldName: fieldCode}

从 app/generator_v2.py 原样搬入；保持函数签名与行为完全一致。
generator_v2.py 改为从这里 re-export 以保证 `from app.generator_v2 import
_rand, _extract_fields` 这种历史引用依然可用。
"""
from __future__ import annotations

import hashlib
import random
import re
import string
from typing import Dict

from app.config import settings


def _rand(n: int = 4) -> str:
    """根据配置决定是否生成随机后缀"""
    if settings.enable_code_suffix:
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
    return ""


def _apply_suffix(code: str, suffix: str) -> str:
    """为编码添加后缀（如果有）"""
    if suffix:
        return f"{code}_{suffix}"
    return code


def _sanitize_code(code: str) -> str:
    """确保 code 纯 ASCII、字母开头、无保留字冲突"""
    if not code:
        return f"c{_rand(6)}"
    c = re.sub(r"[^a-zA-Z0-9_]", "", code)
    if len(c) < 2:
        c = "c" + hashlib.md5(code.encode()).hexdigest()[:7]
    if c[0].isdigit():
        c = "f_" + c
    c = c.lower()
    # 2026-05-30: apaas 禁止字段/模型 code 以 apaas、xdap 开头 (bizCode 12017
    # "不能以apaas，xdap开头"). 如映射类模型的 apaas_target_model 字段 → 整模型建失败.
    # 加 f_ 前缀绕开, 让这类 code 也能正常落库 (横跨字段/模型/字典/选项所有标识符).
    if c.startswith(("apaas", "xdap")):
        c = "f_" + c
    return c


_RESERVED = {
    # SQL 关键字（MySQL + PostgreSQL + 通用 SQL）
    "add", "all", "alter", "and", "any", "as", "asc", "between", "by",
    "call", "case", "check", "column", "constraint", "create", "cross",
    "current", "database", "default", "delete", "desc", "describe",
    "distinct", "drop", "each", "else", "end", "escape", "exists",
    "explain", "false", "for", "foreign", "from", "full", "function",
    "grant", "group", "having", "if", "in", "index", "inner", "insert",
    "into", "is", "join", "key", "left", "like", "limit", "lock",
    "not", "null", "offset", "on", "or", "order", "outer", "primary",
    "procedure", "references", "replace", "return", "revoke", "right",
    "rollback", "row", "rows", "schema", "select", "set", "show",
    "table", "then", "to", "trigger", "true", "union", "unique",
    "unlock", "update", "use", "using", "values", "view", "when",
    "where", "with",
    # SQL 函数 / 聚合
    "avg", "count", "max", "min", "sum", "rank", "abs", "cast",
    "coalesce", "convert", "extract", "length", "lower", "upper",
    "trim", "substring", "position",
    # MySQL 特有保留字
    "accessible", "analyze", "asensitive", "before", "bigint", "binary",
    "blob", "both", "cascade", "change", "char", "character", "collate",
    "condition", "continue", "databases", "day_hour", "day_microsecond",
    "day_minute", "day_second", "dec", "decimal", "declare", "delayed",
    "deterministic", "div", "double", "dual", "elseif", "enclosed",
    "escaped", "exit", "fetch", "float", "float4", "float8", "force",
    "fulltext", "generated", "get", "grouping", "groups", "high_priority",
    "hour_microsecond", "hour_minute", "hour_second", "ignore", "infile",
    "int", "int1", "int2", "int3", "int4", "int8", "integer", "interval",
    "iterate", "keys", "kill", "leading", "leave", "linear", "lines",
    "load", "localtime", "localtimestamp", "long", "longblob", "longtext",
    "loop", "low_priority", "master_bind", "master_ssl_verify_server_cert",
    "match", "maxvalue", "mediumblob", "mediumint", "mediumtext",
    "middleint", "minute_microsecond", "minute_second", "mod", "modifies",
    "natural", "no_write_to_binlog", "numeric", "optimize", "optimizer_costs",
    "option", "optionally", "out", "outfile", "partition", "precision",
    "purge", "range", "read", "reads", "real", "recursive", "regexp",
    "release", "rename", "repeat", "require", "resignal", "restrict",
    "rlike", "second_microsecond", "sensitive", "separator", "signal",
    "smallint", "spatial", "specific", "sql", "sqlexception", "sqlstate",
    "sqlwarning", "ssl", "straight_join", "stored", "system",
    "terminated", "text", "tinyblob", "tinyint", "tinytext", "trailing",
    "undo", "unsigned", "usage", "utc_date", "utc_time", "utc_timestamp",
    "varbinary", "varchar", "varcharacter", "varying", "virtual",
    "while", "window", "write", "xor", "year_month", "zerofill",
    # 常见短名 / 业务名（平台可能保留）
    "id", "no", "name", "type", "status", "state", "value", "data",
    "code", "date", "time", "timestamp", "number", "level", "action",
    "result", "role", "user", "label", "field", "fields", "file",
    "size", "start", "stop", "open", "close", "source", "scope",
    "method", "language", "comment", "location", "email", "phone",
    "address", "account", "model", "unit", "category", "manager",
    "priority", "amount", "currency", "operator", "spec", "begin",
    "commit", "password", "subject", "title", "description", "content",
    "note", "notes", "remark", "remarks", "company", "customer",
    "contact", "product", "service", "price", "total", "quantity",
    "region", "area", "domain", "mode", "version", "class", "object",
    "event", "process", "rule", "policy", "plan", "task", "job",
    "session", "token", "hash", "link", "path", "url", "list",
    "map", "array", "queue", "stack", "tree", "node", "page",
    "form", "menu", "input", "output", "error", "log", "audit",
    "archive", "backup", "cache", "temp", "test", "debug", "admin",
    "root", "owner", "parent", "child", "master", "slave", "host",
    "port", "server", "client", "local", "global", "public", "private",
    "static", "dynamic", "abstract", "virtual", "super", "self", "this",
    "new", "old",
}


def _safe_field_code(code: str) -> str:
    """确保字段编码不与数据库关键字冲突。

    策略：保留合规编码；遇到数据库/平台保留短名时自动加业务字段后缀。
    """
    raw = str(code or "").strip()
    c = _sanitize_code(raw or code)
    if c in _RESERVED:
        c = f"{c}_field"
    if c in _RESERVED:
        c = f"f_{c}"
    return c


def _extract_fields(platform_model: dict) -> Dict[str, str]:
    """从平台返回的模型数据中提取 {fieldName: fieldCode}"""
    return {
        f.get("fieldName"): f.get("fieldCode")
        for f in platform_model.get("fields", [])
        if f.get("fieldName") and f.get("fieldCode")
    }


__all__ = [
    "_RESERVED",
    "_rand",
    "_apply_suffix",
    "_sanitize_code",
    "_safe_field_code",
    "_extract_fields",
]
