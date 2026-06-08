"""邮件发送工具 — Resend API（沙箱模式）。

环境变量：
    RESEND_API_KEY: Resend API Key。
    未设置时使用沙箱模式（记录但不真实发送）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 沙箱模式下的邮件记录
_SANDBOX_MAILBOX: list[dict[str, Any]] = []


async def send_email_impl(to: str, subject: str, body: str) -> dict[str, Any]:
    """发送邮件。

    Args:
        to: 收件人邮箱。
        subject: 邮件主题。
        body: 邮件正文。

    Returns:
        发送结果字典。
    """
    api_key = os.environ.get("RESEND_API_KEY")

    if not api_key:
        # 沙箱模式：记录邮件但不发送
        mail_record = {
            "to": to,
            "subject": subject,
            "body": body[:500],  # 限制长度
            "mode": "sandbox",
        }
        _SANDBOX_MAILBOX.append(mail_record)
        logger.info(f"[沙箱邮件] to={to}, subject={subject}")
        return {
            "success": True,
            "mode": "sandbox",
            "message": f"邮件已记录（沙箱模式，未真实发送）: to={to}, subject={subject}",
        }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                json={
                    "from": "AgentBench <onboarding@agentbench.dev>",
                    "to": [to],
                    "subject": subject,
                    "text": body,
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "success": True,
            "mode": "real",
            "email_id": data.get("id", ""),
            "message": f"邮件已发送: to={to}, subject={subject}",
        }
    except Exception as e:
        return {
            "success": False,
            "mode": "real",
            "error": f"邮件发送失败: {e}",
        }


def get_sandbox_mailbox() -> list[dict[str, Any]]:
    """获取沙箱模式下的邮件记录（用于评测验证）。"""
    return list(_SANDBOX_MAILBOX)


def clear_sandbox_mailbox() -> None:
    """清空沙箱邮件记录。"""
    _SANDBOX_MAILBOX.clear()
