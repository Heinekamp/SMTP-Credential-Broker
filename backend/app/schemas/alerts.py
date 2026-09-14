from pydantic import BaseModel


class AlertRead(BaseModel):
    kind: str
    key: str
    title: str
    detail: str
    target_type: str | None
    target_id: int | None
    acknowledgeable: bool
    acknowledged: bool


class AlertsResponse(BaseModel):
    alerts: list[AlertRead]
    # Excludes already-acknowledged update alerts — matches typical
    # bell-badge semantics (a badge count an admin has already
    # acknowledged shouldn't keep demanding attention).
    active_count: int
