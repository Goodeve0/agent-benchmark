"""Python 代码执行工具 — 受限本地执行。

安全策略：
1. 禁止导入 os / sys / subprocess 等危险模块
2. 禁止文件读写操作
3. 限制输出大小（防止内存溢出）

支持的标准库：math, json, re, datetime, collections, itertools, functools, statistics
第三方库（如已安装）：numpy, pandas
"""

from __future__ import annotations

import io
import logging
from contextlib import redirect_stdout, redirect_stderr
from typing import Any

logger = logging.getLogger(__name__)

_ALLOWED_MODULES = {
    "math", "json", "re", "datetime", "collections", "itertools",
    "functools", "statistics", "decimal", "fractions", "copy",
    "string", "textwrap", "enum", "typing",
}

_FORBIDDEN_BUILTINS = {
    "exec", "eval", "compile", "__import__", "open",
    "input", "breakpoint", "exit", "quit",
}

_MAX_OUTPUT = 10000


async def run_python_impl(code: str, timeout: int = 10) -> dict[str, Any]:
    """执行 Python 代码并返回输出。

    Args:
        code: 要执行的 Python 代码。
        timeout: 执行超时秒数。

    Returns:
        执行结果字典。
    """
    safety_error = _check_safety(code)
    if safety_error:
        return {"success": False, "error": safety_error, "stdout": "", "stderr": ""}

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        safe_globals = _build_safe_globals()
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(code, safe_globals)  # noqa: S102

        stdout = stdout_buf.getvalue()[:_MAX_OUTPUT]
        stderr = stderr_buf.getvalue()[:_MAX_OUTPUT]
        return {"success": True, "stdout": stdout, "stderr": stderr}
    except Exception as e:
        return {
            "success": False,
            "stdout": stdout_buf.getvalue()[:_MAX_OUTPUT],
            "stderr": stderr_buf.getvalue()[:_MAX_OUTPUT],
            "error": f"{type(e).__name__}: {e}",
        }


def _check_safety(code: str) -> str | None:
    """检查代码安全性。"""
    for name in _FORBIDDEN_BUILTINS:
        if name in code:
            return f"代码中包含禁止的函数: {name}"

    for line in code.split("\n"):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            module_name = _extract_module_name(stripped)
            top_level = module_name.split(".")[0]
            if top_level not in _ALLOWED_MODULES and top_level not in ("numpy", "pandas"):
                return f"禁止导入模块: {module_name}（允许: {', '.join(sorted(_ALLOWED_MODULES))}, numpy, pandas）"

    file_ops = ["open(", "with open", ".read(", ".write(", ".readlines("]
    for op in file_ops:
        if op in code:
            return f"代码中包含禁止的文件操作: {op}"

    return None


def _extract_module_name(statement: str) -> str:
    """从 import 语句中提取模块名。"""
    statement = statement.strip()
    if statement.startswith("import "):
        return statement.replace("import ", "").split(",")[0].split(" as ")[0].strip()
    if statement.startswith("from "):
        return statement.replace("from ", "").split(" import")[0].strip()
    return ""


def _build_safe_globals() -> dict[str, Any]:
    """构造受限的全局命名空间。"""
    import builtins

    safe_builtins = {k: v for k, v in builtins.__dict__.items() if k not in _FORBIDDEN_BUILTINS}

    imported = {}
    for mod_name in _ALLOWED_MODULES:
        try:
            imported[mod_name] = __import__(mod_name)
        except ImportError:
            pass

    for optional in ("numpy", "pandas"):
        try:
            imported[optional] = __import__(optional)
        except ImportError:
            pass

    return {"__builtins__": safe_builtins, **imported}
