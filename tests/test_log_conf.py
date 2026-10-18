"""log_conf 凭据打码护栏（L16 纵深防御）。

覆盖 _mask_secrets 的正/负样本：常见凭据形态必须被打码，
普通日志行（含 count= / size= 等）不得误伤。
"""

from app.log_conf import _REDACTED, _mask_secrets


def test_authorization_bearer_redacted():
    out = _mask_secrets("POST /v1 Authorization: Bearer sk-abc123DEF456ghi789")
    assert _REDACTED in out
    assert "abc123DEF456" not in out
    assert "sk-abc123DEF456" not in out


def test_key_value_forms_redacted():
    for line, secret in (("api_key=1234567890abcdef", "1234567890abcdef"),
                         ("proxy_token=aB3dE5fG7h9i", "aB3dE5fG7h9i"),
                         ("token: SUPERSECRETtoken99", "SUPERSECRETtoken99"),
                         ("?access_token=deadbeef1234 ok", "deadbeef1234")):
        out = _mask_secrets(line)
        assert _REDACTED in out, line
        assert secret not in out, line


def test_standalone_sk_key_redacted():
    out = _mask_secrets("using sk-proj-abcdef1234567890ABCDEF now")
    assert "abcdef1234567890" not in out
    assert out.startswith("using sk-")


def test_hook_event_key_query_param_redacted():
    """?key= 形态的 hook 事件令牌必须打码（裸 key 不在原
    alternation 里，上报 URL 进日志时会漏）。"""
    out = _mask_secrets(
        "POST /api/hooks/hermes-event?key=abc123def456 HTTP/1.1")
    assert _REDACTED in out
    assert "abc123def456" not in out
    # key: value 形态同样覆盖
    out2 = _mask_secrets("hook url key: deadbeefcafe1234 end")
    assert "deadbeefcafe1234" not in out2


def test_ordinary_lines_untouched():
    for line in ("GET /api/status 200 12ms",
                 "normal line size=1024 count=5",
                 "user typed: how do I set my password to hello world"):
        assert _mask_secrets(line) == line


def test_masking_formatter_applies(caplog):
    import logging

    from app.log_conf import _MaskingFormatter
    rec = logging.LogRecord("httpx", logging.INFO, "", 0,
                            "request Authorization: Bearer topsecretvalue99",
                            (), None)
    out = _MaskingFormatter("%(name)s %(message)s").format(rec)
    assert "topsecretvalue99" not in out
    assert _REDACTED in out
