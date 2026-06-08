"""天气查询工具 — OpenWeatherMap API。

环境变量：
    OPENWEATHER_API_KEY: OpenWeatherMap API Key。
    未设置时使用模拟数据。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 模拟数据（API Key 未设置时的降级数据）
_MOCK_WEATHER: dict[str, dict[str, Any]] = {
    "beijing": {"temp": 22, "feels_like": 20, "humidity": 45, "description": "晴", "wind_speed": 3.2, "city": "北京"},
    "shanghai": {"temp": 26, "feels_like": 28, "humidity": 72, "description": "多云", "wind_speed": 4.1, "city": "上海"},
    "tokyo": {"temp": 24, "feels_like": 25, "humidity": 60, "description": "小雨", "wind_speed": 2.8, "city": "东京"},
    "new york": {"temp": 18, "feels_like": 16, "humidity": 55, "description": "阴天", "wind_speed": 5.5, "city": "纽约"},
    "london": {"temp": 14, "feels_like": 12, "humidity": 80, "description": "小雨", "wind_speed": 6.0, "city": "伦敦"},
}


async def get_weather_impl(city: str, unit: str = "celsius") -> dict[str, Any]:
    """查询城市天气。

    Args:
        city: 城市名称。
        unit: 温度单位 (celsius / fahrenheit)。

    Returns:
        天气信息字典。
    """
    api_key = os.environ.get("OPENWEATHER_API_KEY")

    if not api_key:
        logger.info("OPENWEATHER_API_KEY 未设置，使用模拟天气数据")
        return _get_mock_weather(city, unit)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "q": city,
                    "appid": api_key,
                    "units": "metric" if unit == "celsius" else "imperial",
                    "lang": "zh_cn",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        temp = data["main"]["temp"]
        return {
            "city": data.get("name", city),
            "temp": temp,
            "feels_like": data["main"]["feels_like"],
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"],
            "wind_speed": data["wind"]["speed"],
            "unit": unit,
        }
    except Exception as e:
        logger.warning(f"天气 API 调用失败: {e}，降级到模拟数据")
        return _get_mock_weather(city, unit)


def _get_mock_weather(city: str, unit: str = "celsius") -> dict[str, Any]:
    """获取模拟天气数据。"""
    key = city.lower().strip()
    weather = _MOCK_WEATHER.get(key, {"temp": 20, "feels_like": 19, "humidity": 50, "description": "晴", "wind_speed": 3.0, "city": city})
    result = {**weather}
    if unit == "fahrenheit" and "temp" in result:
        result["temp"] = round(result["temp"] * 9 / 5 + 32, 1)
        result["feels_like"] = round(result["feels_like"] * 9 / 5 + 32, 1)
    result["unit"] = unit
    return result
