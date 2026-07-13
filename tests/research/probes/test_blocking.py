import httpx

from newsradar.research.probes.blocking import blocked_reason


def test_login_challenge_and_rate_limit_are_blocked() -> None:
    assert blocked_reason(httpx.Response(200, text="Sign in to continue"))
    assert blocked_reason(httpx.Response(429, text="slow down"))
    assert blocked_reason(httpx.Response(503, text="Cloudflare challenge"))


def test_public_article_navigation_does_not_look_like_a_login_wall() -> None:
    response = httpx.Response(
        200,
        text=(
            "<nav><a>Sign in</a></nav>"
            "<article>How to verify model outputs</article>"
            "<script>const captchaProvider = 'cloudflare';</script>"
        ),
    )

    assert blocked_reason(response) is None
