"""Pure alert-condition evaluation (§42). DB-aware wiring lives in app.services.alert_service."""
from __future__ import annotations


def evaluate_condition(observed: float, condition: str, threshold: float) -> bool:
    if condition == ">":
        return observed > threshold
    if condition == "<":
        return observed < threshold
    raise ValueError(f"Unsupported condition '{condition}'. Use '>' or '<'.")


def should_fire(observed: float | None, condition: str, threshold: float, currently_met: bool) -> tuple[bool, bool]:
    """
    Returns (new_currently_met, should_fire_event). Fires at most once per
    condition-become-true transition — no repeat spam while the condition
    stays continuously true.
    """
    if observed is None:
        return currently_met, False
    met = evaluate_condition(observed, condition, threshold)
    fire = met and not currently_met
    return met, fire
