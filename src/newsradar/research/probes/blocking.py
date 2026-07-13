from __future__ import annotations

import httpx


def blocked_reason(response: httpx.Response) -> str | None:
    if response.status_code in {401, 403, 429}:
        return "访问需要认证、批准或受限配额"
    if response.status_code >= 500 and any(
        value in response.text.lower() for value in ("cloudflare", "challenge", "captcha")
    ):
        return "页面触发验证挑战，研究探测不会绕过"
    text = response.text.lower()
    if any(
        value in text
        for value in (
            "captcha",
            "recaptcha",
            "cloudflare",
            "verify",
            "sign in",
            "log in",
            "paywall",
            "subscription",
            "browser session",
        )
    ):
        return "页面需要登录、验证、付费或浏览器会话，研究探测已停止"
    return None
