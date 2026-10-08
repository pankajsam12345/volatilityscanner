"""Wires the alert engine to real stored history and fires web/webhook/email/telegram notifications (§42)."""
from __future__ import annotations

import asyncio
import datetime as dt
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.engine import should_fire
from app.analytics.stats import zscore
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Alert, AlertEvent
from app.services import history_service

logger = get_logger("app.alerts")

RAW_METRICS_VIA_METRIC_HISTORY = {"atm_iv", "calendar_spread", "forward_vol"}


async def _base_series(session: AsyncSession, underlying_id: int, base_metric: str, bucket: str) -> list[float]:
    if base_metric == "iv_rv":
        _, iv_hist, rv_hist = await history_service.get_aligned_iv_rv_series_with_dates(session, underlying_id, bucket)
        return [iv - rv for iv, rv in zip(iv_hist, rv_hist)]
    if base_metric == "rv20":
        rows = await history_service.get_hv_series(session, underlying_id, 20, "CLOSE_CLOSE")
        return [v for _, v in rows if v is not None]
    # atm_iv, calendar_spread, forward_vol, skew_{d}, rr_{d}, bf_{d}
    rows = await history_service.get_metric_history_with_timestamps(session, underlying_id, base_metric, bucket)
    return [v for _, v in rows]


async def get_observed_value(session: AsyncSession, underlying_id: int, metric: str, bucket: str) -> float | None:
    is_zscore = metric.endswith("_zscore")
    base_metric = metric[: -len("_zscore")] if is_zscore else metric

    series = await _base_series(session, underlying_id, base_metric, bucket)
    if not series:
        return None
    if not is_zscore:
        return series[-1]
    return zscore(series[-1], series[:-1])


async def _fire_webhook(url: str, message: str, observed_value: float) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json={"message": message, "observed_value": observed_value})
    except Exception as exc:  # noqa: BLE001 — a broken webhook must never crash the alert check
        logger.error(f"Webhook delivery failed for {url}: {exc}")


def _send_smtp_email(to_addr: str, subject: str, body: str) -> None:
    settings = get_settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_addr
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5.0) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


async def _fire_email(to_addr: str, message: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        logger.error(f"EMAIL alert to {to_addr} skipped: smtp_host is not configured")
        return
    try:
        await asyncio.to_thread(_send_smtp_email, to_addr, "Volatility Opportunity Scanner alert", message)
    except Exception as exc:  # noqa: BLE001 — a broken mail server must never crash the alert check
        logger.error(f"Email delivery failed for {to_addr}: {exc}")


async def _fire_telegram(chat_id: str, message: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.error(f"TELEGRAM alert to {chat_id} skipped: telegram_bot_token is not configured")
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json={"chat_id": chat_id, "text": message})
    except Exception as exc:  # noqa: BLE001 — a broken bot/network must never crash the alert check
        logger.error(f"Telegram delivery failed for chat {chat_id}: {exc}")


async def check_all_alerts(session: AsyncSession) -> list[AlertEvent]:
    alerts = (await session.execute(select(Alert).where(Alert.is_active.is_(True)))).scalars().all()
    fired: list[AlertEvent] = []

    for alert in alerts:
        observed = await get_observed_value(session, alert.underlying_id, alert.metric, alert.bucket)
        new_met, fire = should_fire(observed, alert.condition, alert.threshold, alert.currently_met)
        alert.currently_met = new_met

        if fire:
            now = dt.datetime.now(dt.timezone.utc)
            message = f"{alert.metric} ({alert.bucket or 'n/a'}) {alert.condition} {alert.threshold} — observed {observed:.4f}"
            event = AlertEvent(alert_id=alert.id, triggered_at=now, observed_value=observed, message=message)
            session.add(event)
            alert.last_triggered_at = now
            fired.append(event)

            if alert.channel == "WEBHOOK" and alert.webhook_url:
                await _fire_webhook(alert.webhook_url, message, observed)
            elif alert.channel == "EMAIL" and alert.recipient:
                await _fire_email(alert.recipient, message)
            elif alert.channel == "TELEGRAM" and alert.recipient:
                await _fire_telegram(alert.recipient, message)

    await session.commit()
    return fired
