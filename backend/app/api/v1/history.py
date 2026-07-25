from fastapi import APIRouter

from app.core.constants import Tags
from app.schemas.history import LogEntry, RunSummary, StatsSummary
from app.services import history_repository

router = APIRouter(tags=[Tags.HISTORY])


@router.get("/runs", response_model=list[RunSummary], summary="List past automation runs")
def get_runs(limit: int = 20) -> list[RunSummary]:
    return [RunSummary(**run) for run in history_repository.list_runs(limit=limit)]


@router.get("/logs", response_model=list[LogEntry], summary="List recent audit log entries")
def get_logs(limit: int = 100) -> list[LogEntry]:
    return [LogEntry(**log) for log in history_repository.list_logs(limit=limit)]


@router.get("/stats", response_model=StatsSummary, summary="Aggregate processing statistics")
def get_stats() -> StatsSummary:
    return StatsSummary(**history_repository.get_stats())
