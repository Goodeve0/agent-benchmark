"""网页搜索工具 — Tavily Search API。

环境变量：
    TAVILY_API_KEY: Tavily Search API Key。
    未设置时使用模拟搜索结果。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 模拟搜索结果
_MOCK_RESULTS: dict[str, list[dict[str, Any]]] = {
    "python": [
        {
            "title": "Python 官方文档",
            "url": "https://docs.python.org",
            "snippet": "Python 是一种解释型、面向对象、动态数据类型的高级程序设计语言。",
        },
        {
            "title": "Python Tutorial - W3Schools",
            "url": "https://www.w3schools.com/python",
            "snippet": "Learn Python with examples and exercises.",
        },
    ],
    "weather": [
        {"title": "天气预报 - 中国气象局", "url": "http://www.cma.gov.cn", "snippet": "提供全国天气预报、气象灾害预警等信息。"},
    ],
    "travel": [
        {"title": "携程旅行", "url": "https://www.ctrip.com", "snippet": "提供酒店预订、机票预订、旅游度假等产品和服务。"},
        {"title": "马蜂窝旅游", "url": "https://www.mafengwo.cn", "snippet": "旅游攻略,自由行,自助游攻略,旅游社交分享网站。"},
    ],
}


async def search_web_impl(query: str, max_results: int = 5) -> dict[str, Any]:
    """搜索互联网获取信息。

    Args:
        query: 搜索关键词。
        max_results: 最大返回结果数。

    Returns:
        搜索结果字典，包含 results 列表。
    """
    api_key = os.environ.get("TAVILY_API_KEY")

    if not api_key:
        logger.info("TAVILY_API_KEY 未设置，使用模拟搜索结果")
        return _get_mock_results(query, max_results)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:200],
            })

        return {
            "query": query,
            "answer": data.get("answer", ""),
            "results": results,
            "total": len(results),
        }
    except Exception as e:
        logger.warning(f"搜索 API 调用失败: {e}，降级到模拟数据")
        return _get_mock_results(query, max_results)


def _get_mock_results(query: str, max_results: int = 5) -> dict[str, Any]:
    """获取模拟搜索结果。"""
    key = query.lower().strip()
    matched = _MOCK_RESULTS.get(key, [
        {"title": f"搜索结果: {query}", "url": f"https://example.com/search?q={query}", "snippet": f"这是关于 {query} 的搜索结果摘要。"}
    ])
    return {
        "query": query,
        "results": matched[:max_results],
        "total": min(len(matched), max_results),
    }
