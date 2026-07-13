from __future__ import annotations

import httpx


def blocked_reason(response: httpx.Response, *, inspect_body: bool = True) -> str | None:
    if response.status_code in {401, 403, 429}:
        return "访问需要认证、批准或受限配额"
    if not inspect_body:
        return None
    if response.status_code >= 500 and any(
        value in response.text.lower() for value in ("cloudflare", "challenge", "captcha")
    ):
        return "页面触发验证挑战，研究探测不会绕过"
    text = response.text.lower()
    if any(
        value in text
        for value in (
            "captcha challenge",
            "recaptcha challenge",
            "cloudflare challenge",
            "cf-chl-",
            "verify you are human",
            "verification challenge",
            "sign in to continue",
            "log in to continue",
            "paywall",
            "subscription required",
            "browser session required",
        )
    ):
        return "页面需要登录、验证、付费或浏览器会话，研究探测已停止"
    return None
