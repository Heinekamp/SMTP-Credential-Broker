from pydantic import BaseModel


class HealthCheckDetail(BaseModel):
    ok: bool
    detail: str = ""


class HealthResponse(BaseModel):
    status: str
    database: HealthCheckDetail
    postfix_reachable: HealthCheckDetail
    postfix_running: HealthCheckDetail
    last_generation_result: str
    config_in_sync: HealthCheckDetail
