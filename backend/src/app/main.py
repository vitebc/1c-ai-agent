import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.stats import router as stats_router
from app.config import settings

# Без этого INFO-логи петли (agent1c.loop) тонут: root-логгер по умолчанию WARNING.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _setup_loop_file_logging() -> None:
    """Дублировать логи петли в файл с полным контентом раундов (LOOP_LOG_FILE).

    Ротация 50 МБ × 3 файла — полный лог тяжёлый (полные ответы модели и
    результаты инструментов), бесконечный файл не допустим.
    """
    path = settings.loop_log_file.strip()
    if not path:
        return
    try:
        loop_logger = logging.getLogger("agent1c.loop")
        # Уровень явный: без него логгер наследует WARNING от root (родитель
        # agent1c handler'ов не имеет), и INFO-записи в файл не проходят,
        # хотя в stdout через basicConfig видны.
        loop_logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            path, maxBytes=50 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        loop_logger.addHandler(handler)
    except OSError as e:
        # Файл недоступен (нет папки/прав) — не роняем бэкенд, только stdout.
        logging.getLogger("agent1c.main").warning("LOOP_LOG_FILE=%s недоступен: %s", path, e)


_setup_loop_file_logging()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    # Чат-форма 1С ходит из HTML-документа (opaque origin) через XHR —
    # без CORS браузер режет кросс-доменные запросы. Куки не используем
    # (user_id в теле), поэтому открываем полностью; для прода сузить.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(stats_router)
    return app


app = create_app()
