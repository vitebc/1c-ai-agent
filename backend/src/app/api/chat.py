"""POST /chat: вопрос -> агент -> SSE-стрим событий с персистентностью.

События: `tool` (вызов инструмента), `answer` (финальный ответ кусками),
`done` (мета: session_id, rounds, tool_errors).
Настоящий токен-стриминг появится с локальной моделью; пока ответ режем кусками.
Поддерживает вложения (attachments) как multimodal content и ограничение
истории через context_size. Фоновый режим ?background=true возвращает JSON
{job_id} с polling GET /chat/result/{job_id}.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import SYSTEM_PROMPT, AgentResult, ToolRegistry, run_agent
from app.agents import Agent, AgentRegistry
from app.config import settings
from app.db.models import ChatSession, Message, User
from app.db.session import SessionFactory
from app.llm import ChatLLM, OpenAICompatibleLLM
from app.llm.client import build_user_content
from app.onec import McpOnecClient, build_onec_tools
from app.rag import build_embeddings, make_kb_search
from app.skills import Skill, SkillRegistry
from app.tools import MOCK_ONEC_TOOLS

router = APIRouter()

log = logging.getLogger("agent1c.chat")

# In-memory store для фоновых задач (достаточно для совместимости с BSL).
# Потокобезопасность не нужна — один процесс, GIL.
_background_jobs: dict[str, dict[str, Any]] = {}


class Attachment(BaseModel):
    filename: str = Field(min_length=1, max_length=512, validation_alias="name", alias_priority=1)
    mime_type: str = Field(
        default="application/octet-stream",
        max_length=256,
        validation_alias="mime",
    )
    content_base64: str = Field(
        default="",
        max_length=20_000_000,
        validation_alias="data_base64",
    )
    # url-альтернатива для будущего расширения — пока не используется
    url: str | None = Field(default=None, max_length=2048)

    model_config = {"populate_by_name": True, "extra": "ignore"}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: int | None = None
    # Идентификатор пользователя 1С. На шаге 3 сюда придёт OAuth-токен прокси.
    user_id: str = "dev"
    attachments: list[Attachment] | None = Field(default=None, max_length=10)
    context_size: int | None = Field(
        default=None, ge=1, le=100, description="Сколько последних пар сообщений передавать в LLM"
    )
    # Имя ИБ 1С (НРег) для мультибазовости: считает BSL (БСП или разбор строки соединения).
    base_name: str | None = Field(default=None, max_length=128)
    # Рантайм-скил (backend/skills/<name>); пусто — авто-матчинг по description.
    skill: str | None = Field(default=None, max_length=64)
    # Рантайм-агент (backend/agents/<name>); пусто — агент по умолчанию.
    agent: str | None = Field(default=None, max_length=64)

    model_config = {"extra": "ignore"}


async def get_llm() -> ChatLLM:
    return OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        top_k=settings.llm_top_k,
        repetition_penalty=settings.llm_repetition_penalty,
        enable_thinking=settings.llm_enable_thinking,
    )


async def get_registry() -> ToolRegistry:
    embeddings = build_embeddings(settings.embeddings_provider, settings.tei_base_url)
    if settings.onec_mode == "live":
        client = McpOnecClient(settings.onec_mcp_url, token=settings.onec_token)
        return ToolRegistry(build_onec_tools(client) + [make_kb_search(SessionFactory, embeddings)])
    if settings.onec_mode != "mock":
        raise ValueError(f"ONEC_MODE: жди 'mock' или 'live', получено {settings.onec_mode!r}")
    return ToolRegistry(MOCK_ONEC_TOOLS + [make_kb_search(SessionFactory, embeddings)])


async def get_skill_registry() -> SkillRegistry:
    # Перечитываем файлы на каждый запрос: новый SKILL.md подхватывается без рестарта.
    return SkillRegistry.load(settings.skills_dir)


async def get_agent_registry() -> AgentRegistry:
    # Перечитываем файлы на каждый запрос: новый AGENT.md подхватывается без рестарта.
    return AgentRegistry.load(settings.agents_dir)


@router.get("/agents")
async def list_agents(agents: AgentRegistry = Depends(get_agent_registry)) -> JSONResponse:  # noqa: B008
    """Агенты для дропдауна формы 1С: имя + title + описание + инструменты + битые файлы."""
    return JSONResponse(
        {
            "default": settings.default_agent,
            "agents": [
                {
                    "name": a.name,
                    "title": a.title,
                    "description": a.description,
                    "tools": list(a.tools),
                    "skills": list(a.skills),
                }
                for a in agents.agents
            ],
            "errors": list(agents.errors),
        }
    )


@router.get("/skills")
async def list_skills(
    skills: SkillRegistry = Depends(get_skill_registry),  # noqa: B008
    agents: AgentRegistry = Depends(get_agent_registry),  # noqa: B008
    agent: str | None = Query(default=None, max_length=64, description="Фильтр скилов по агенту"),
) -> JSONResponse:
    """Скилы для дропдауна формы 1С: имя + описание + инструменты + битые файлы."""
    visible = skills.skills
    if agent is not None:
        spec = agents.get(agent)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"agent not found: {agent}")
        if not spec.allows_all_skills:
            visible = [s for s in visible if s.name in spec.skills]
    return JSONResponse(
        {
            "skills": [{"name": s.name, "description": s.description, "tools": list(s.tools)} for s in visible],
            "errors": list(skills.errors),
        }
    )


def _history_to_messages(rows: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in rows:
        if m.role in ("user", "assistant"):
            out.append({"role": m.role, "content": m.content})
    return out


@router.get("/chat/result/{job_id}")
async def chat_result(job_id: str) -> JSONResponse:
    job = _background_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] == "running":
        return JSONResponse({"job_id": job_id, "status": "running", "session_id": job["session_id"]})
    if job["status"] == "error":
        return JSONResponse(
            {"job_id": job_id, "status": "error", "error": job.get("error"), "session_id": job["session_id"]}
        )
    result: AgentResult = job["result"]
    return JSONResponse(
        {
            "job_id": job_id,
            "status": "done",
            "session_id": job["session_id"],
            "agent": job.get("agent_name"),
            "skill": job.get("skill_name"),
            "answer": result.answer,
            "rounds": result.rounds,
            "tool_calls": result.tool_calls,
            "tool_errors": result.tool_errors,
        }
    )


@router.post("/chat", response_model=None)
async def chat(
    req: ChatRequest,
    background: bool = Query(
        default=False, description="Фоновый режим: вернуть job_id и опрашивать GET /chat/result/{job_id}"
    ),
    llm: ChatLLM = Depends(get_llm),  # noqa: B008 — идиома FastAPI
    registry: ToolRegistry = Depends(get_registry),  # noqa: B008 — идиома FastAPI
    skills: SkillRegistry = Depends(get_skill_registry),  # noqa: B008 — идиома FastAPI
    agents: AgentRegistry = Depends(get_agent_registry),  # noqa: B008 — идиома FastAPI
) -> Any:
    # Защита от огромных вложений на уровне сериализации уже есть (max_length),
    # но дополнительно режем число вложений
    if req.attachments and len(req.attachments) > 10:
        raise HTTPException(status_code=413, detail="too many attachments (max 10)")
    # Создаём/находим сессию и грузим историю
    async with SessionFactory() as session:
        user = (await session.execute(select(User).where(User.onec_id == req.user_id))).scalar_one_or_none()
        if user is None:
            user = User(onec_id=req.user_id, display_name=req.user_id)
            session.add(user)
            await session.flush()
        chat_session = None
        if req.session_id is not None:
            chat_session = (
                await session.execute(
                    select(ChatSession).where(ChatSession.id == req.session_id, ChatSession.user_id == user.id)
                )
            ).scalar_one_or_none()
            if chat_session is None:
                raise HTTPException(status_code=404, detail="session not found")
            if req.base_name and chat_session.base_name and chat_session.base_name != req.base_name:
                # Сессия чужой базы — историю не смешиваем, заводим новую.
                chat_session = None
            elif req.base_name and not chat_session.base_name:
                # Старая сессия без базы — привязываем к текущей.
                chat_session.base_name = req.base_name
        if chat_session is None:
            chat_session = ChatSession(user_id=user.id, title=req.message[:80], base_name=req.base_name)
            session.add(chat_session)
            await session.flush()
        session_id, profile = chat_session.id, user.access_profile
        # Агент: явный выбор > залипший в сессии > дефолт. Итог пишем в сессию.
        agent_spec: Agent | None = None
        if req.agent is not None:
            agent_spec = agents.get(req.agent)
            if agent_spec is None:
                raise HTTPException(status_code=404, detail=f"agent not found: {req.agent}")
        elif chat_session.agent_name:
            agent_spec = agents.get(chat_session.agent_name)
            if agent_spec is None:
                chat_session.agent_name = None  # файл агента удалён — отвязываем
        if agent_spec is None:
            agent_spec = agents.get(settings.default_agent)
            if agent_spec is None and agents.agents:
                agent_spec = agents.agents[0]
            if agent_spec is None:
                raise HTTPException(status_code=500, detail="no agents configured")
        chat_session.agent_name = agent_spec.name
        # Модель: оверрайд из AGENT.md, иначе из конфига.
        if agent_spec.model and agent_spec.model != settings.llm_model:
            llm = OpenAICompatibleLLM(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=agent_spec.model,
                temperature=settings.llm_temperature,
                top_p=settings.llm_top_p,
                top_k=settings.llm_top_k,
                repetition_penalty=settings.llm_repetition_penalty,
                enable_thinking=settings.llm_enable_thinking,
            )
            log.info("агент %s: модель %s (оверрайд)", agent_spec.name, agent_spec.model)
        # Скил внутри агента: явный обязан быть разрешён, залипший чужой — сброс, иначе авто-матчинг среди своих.
        skill: Skill | None = None
        if req.skill is not None:
            skill = skills.get(req.skill)
            if skill is None:
                raise HTTPException(status_code=404, detail=f"skill not found: {req.skill}")
            if not agent_spec.allows_skill(skill.name):
                raise HTTPException(status_code=404, detail=f"skill not available for agent {agent_spec.name}")
        elif chat_session.skill_name:
            skill = skills.get(chat_session.skill_name)
            if skill is None or not agent_spec.allows_skill(skill.name):
                chat_session.skill_name = None  # файл удалён или скил чужого агента — отвязываем
                skill = None
        if skill is None and req.skill is None:
            embeddings = build_embeddings(settings.embeddings_provider, settings.tei_base_url)
            scoped = (
                SkillRegistry(skills=list(skills.skills))
                if agent_spec.allows_all_skills
                else SkillRegistry(skills=[s for s in skills.skills if s.name in agent_spec.skills])
            )
            skill = await scoped.match(req.message, embeddings)
        if skill is not None:
            chat_session.skill_name = skill.name
        else:
            chat_session.skill_name = None
        missing = [t for t in agent_spec.tools if t not in registry.names]
        if missing:
            log.warning("агент %s ссылается на неизвестные инструменты: %s", agent_spec.name, missing)
        registry = registry.subset(agent_spec.tools)
        if skill is not None:
            missing = [t for t in skill.tools if t not in registry.names]
            if missing:
                log.warning("скил %s ссылается на неизвестные инструменты: %s", skill.name, missing)
            registry = registry.subset(skill.tools)
        # История до текущего сообщения
        history_rows: list[Message] = []
        # Загружаем историю если нужен context_size или просто для передачи в LLM
        # При context_size = N берём последние N пар (2*N сообщений)
        if req.context_size is not None:
            limit = req.context_size * 2
            q = select(Message).where(Message.session_id == session_id).order_by(Message.id.desc()).limit(limit)
            rows = (await session.execute(q)).scalars().all()
            history_rows = list(reversed(rows))
        else:
            # По умолчанию — тоже грузим историю (ограничим 20 последних пар чтобы не раздуть промпт)
            q = select(Message).where(Message.session_id == session_id).order_by(Message.id.desc()).limit(40)
            rows = (await session.execute(q)).scalars().all()
            history_rows = list(reversed(rows))
        history = _history_to_messages(history_rows)
        # Сохраняем текущее сообщение пользователя (текст, без base64 чтобы не раздувать БД)
        stored_content = req.message
        if req.attachments:
            names = ", ".join(a.filename for a in req.attachments)
            stored_content = f"{req.message}\n[Вложения: {names}]" if req.message else f"[Вложения: {names}]"
        session.add(Message(session_id=session_id, role="user", content=stored_content))
        await session.commit()

    # Формируем multimodal content для LLM
    att_dicts: list[dict[str, str]] | None = None
    if req.attachments:
        att_dicts = [
            {"filename": a.filename, "mime_type": a.mime_type, "content_base64": a.content_base64, "url": a.url or ""}
            for a in req.attachments
        ]
    user_content: str | list[dict[str, Any]] = build_user_content(req.message, att_dicts)

    extra_system = skill.system_block if skill is not None else ""
    skill_name = skill.name if skill is not None else ""
    base_system = agent_spec.prompt.strip() or SYSTEM_PROMPT
    agent_name = agent_spec.name
    if background:
        job_id = uuid.uuid4().hex
        _background_jobs[job_id] = {
            "status": "running",
            "session_id": session_id,
            "skill_name": skill_name or None,
            "agent_name": agent_name,
            "result": None,
        }

        async def _run_bg() -> None:
            try:
                result = await run_agent(
                    llm=llm,
                    registry=registry,
                    user_message=user_content,
                    user_id=req.user_id,
                    access_profile=profile,
                    base_name=req.base_name or "",
                    max_rounds=settings.agent_max_rounds,
                    history=history if history else None,
                    extra_system=extra_system,
                    skill_name=skill_name,
                    agent_name=agent_name,
                    base_system=base_system,
                )
                async with SessionFactory() as s:
                    s.add(Message(session_id=session_id, role="assistant", content=result.answer))
                    await s.commit()
                _background_jobs[job_id].update({"status": "done", "result": result})
            except Exception as e:  # noqa: BLE001
                _background_jobs[job_id].update({"status": "error", "error": str(e)})

        asyncio.create_task(_run_bg())
        return JSONResponse({"job_id": job_id, "session_id": session_id, "status": "running", "agent": agent_name})

    try:
        result = await run_agent(
            llm=llm,
            registry=registry,
            user_message=user_content,
            user_id=req.user_id,
            access_profile=profile,
            base_name=req.base_name or "",
            max_rounds=settings.agent_max_rounds,
            history=history if history else None,
            extra_system=extra_system,
            skill_name=skill_name,
            agent_name=agent_name,
            base_system=base_system,
        )
    except Exception as e:  # noqa: BLE001 — показываем ошибку в чате, а не 500
        # 1С ждёт SSE, поэтому отдаём ошибку как обычный answer, чтобы форма показала текст а не "HTTP 500"
        err_text = (
            f"Ошибка обращения к LLM ({type(e).__name__}: {e}). "
            f"Проверь .env: LLM_BASE_URL={settings.llm_base_url}, LLM_MODEL={settings.llm_model} "
            f"и LLM_API_KEY задан (сейчас {'пуст' if settings.llm_api_key in ('none', '') else 'задан'}). "
            f"Для локальной модели укажи http://llama:8080/v1 и ключ none."
        )
        result = AgentResult(answer=err_text, rounds=0, tool_calls=[], tool_errors=1)

    async with SessionFactory() as session:
        session.add(Message(session_id=session_id, role="assistant", content=result.answer))
        await session.commit()

    return StreamingResponse(_events(session_id, result, skill_name, agent_name), media_type="text/event-stream")


async def _events(
    session_id: int, result: AgentResult, skill_name: str = "", agent_name: str = ""
) -> AsyncIterator[str]:
    for tool_name in result.tool_calls:
        yield f"event: tool\ndata: {json.dumps({'tool': tool_name}, ensure_ascii=False)}\n\n"
    # Ответ кусками по ~500 символов — скелет стриминга до токенного.
    for i in range(0, len(result.answer), 500):
        yield f"event: answer\ndata: {json.dumps({'delta': result.answer[i : i + 500]}, ensure_ascii=False)}\n\n"
    meta = {
        "session_id": session_id,
        "agent": agent_name or None,
        "skill": skill_name or None,
        "rounds": result.rounds,
        "tool_errors": result.tool_errors,
    }
    yield f"event: done\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
