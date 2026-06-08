"""真实工具实现集合。

每个工具函数都是异步的，签名为 ``async def impl(**params) -> dict``。
返回结果字典中不应包含 ``_source`` 字段（由 RealSandbox 自动添加）。

工具分类：
- get_weather: 天气查询（OpenWeatherMap API）
- search_web: 网页搜索（Tavily / Bing API）
- query_database: 数据库查询（SQLite）
- run_python: Python 代码执行（Docker 沙箱 / 本地受限执行）
- send_email: 邮件发送（Resend API，沙箱模式）
"""

from agent_bench.tools.database import describe_table_impl, list_tables_impl, query_database_impl
from agent_bench.tools.email import send_email_impl
from agent_bench.tools.python_executor import run_python_impl
from agent_bench.tools.search import search_web_impl
from agent_bench.tools.weather import get_weather_impl

__all__ = [
    "get_weather_impl",
    "search_web_impl",
    "query_database_impl",
    "list_tables_impl",
    "describe_table_impl",
    "run_python_impl",
    "send_email_impl",
    "get_all_tool_implementations",
    "get_tool_definitions",
]


def get_all_tool_implementations() -> dict:
    """返回所有真实工具实现的映射 {tool_name: impl_function}。"""
    return {
        "get_weather": get_weather_impl,
        "search_web": search_web_impl,
        "query_database": query_database_impl,
        "list_tables": list_tables_impl,
        "describe_table": describe_table_impl,
        "run_python": run_python_impl,
        "send_email": send_email_impl,
    }


def get_tool_definitions() -> dict:
    """返回所有工具的 OpenAI Function Calling 格式定义。"""
    from agent_bench.models import ToolDef

    return {
        "get_weather": ToolDef(
            name="get_weather",
            description="查询指定城市的当前天气信息，包括温度、湿度、天气状况等。",
            parameters={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，如 '北京'、'Shanghai'、'Tokyo'",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "温度单位，默认摄氏度",
                    },
                },
                "required": ["city"],
            },
        ),
        "search_web": ToolDef(
            name="search_web",
            description="搜索互联网获取信息，返回相关网页摘要。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认5",
                    },
                },
                "required": ["query"],
            },
        ),
        "query_database": ToolDef(
            name="query_database",
            description="执行 SQL 查询并返回结果。仅支持 SELECT 语句，禁止修改数据。",
            parameters={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL 查询语句（仅 SELECT）",
                    },
                },
                "required": ["sql"],
            },
        ),
        "list_tables": ToolDef(
            name="list_tables",
            description="列出数据库中所有可用的表名。",
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
        "describe_table": ToolDef(
            name="describe_table",
            description="获取指定表的结构信息，包括列名、类型等。",
            parameters={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "表名",
                    },
                },
                "required": ["table_name"],
            },
        ),
        "run_python": ToolDef(
            name="run_python",
            description="执行 Python 代码并返回输出结果。支持标准库和 numpy/pandas。禁止文件系统和网络操作。",
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要执行的 Python 代码",
                    },
                },
                "required": ["code"],
            },
        ),
        "send_email": ToolDef(
            name="send_email",
            description="发送邮件。沙箱模式下不会真正发送，仅记录邮件内容用于评测。",
            parameters={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "收件人邮箱地址",
                    },
                    "subject": {
                        "type": "string",
                        "description": "邮件主题",
                    },
                    "body": {
                        "type": "string",
                        "description": "邮件正文",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        ),
    }
