"""Configuração explícita, prazos por fornecedor e notas reais do Excel."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile

import polars as pl
import pytest
from pydantic import ValidationError

import motor.reporting.purchase_list as purchase_module
from motor.config import Params, PurchaseListParams, load_params
from motor.forecast.statistical import StatisticalForecaster
from motor.policy.basestock import BasestockPolicy
from motor.reporting.purchase_list import (
    _ItemDecisions,
    generate_purchase_list,
    write_all_workbooks,
)
from tests.purchase_list_fixtures import (
    PARAMS_PATH,
    build_purchase_list_scenario,
    build_supplier_timing_scenario,
)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alpha", 0.0),
        ("alpha", 1.0),
        ("alpha", -0.1),
        ("alpha", 1.1),
        ("lead_time_days_override", 0),
        ("lead_time_days_override", -1),
        ("review_period_days_override", 0),
        ("review_period_days_override", -1),
        ("lead_time_days_override", 1.5),
        ("review_period_days_override", 1.5),
        ("budget_period_days", 0),
        ("budget_period_days", -1),
        ("budget_period_days", 1.5),
    ],
)
def test_purchase_list_config_rejects_invalid_values(field: str, value: float) -> None:
    payload = load_params(PARAMS_PATH).purchase_list.model_dump()
    payload[field] = value
    with pytest.raises(ValidationError, match=field) as error:
        PurchaseListParams.model_validate(payload)
    assert field in str(error.value)


def _workbook_notes(path: Path) -> str:
    """Lê as células de Notas do XLSX, sem dependência adicional de Excel."""
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as workbook:
        strings_xml = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
        strings = ["".join(node.itertext()) for node in strings_xml.findall("m:si", namespace)]
        sheet = ElementTree.fromstring(workbook.read("xl/worksheets/sheet3.xml"))
        indices = sheet.findall(".//m:c[@t='s']/m:v", namespace)
        return "\n".join(strings[int(node.text or "0")] for node in indices)


def test_null_overrides_use_each_supplier_risk_window_and_excel_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_supplier_timing_scenario(tmp_path)
    expected_timings = {
        "SUP-GROCERY": (2, 7),
        "SUP-PRODUCE": (5, 14),
        "SUP-EGGS": (3, 7),
        "SUP-CLOSED": (4, 7),
    }
    real_decide_all = purchase_module._decide_all_items
    real_decide_item = purchase_module._decide_item
    real_predict = StatisticalForecaster.predict_quantiles
    real_policy = BasestockPolicy
    current_rows: Iterator[dict[str, Any]] = iter(())
    current_horizon = 0
    observed: dict[str, list[int]] = {}
    forecasts: Counter[int] = Counter()
    policies: Counter[int] = Counter()

    def record_all(item_supplier: pl.DataFrame, **kwargs: Any) -> _ItemDecisions:
        nonlocal current_rows
        current_rows = iter(item_supplier.iter_rows(named=True))
        return real_decide_all(item_supplier, **kwargs)

    def record_item(**kwargs: Any) -> tuple[float, float, float, float, float]:
        nonlocal current_horizon
        row = next(current_rows)
        supplier_id = row["supplier_id"]
        lead, review = expected_timings[supplier_id]
        assert (kwargs["lead_time_days"], kwargs["review_period_days"]) == (lead, review)
        current_horizon = lead + review
        observed.setdefault(supplier_id, []).append(current_horizon)
        return real_decide_item(**kwargs)

    def record_predict(
        forecaster: StatisticalForecaster,
        as_of: date,
        horizon: int,
        quantiles: list[float],
    ) -> pl.DataFrame:
        assert horizon == current_horizon
        assert quantiles == [case.params.purchase_list.alpha]
        forecasts[horizon] += 1
        return real_predict(forecaster, as_of, horizon, quantiles)

    def record_policy(*, alpha: float, expected_window_days: int) -> BasestockPolicy:
        assert expected_window_days == current_horizon
        assert alpha == case.params.purchase_list.alpha
        policies[expected_window_days] += 1
        return real_policy(alpha=alpha, expected_window_days=expected_window_days)

    monkeypatch.setattr(purchase_module, "_decide_all_items", record_all)
    monkeypatch.setattr(purchase_module, "_decide_item", record_item)
    monkeypatch.setattr(StatisticalForecaster, "predict_quantiles", record_predict)
    monkeypatch.setattr(purchase_module, "BasestockPolicy", record_policy)
    results, _ = generate_purchase_list(case.as_of, base_params=case.params, tables=case.tables)
    assert observed == {
        "SUP-GROCERY": [9] * 5,
        "SUP-PRODUCE": [19] * 3,
        "SUP-EGGS": [10] * 2,
        "SUP-CLOSED": [11] * 2,
    }
    assert policies == Counter({9: 5, 19: 3, 10: 2, 11: 2})
    assert all(forecasts[horizon] > policies[horizon] for horizon in policies)
    paths = write_all_workbooks(
        results,
        as_of=case.as_of,
        out_dir=tmp_path / "xlsx",
        params=case.params,
        suppliers=case.tables.suppliers,
    )
    assert {path.stem for path in paths} == {"SUP-GROCERY", "SUP-PRODUCE", "SUP-EGGS"}
    for path in paths:
        notes = _workbook_notes(path)
        lead, review = expected_timings[path.stem]
        assert f"lead_time={lead} dias (cadastro do fornecedor)" in notes
        assert f"review_period={review} dias (cadastro do fornecedor)" in notes
        assert f"janela de risco={lead + review} dias" in notes
        assert f"alpha={case.params.purchase_list.alpha:g}" in notes


def test_excel_notes_use_configured_overrides_and_alpha(tmp_path: Path) -> None:
    case = build_purchase_list_scenario(tmp_path)
    payload = case.params.model_dump()
    payload["purchase_list"].update(
        alpha=0.73,
        lead_time_days_override=4,
        review_period_days_override=7,
    )
    params = Params.model_validate(payload)
    results, _ = generate_purchase_list(case.as_of, base_params=params, tables=case.tables)
    paths = write_all_workbooks(
        results,
        as_of=case.as_of,
        out_dir=tmp_path / "xlsx",
        params=params,
        suppliers=case.tables.suppliers,
    )
    assert paths
    for path in paths:
        notes = _workbook_notes(path)
        assert "alpha=0.73" in notes
        assert "lead_time=4 dias (override da lista)" in notes
        assert "review_period=7 dias (override da lista)" in notes
        assert "janela de risco=11 dias" in notes
    assert params.model.quantiles == case.params.model.quantiles
    assert params.economics == case.params.economics


def test_budget_period_is_independent_of_supplier_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_purchase_list_scenario(tmp_path)
    payload = case.params.model_dump()
    payload["purchase_list"]["budget_period_days"] = 7
    payload["guardrails"]["weekly_budget_rs"] = 3500.0
    params = Params.model_validate(payload)
    real_finalize = purchase_module._finalize_with_cash_constraint
    budgets: list[float] = []

    def record_finalize(*args: Any, **kwargs: Any) -> Any:
        budgets.append(kwargs["budget_rs"])
        return real_finalize(*args, **kwargs)

    monkeypatch.setattr(purchase_module, "_finalize_with_cash_constraint", record_finalize)
    results, report = generate_purchase_list(case.as_of, base_params=params, tables=case.tables)
    assert budgets == [3500.0]
    assert params.purchase_list.review_period_days_override == 14
    assert sum(r.value_rs for s in results.values() for r in (*s.main, *s.exceptions)) <= 3500.0
    assert report.counts[purchase_module.GuardrailReason.RESTRICAO_DE_CAIXA] > 0
