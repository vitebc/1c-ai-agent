"""Смоук стабильности function calling.

Гоняет вопросы через агентскую петлю и считает: долю завершённых диалогов,
долю попаданий в ожидаемый инструмент, долю чистых прогонов (без ERROR-ретраев).

Два режима (запуск из backend/):
- моки:   uv run python scripts/smoke_tools.py  (questions.json)
- replay: uv run python scripts/smoke_tools.py --replay tests/fixtures/ka2_pilot.json
  (живые ответы 1С из фикстуры + replay_questions.json — регресс шейпинга
  и качества ответов на реальных данных без сети до базы).

Нужны LLM_BASE_URL / LLM_API_KEY / LLM_MODEL в .env (корень репозитория).
Критерий: choice_rate >= 0.9, иначе exit 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.agent import ToolRegistry, run_agent
from app.config import settings
from app.db.session import SessionFactory
from app.llm import OpenAICompatibleLLM
from app.onec import FakeOnecClient, McpOnecClient, build_onec_tools
from app.rag import build_embeddings, make_kb_search
from app.tools import MOCK_ONEC_TOOLS

THRESHOLD = 0.9
HERE = Path(__file__).resolve().parent


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", default=None, help="JSON-фикстура ответов 1С вместо моков")
    ap.add_argument("--live", action="store_true", help="живой прокси 1С (ONEC_MCP_URL) вместо моков")
    args = ap.parse_args()

    llm = OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        top_k=settings.llm_top_k,
        repetition_penalty=settings.llm_repetition_penalty,
        enable_thinking=settings.llm_enable_thinking,
    )
    embeddings = build_embeddings(settings.embeddings_provider, settings.tei_base_url)
    kb_tool = make_kb_search(SessionFactory, embeddings)
    if args.replay:
        fixture = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        registry = ToolRegistry(build_onec_tools(FakeOnecClient(calls=fixture)) + [kb_tool])
        questions = json.loads((HERE / "replay_questions.json").read_text(encoding="utf-8"))
    elif args.live:
        client = McpOnecClient(settings.onec_mcp_url, token=settings.onec_token)
        registry = ToolRegistry(build_onec_tools(client) + [kb_tool])
        questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    else:
        registry = ToolRegistry(MOCK_ONEC_TOOLS + [kb_tool])
        questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))

    completed = hits = clean = 0
    for i, item in enumerate(questions, 1):
        q, expected, profile = item["q"], item["expected"], item.get("profile", "all")
        try:
            res = await run_agent(
                llm=llm, registry=registry, user_message=q, access_profile=profile, max_rounds=settings.agent_max_rounds
            )
        except Exception as e:
            print(f"[{i:02d}] EXC {q!r}: {type(e).__name__}: {e}")
            print("Проверь LLM_BASE_URL / LLM_API_KEY / LLM_MODEL в .env — дальше нет смысла.")
            return 2
        done = "лимит раундов" not in res.answer
        hit = (expected in res.tool_calls) if expected != "none" else not res.tool_calls
        completed += done
        hits += done and hit
        clean += done and res.tool_errors == 0
        mark = "OK " if done and hit else "FAIL"
        print(f"[{i:02d}] {mark} exp={expected} prof={profile} got={res.tool_calls} errs={res.tool_errors} | {q}")
        print(f"      -> {res.answer[:150].replace(chr(10), ' ')}")

    total = len(questions)
    choice_rate = hits / completed if completed else 0.0
    print(f"\ncompleted {completed}/{total}  choice {hits}/{completed}={choice_rate:.2f}  clean {clean}/{total}")
    return 0 if choice_rate >= THRESHOLD else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
