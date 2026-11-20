"""Exceções explícitas que preservam a validação mesmo com Python otimizado."""

from datetime import date

import polars as pl
import pytest

from motor.experiments import monthly_report
from motor.io.quality_report import _active_items
from motor.reporting.purchase_list import _first_sale_and_days_with_sales


def test_first_sale_rejects_invalid_aggregated_date(monkeypatch: pytest.MonkeyPatch) -> None:
    demand = pl.DataFrame({"date": [date(2026, 1, 1)], "units_sold": [1.0]})

    def invalid_min(_series: pl.Series) -> str:
        return "data inválida"

    monkeypatch.setattr(pl.Series, "min", invalid_min)
    with pytest.raises(TypeError) as error:
        _first_sale_and_days_with_sales(demand, date(2026, 1, 2))
    assert str(error.value) == "A primeira data de venda deve ser uma data válida."


def test_month_count_rejects_non_integer_evaluation_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monthly_report, "_evaluation_window", lambda: {"n_evaluation_days": "60"})
    with pytest.raises(TypeError) as error:
        monthly_report.n_months_no_periodo()
    assert str(error.value) == "simulation_window.n_evaluation_days deve ser um inteiro."


def test_active_items_rejects_missing_latest_date() -> None:
    sales = pl.DataFrame(schema={"date": pl.Date, "item_id": pl.String, "units_sold": pl.Float64})
    with pytest.raises(TypeError) as error:
        _active_items(sales, window_days=28)
    assert str(error.value) == (
        "sales.date deve conter uma data válida para identificar os itens ativos."
    )
