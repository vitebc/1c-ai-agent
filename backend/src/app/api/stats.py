"""GET /stats/requests и /stats/summary — чтение статистики обращений.

Без авторизации (закрытый контур, как остальной API бэкенда).
Фильтры: user_id, base_name, agent, skill, from/to (ISO datetime).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatRequestLog
from app.db.session import SessionFactory

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/requests")
async def list_requests(
    user_id: str | None = Query(default=None, max_length=128),
    base_name: str | None = Query(default=None, max_length=128),
    agent: str | None = Query(default=None, max_length=64),
    skill: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, pattern="^(ok|error)$"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Список запросов с фильтрами и пагинацией."""
    # Колонка TIMESTAMP WITHOUT TIME ZONE — снимаем tzinfo.
    if from_ is not None and from_.tzinfo is not None:
        from_ = from_.replace(tzinfo=None)
    if to is not None and to.tzinfo is not None:
        to = to.replace(tzinfo=None)

    async with SessionFactory() as s:
        q = select(ChatRequestLog)
        if user_id:
            q = q.where(ChatRequestLog.user_id == user_id)
        if base_name:
            q = q.where(ChatRequestLog.base_name == base_name)
        if agent:
            q = q.where(ChatRequestLog.agent == agent)
        if skill:
            q = q.where(ChatRequestLog.skill == skill)
        if status:
            q = q.where(ChatRequestLog.status == status)
        if from_:
            q = q.where(ChatRequestLog.created_at >= from_)
        if to:
            q = q.where(ChatRequestLog.created_at <= to)

        total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0

        rows = (
            (await s.execute(q.order_by(ChatRequestLog.created_at.desc()).limit(limit).offset(offset)))
            .scalars()
            .all()
        )

        items = [
            {
                "id": r.id,
                "user_id": r.user_id,
                "session_id": r.session_id,
                "base_name": r.base_name,
                "base_url": r.base_url,
                "agent": r.agent,
                "skill": r.skill,
                "model": r.model,
                "question": r.question,
                "answer": r.answer,
                "status": r.status,
                "error": r.error,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "rounds": r.rounds,
                "tool_calls": r.tool_calls,
                "elapsed_s": r.elapsed_s,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    return {"total": total, "items": items}


@router.get("/summary")
async def summary(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> dict:
    """Сводка: всего, по пользователям, по базам, по агентам."""
    if from_ is None:
        from_ = datetime.now(timezone.utc) - timedelta(days=1)
    if to is None:
        to = datetime.now(timezone.utc)
    # Колонка TIMESTAMP WITHOUT TIME ZONE — снимаем tzinfo.
    if from_.tzinfo is not None:
        from_ = from_.replace(tzinfo=None)
    if to.tzinfo is not None:
        to = to.replace(tzinfo=None)

    async with SessionFactory() as s:
        base_q = select(ChatRequestLog).where(ChatRequestLog.created_at >= from_, ChatRequestLog.created_at <= to)

        total_row = (await s.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0
        tokens_row = (await s.execute(
            select(
                func.coalesce(func.sum(ChatRequestLog.total_tokens), 0),
                func.avg(ChatRequestLog.elapsed_s),
            ).where(ChatRequestLog.created_at >= from_, ChatRequestLog.created_at <= to)
        )).one()

        by_user_rows = (await s.execute(
            select(
                ChatRequestLog.user_id,
                func.count().label("count"),
                func.coalesce(func.sum(ChatRequestLog.total_tokens), 0).label("tokens"),
            )
            .where(ChatRequestLog.created_at >= from_, ChatRequestLog.created_at <= to)
            .group_by(ChatRequestLog.user_id)
            .order_by(func.count().desc())
            .limit(50)
        )).all()

        base_label = func.coalesce(ChatRequestLog.base_name, "(без базы)").label("base_name")
        by_base_rows = (await s.execute(
            select(base_label, func.count())
            .where(ChatRequestLog.created_at >= from_, ChatRequestLog.created_at <= to)
            .group_by(base_label)
            .order_by(func.count().desc())
        )).all()

        agent_label = func.coalesce(ChatRequestLog.agent, "(default)").label("agent")
        by_agent_rows = (await s.execute(
            select(agent_label, func.count())
            .where(ChatRequestLog.created_at >= from_, ChatRequestLog.created_at <= to)
            .group_by(agent_label)
            .order_by(func.count().desc())
        )).all()

    return {
        "from": from_.isoformat(),
        "to": to.isoformat(),
        "total_requests": total_row,
        "total_tokens": int(tokens_row[0]),
        "avg_elapsed_s": round(float(tokens_row[1]), 2) if tokens_row[1] is not None else 0.0,
        "by_user": [
            {"user_id": r[0], "count": r[1], "tokens": int(r[2])} for r in by_user_rows
        ],
        "by_base": [{"base_name": r[0], "count": r[1]} for r in by_base_rows],
        "by_agent": [{"agent": r[0], "count": r[1]} for r in by_agent_rows],
    }


@router.get("/distinct")
async def distinct_values() -> dict:
    """Списки для фильтров UI: уникальные user_id, base_name, agent."""
    async with SessionFactory() as s:
        users = (await s.execute(
            select(ChatRequestLog.user_id).distinct().order_by(ChatRequestLog.user_id)
        )).scalars().all()
        bases = (await s.execute(
            select(ChatRequestLog.base_name).where(ChatRequestLog.base_name.isnot(None))
            .distinct().order_by(ChatRequestLog.base_name)
        )).scalars().all()
        agents = (await s.execute(
            select(ChatRequestLog.agent).where(ChatRequestLog.agent.isnot(None))
            .distinct().order_by(ChatRequestLog.agent)
        )).scalars().all()

    return {
        "user_ids": list(users),
        "base_names": list(bases),
        "agents": list(agents),
    }
