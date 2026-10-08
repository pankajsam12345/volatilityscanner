import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Alert, AlertEvent, Underlying, User
from app.services.alert_service import check_all_alerts

router = APIRouter()


class CreateAlertRequest(BaseModel):
    symbol: str
    metric: str
    bucket: str = ""
    condition: str
    threshold: float
    channel: str = "WEB"
    webhook_url: Optional[str] = None
    recipient: Optional[str] = None


def _alert_to_dict(a: Alert, symbol: str) -> dict:
    return {
        "id": a.id, "symbol": symbol, "metric": a.metric, "bucket": a.bucket, "condition": a.condition,
        "threshold": a.threshold, "channel": a.channel, "webhook_url": a.webhook_url, "recipient": a.recipient,
        "is_active": a.is_active, "currently_met": a.currently_met, "last_triggered_at": a.last_triggered_at,
    }


@router.post("/alerts")
async def create_alert(body: CreateAlertRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if body.condition not in (">", "<"):
        raise HTTPException(422, "condition must be '>' or '<'")
    if body.channel not in ("WEB", "WEBHOOK", "EMAIL", "TELEGRAM"):
        raise HTTPException(422, "channel must be one of WEB, WEBHOOK, EMAIL, TELEGRAM")
    if body.channel == "WEBHOOK" and not body.webhook_url:
        raise HTTPException(422, "webhook_url is required for the WEBHOOK channel")
    if body.channel in ("EMAIL", "TELEGRAM") and not body.recipient:
        raise HTTPException(422, f"recipient is required for the {body.channel} channel")
    underlying = (await db.execute(select(Underlying).where(Underlying.symbol == body.symbol))).scalar_one_or_none()
    if underlying is None:
        raise HTTPException(404, f"Unknown symbol '{body.symbol}'")

    alert = Alert(
        underlying_id=underlying.id, metric=body.metric, bucket=body.bucket, condition=body.condition,
        threshold=body.threshold, channel=body.channel, webhook_url=body.webhook_url, recipient=body.recipient,
        is_active=True, created_at=dt.datetime.now(dt.timezone.utc), currently_met=False,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return _alert_to_dict(alert, body.symbol)


@router.get("/alerts")
async def list_alerts(symbol: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Alert, Underlying.symbol).join(Underlying).where(Alert.is_active.is_(True)).order_by(Alert.created_at.desc())
    if symbol:
        stmt = stmt.where(Underlying.symbol == symbol)
    rows = (await db.execute(stmt)).all()
    return [_alert_to_dict(a, s) for a, s in rows]


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    alert = (await db.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        raise HTTPException(404, f"No alert {alert_id}")
    alert.is_active = False
    await db.commit()
    return {"status": "deactivated"}


@router.get("/alerts/events")
async def list_alert_events(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(AlertEvent).order_by(AlertEvent.triggered_at.desc()).limit(50))
    ).scalars().all()
    return [
        {"id": e.id, "alert_id": e.alert_id, "triggered_at": e.triggered_at, "observed_value": e.observed_value, "message": e.message}
        for e in rows
    ]


@router.post("/alerts/check")
async def trigger_alert_check(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    fired = await check_all_alerts(db)
    return {"fired": len(fired)}
