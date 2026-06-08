"""数据库查询工具 — SQLite。

提供三个工具：
- list_tables: 列出所有可用表
- describe_table: 获取表结构
- query_database: 执行 SQL 查询（仅 SELECT）

默认使用项目内置的示例数据库 (data/sakila.db)。
环境变量：
    AGENT_BENCH_DB_PATH: 自定义数据库路径。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 危险 SQL 关键词（禁止执行）
_FORBIDDEN_KEYWORDS = {"DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH", "DETACH"}


def _get_db_path() -> str:
    """获取数据库路径。"""
    env_path = os.environ.get("AGENT_BENCH_DB_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    # 默认使用项目内置示例数据库
    default_path = Path(__file__).parent.parent.parent.parent.parent / "data" / "sakila.db"
    if default_path.exists():
        return str(default_path)
    # 如果没有示例数据库，使用内存数据库
    return ":memory:"


def _validate_sql(sql: str) -> None:
    """校验 SQL 安全性，仅允许 SELECT 语句。"""
    upper = sql.strip().upper()
    if not upper.startswith("SELECT"):
        raise ValueError(f"仅允许 SELECT 查询，当前语句以 {upper.split()[0] if upper.split() else '空'} 开头")
    for keyword in _FORBIDDEN_KEYWORDS:
        if keyword in upper.split():
            raise ValueError(f"SQL 中包含禁止的关键词: {keyword}")


async def list_tables_impl() -> dict[str, Any]:
    """列出数据库中所有可用的表。"""
    db_path = _get_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return {"tables": tables, "total": len(tables), "database": db_path}
    except Exception as e:
        return {"error": str(e), "tables": [], "total": 0}


async def describe_table_impl(table_name: str) -> dict[str, Any]:
    """获取指定表的结构信息。

    Args:
        table_name: 表名。

    Returns:
        表结构信息字典。
    """
    db_path = _get_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 获取列信息
        cursor.execute(f"PRAGMA table_info([{table_name}])")
        columns = [
            {
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "default": row[4],
                "pk": bool(row[5]),
            }
            for row in cursor.fetchall()
        ]

        # 获取行数
        cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
        row_count = cursor.fetchone()[0]

        conn.close()
        return {
            "table_name": table_name,
            "columns": columns,
            "row_count": row_count,
        }
    except Exception as e:
        return {"error": str(e), "table_name": table_name}


async def query_database_impl(sql: str) -> dict[str, Any]:
    """执行 SQL 查询。

    Args:
        sql: SQL 查询语句（仅 SELECT）。

    Returns:
        查询结果字典。
    """
    db_path = _get_db_path()
    try:
        _validate_sql(sql)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()

        # 限制返回行数
        max_rows = 100
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "sql": sql,
        }
    except ValueError as e:
        return {"error": str(e), "sql": sql, "rows": [], "row_count": 0}
    except Exception as e:
        return {"error": f"SQL 执行失败: {e}", "sql": sql, "rows": [], "row_count": 0}
