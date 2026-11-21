"""Caracteriza o gerador atual antes das refatorações da Sprint 25.

O golden é lido, nunca atualizado por pytest. Asserções de comportamento
complementam a comparação integral e impedem um cenário vazio de passar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from motor.config import Params, load_params
from motor.io.contracts import (
    ITEMS_PRIMARY_KEY,
    SALES_PRIMARY_KEY,
    STOCK_PRIMARY_KEY,
    SUPPLIERS_PRIMARY_KEY,
    Item,
    Sale,
    Stock,
    Supplier,
    validate_referential_integrity,
    validate_supplier_order_cadence,
    validate_table,
)
from motor.policy.guardrails import GuardrailReason
from motor.policy.supplier import OrderOutcome
from motor.reporting.purchase_list import (
    GuardrailFiringReport,
    PurchaseListRow,
    SupplierPurchaseList,
    generate_purchase_list,
)
from motor.selection_cache import _selection_params_hash, load_or_select_subset
from tests.purchase_list_fixtures import (
    PARAMS_PATH,
    PurchaseListScenario,
    build_purchase_list_scenario,
    characterization_cases,
    serialize_purchase_list,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "purchase_list_synthetic.json"
PurchaseListOutput = tuple[dict[str, SupplierPurchaseList], GuardrailFiringReport]


@pytest.fixture(scope="module")
def scenarios(tmp_path_factory: pytest.TempPathFactory) -> dict[str, PurchaseListScenario]:
    return characterization_cases(
        build_purchase_list_scenario(tmp_path_factory.mktemp("purchase_list"))
    )


@pytest.fixture(scope="module")
def outputs(scenarios: dict[str, PurchaseListScenario]) -> dict[str, PurchaseListOutput]:
    """Roda cada cenário uma vez, com os componentes reais, sem mocks."""
    return {
        name: generate_purchase_list(case.as_of, base_params=case.params, tables=case.tables)
        for name, case in scenarios.items()
    }


def _rows(output: PurchaseListOutput) -> dict[str, PurchaseListRow]:
    return {
        row.item_id: row
        for supplier in output[0].values()
        for row in (*supplier.main, *supplier.exceptions)
    }


def _has_note(row: PurchaseListRow, text: str) -> bool:
    return any(text in detail for detail in row.adjustments)


def test_fixture_has_valid_contracts_history_and_cache(
    scenarios: dict[str, PurchaseListScenario],
) -> None:
    for case in scenarios.values():
        tables = case.tables
        sales = tables.sales.collect()
        validate_table(sales, Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)
        validate_table(tables.items, Item, table_name="items", primary_key=ITEMS_PRIMARY_KEY)
        validate_table(
            tables.suppliers, Supplier, table_name="suppliers", primary_key=SUPPLIERS_PRIMARY_KEY
        )
        validate_table(tables.stock, Stock, table_name="stock", primary_key=STOCK_PRIMARY_KEY)
        validate_referential_integrity(
            items=tables.items, suppliers=tables.suppliers, sales=sales, stock=tables.stock
        )
        validate_supplier_order_cadence(tables.suppliers)
        assert tables.items.height == 12
        assert tables.suppliers.height == 4
        assert sales.height == 12 * 470
        assert sales["date"].max() < case.as_of
        simulated_days = (case.as_of - case.params.simulation.start_date).days
        assert simulated_days > case.params.simulation.warmup_days
        history_days = (case.params.simulation.start_date - sales["date"].min()).days
        assert history_days >= case.params.subset_selection.min_weeks_of_history * 7
        assert history_days > case.params.forecast_statistical.min_residual_samples
        cached_bytes = tables.subset_cache_path.read_bytes()
        cached = json.loads(cached_bytes)
        assert cached["params_hash"] == _selection_params_hash(case.params)
        selected = load_or_select_subset(
            tables.sales,
            tables.items,
            tables.suppliers,
            tables.stock,
            case.params,
            cache_path=tables.subset_cache_path,
        )
        assert selected.item_ids == tuple(sorted(tables.items["item_id"].to_list()))
        assert selected.store_id == case.params.subset_selection.store_id
        assert tables.subset_cache_path.read_bytes() == cached_bytes


@pytest.mark.parametrize("name", ["default", "cash_limited", "cash_below_floors", "minimum_filled"])
def test_generate_purchase_list_matches_complete_golden(
    name: str, scenarios: dict[str, PurchaseListScenario], outputs: dict[str, PurchaseListOutput]
) -> None:
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    actual: dict[str, Any] = serialize_purchase_list(*outputs[name])
    assert expected["as_of"] == scenarios[name].as_of.isoformat()
    assert actual == expected["scenarios"][name]


def test_issued_order_has_main_rows_and_exceptions(
    outputs: dict[str, PurchaseListOutput],
) -> None:
    results, _ = outputs["default"]
    grocery = results["SUP-GROCERY"]
    assert grocery.outcome == OrderOutcome.PEDIDO_EMITIDO
    assert [row.item_id for row in grocery.main] == ["G-DORMANT", "G-REGULAR", "G-SMALL"]
    assert {row.item_id for row in grocery.exceptions} == {"G-NEW", "G-SURGE"}
    assert all(row.is_exception for row in grocery.exceptions)
    regular = _rows(outputs["default"])["G-REGULAR"]
    assert regular.quantity_units == 72.0
    assert regular.quantity_packs == 6.0
    assert regular.value_rs == pytest.approx(72.0 * 8.2)
    assert _has_note(regular, "arredondado para cima (fardo)")


def test_supplier_outside_calendar_is_omitted(
    scenarios: dict[str, PurchaseListScenario], outputs: dict[str, PurchaseListOutput]
) -> None:
    for name, case in scenarios.items():
        closed = next(
            row
            for row in case.tables.suppliers.iter_rows(named=True)
            if row["supplier_id"] == "SUP-CLOSED"
        )
        assert case.as_of.isoweekday() not in closed["order_days"]
        assert set(outputs[name][0]) == {"SUP-GROCERY", "SUP-PRODUCE", "SUP-EGGS"}
        assert {"B-ONE", "B-TWO"}.isdisjoint(_rows(outputs[name]))


def test_new_items_use_median_and_no_demand_has_null_coverage(
    outputs: dict[str, PurchaseListOutput],
) -> None:
    rows = _rows(outputs["default"])
    # Mediana de [0, 70, 35, 286,78...] = 52,5; fardo 12 => 60.
    new_grocery = rows["G-NEW"]
    assert new_grocery.quantity_units == 60.0
    assert _has_note(new_grocery, "mediana da categoria (52.50 unidades)")
    # Hortifruti: mediana das sugestões pós-teto (70 + 298,55)/2 = 184,275;
    # arredondada para cima na unidade => 185, mesmo sem venda do item novo.
    never_sold = rows["P-NEVER"]
    assert never_sold.quantity_units == 185.0
    assert _has_note(never_sold, "que sugeriria 0.00 unidades")
    assert never_sold.coverage_days_after_order is None
    assert rows["G-DORMANT"].coverage_days_after_order is None
    assert rows["G-DORMANT"].quantity_units == 0.0
    assert outputs["default"][1].counts[GuardrailReason.ITEM_NOVO] == 2


def test_variation_is_flagged_and_coverage_cap_reduces_quantity(
    outputs: dict[str, PurchaseListOutput],
) -> None:
    rows = _rows(outputs["default"])
    surge = rows["G-SURGE"]
    assert _has_note(surge, "acima do limite de 2x")
    assert _has_note(surge, "quantidade NÃO alterada")
    assert surge.quantity_units == 288.0  # Só arredondamento após sinalizar 286,78.
    trend = rows["P-TREND"]
    assert _has_note(trend, "cortado de 350.00 para 298.55 unidades")
    assert trend.quantity_units == 299.0  # Teto seguido do arredondamento de fardo.
    assert _has_note(trend, "teto efetivo de 21 dias")
    assert _has_note(rows["P-REGULAR"], "ciclo de compra incompatível com a família")
    counts = outputs["default"][1].counts
    assert counts[GuardrailReason.LIMITE_DE_VARIACAO] == 1
    assert counts[GuardrailReason.TETO_DE_COBERTURA] == 4


def test_unreachable_minimum_defers_order_and_reachable_minimum_is_filled(
    outputs: dict[str, PurchaseListOutput],
) -> None:
    deferred = outputs["default"][0]["SUP-EGGS"]
    assert deferred.outcome == OrderOutcome.MINIMO_INATINGIVEL
    assert not deferred.main
    assert len(deferred.exceptions) == 2
    assert all(row.quantity_units == 0.0 and row.value_rs == 0.0 for row in deferred.exceptions)
    assert all(_has_note(row, "pedido adiado") for row in deferred.exceptions)
    filled = outputs["minimum_filled"][0]["SUP-EGGS"]
    assert filled.outcome == OrderOutcome.PEDIDO_EMITIDO
    assert sum(row.value_rs for row in (*filled.main, *filled.exceptions)) >= filled.min_order_value
    assert any(_has_note(row, "aumentado para bater pedido mínimo") for row in filled.exceptions)
    assert all(row.quantity_packs.is_integer() for row in (*filled.main, *filled.exceptions))


@pytest.mark.parametrize("name", ["cash_limited", "cash_below_floors"])
def test_cash_constraint_cuts_quantity_and_keeps_audit_trail(
    name: str, scenarios: dict[str, PurchaseListScenario], outputs: dict[str, PurchaseListOutput]
) -> None:
    original = _rows(outputs["default"])
    final = _rows(outputs[name])
    cuts = [row for row in final.values() if _has_note(row, "reduzido por restrição de caixa")]
    assert cuts
    assert all(row.quantity_units == 0.0 and row.value_rs == 0.0 for row in cuts)
    assert all(row.is_exception and original[row.item_id].quantity_units > 0.0 for row in cuts)
    params = scenarios[name].params
    budget = params.guardrails.weekly_budget_rs * params.purchase_list.budget_period_days / 7
    assert sum(row.value_rs for row in final.values()) <= budget
    assert outputs[name][1].counts[GuardrailReason.RESTRICAO_DE_CAIXA] >= len(cuts)
    assert outputs["default"][1].counts[GuardrailReason.RESTRICAO_DE_CAIXA] == 0
    for case in scenarios.values():
        # O objeto de entrada respeita inclusive os validadores entre seções.
        assert Params.model_validate(case.params.model_dump()) == case.params
        payload = case.params.model_dump()
        production = load_params(PARAMS_PATH)
        payload["guardrails"]["weekly_budget_rs"] = production.guardrails.weekly_budget_rs
        assert Params.model_validate(payload) == production


def test_category_floor_and_insufficient_budget_alert(
    scenarios: dict[str, PurchaseListScenario], outputs: dict[str, PurchaseListOutput]
) -> None:
    normal = _rows(outputs["default"])
    limited = _rows(outputs["cash_limited"])
    assert outputs["cash_limited"][1].category_floor_alert is None
    fraction = scenarios["cash_limited"].params.guardrails.cash_constraint_category_floor_fraction
    for category in {row.category for row in normal.values()}:
        before = sum(row.value_rs for row in normal.values() if row.category == category)
        after = sum(row.value_rs for row in limited.values() if row.category == category)
        assert after >= fraction * before
    assert any(_has_note(row, "protegido pelo piso de categoria") for row in limited.values())
    alert = outputs["cash_below_floors"][1].category_floor_alert
    assert alert is not None
    assert alert.total_floor_rs == pytest.approx(5313.6)
    assert alert.budget_rs == 4000.0
    assert alert.shortfall_rs == pytest.approx(alert.total_floor_rs - alert.budget_rs)
