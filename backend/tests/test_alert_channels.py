from app.core.config import Settings
from app.services import alert_service


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


async def test_fire_email_skips_when_smtp_host_unconfigured(monkeypatch):
    monkeypatch.setattr(alert_service, "get_settings", lambda: _settings(smtp_host=""))
    called = False

    def fake_send(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(alert_service, "_send_smtp_email", fake_send)
    await alert_service._fire_email("trader@example.com", "atm_iv > 0.20 — observed 0.25")
    assert called is False


async def test_fire_email_sends_when_configured(monkeypatch):
    monkeypatch.setattr(alert_service, "get_settings", lambda: _settings(smtp_host="smtp.example.com"))
    sent = {}

    def fake_send(to_addr, subject, body):
        sent["to_addr"] = to_addr
        sent["subject"] = subject
        sent["body"] = body

    monkeypatch.setattr(alert_service, "_send_smtp_email", fake_send)
    await alert_service._fire_email("trader@example.com", "atm_iv > 0.20 — observed 0.25")
    assert sent["to_addr"] == "trader@example.com"
    assert "observed 0.25" in sent["body"]


async def test_fire_email_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(alert_service, "get_settings", lambda: _settings(smtp_host="smtp.example.com"))

    def broken_send(*args, **kwargs):
        raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(alert_service, "_send_smtp_email", broken_send)
    await alert_service._fire_email("trader@example.com", "message")  # must not raise


async def test_fire_telegram_skips_when_bot_token_unconfigured(monkeypatch):
    monkeypatch.setattr(alert_service, "get_settings", lambda: _settings(telegram_bot_token=""))

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("httpx.AsyncClient should not be constructed when unconfigured")

    monkeypatch.setattr(alert_service.httpx, "AsyncClient", ExplodingClient)
    await alert_service._fire_telegram("12345", "message")


async def test_fire_telegram_sends_when_configured(monkeypatch):
    monkeypatch.setattr(alert_service, "get_settings", lambda: _settings(telegram_bot_token="bot-token"))
    posted = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            posted["url"] = url
            posted["json"] = json

    monkeypatch.setattr(alert_service.httpx, "AsyncClient", FakeClient)
    await alert_service._fire_telegram("12345", "message")
    assert posted["url"] == "https://api.telegram.org/botbot-token/sendMessage"
    assert posted["json"] == {"chat_id": "12345", "text": "message"}


async def test_fire_telegram_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(alert_service, "get_settings", lambda: _settings(telegram_bot_token="bot-token"))

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            raise ConnectionError("network down")

    monkeypatch.setattr(alert_service.httpx, "AsyncClient", FailingClient)
    await alert_service._fire_telegram("12345", "message")  # must not raise