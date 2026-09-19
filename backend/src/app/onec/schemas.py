"""Контракт инструментов 1С: pydantic-схемы аргументов.

Единый источник правды для моков (шаг 1), BSL-инструментов расширения
`onec/ext` и live-адаптера: имена и параметры совпадают 1:1, поэтому замена
моков на живые вызовы прозрачна для модели.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SkdReportArgs(BaseModel):
    """Отчёт по готовому макету из каталога."""

    report: Literal["sales_by_warehouse", "debtors"]
    period: str = Field(pattern=r"^\d{4}-(Q[1-4]|H[12]|Y)$", examples=["2026-Q1"])
    warehouse: str | None = Field(default=None, description="Фильтр по складу, только для sales_by_warehouse")
    limit: int = Field(default=20, le=100)


class CounterpartyArgs(BaseModel):
    """Карточка контрагента по названию (подстрока) или ИНН."""

    query: str = Field(min_length=2)


class StockArgs(BaseModel):
    """Остатки номенклатуры по складам."""

    sku: str = Field(min_length=2)
    warehouse: str | None = None


class ExecuteSelectArgs(BaseModel):
    """Произвольный запрос: только ВЫБРАТЬ/SELECT, кап строк на стороне 1С."""

    query: str = Field(min_length=1)
    limit: int = Field(default=50, le=200)


class ValidateQueryArgs(BaseModel):
    """Проверка синтаксиса запроса пробным выполнением (ПЕРВЫЕ 1)."""

    query: str = Field(min_length=1)
