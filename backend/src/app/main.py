from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.config import settings


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
    return app


app = create_app()
