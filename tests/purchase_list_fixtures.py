"""Cenário sintético da caracterização ponta a ponta da Sprint 25.

Quatro fornecedores e doze itens fictícios, com histórico diário completo.
Só o orçamento do cenário de estresse diverge do `params.yaml`, sempre por
validação de `Params`. O cache pequeno evita selecionar os 150-300 itens
exigidos para o Favorita; previsão, simulação e regras rodam de verdade.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from motor.config import Params, load_params
from motor.io.canonical import CanonicalTables
from motor.io.contracts import (
    Item,
    Sale,
    Stock,
    Supplier,
    UnitOfSale,
    expected_polars_schema,
)
from motor.reporting.purchase_list import GuardrailFiringReport, SupplierPurchaseList
from motor.selection_cache import _selection_params_hash

PARAMS_PATH = Path(__file__).resolve().parents[1] / "config" / "params.yaml"


@dataclass(frozen=True)
class PurchaseListScenario:
    """Entrada completa de uma execução, independente de dados locais."""

    params: Params
    tables: CanonicalTables
    as_of: date


def _daily_units(item_id: str, day: date, *, first_day: date, as_of: date) -> float:
    """Perfis determinísticos: nível estável, alta, lançamento e ausência de venda."""
    if item_id == "G-SURGE":
        return 40.0 if day >= as_of - timedelta(days=14) else 1.0
    if item_id == "G-NEW":
        return 3.0 if day >= as_of - timedelta(days=14) else 0.0
    if item_id == "G-DORMANT":
        return 0.0 if day >= as_of - timedelta(days=28) else 1.0
    if item_id == "P-TREND":
        return 1.0 + (day - first_day).days / 10
    if item_id == "P-NEVER":
        return 0.0
    return {
        "G-REGULAR": 10.0,
        "G-SMALL": 5.0,
        "P-REGULAR": 10.0,
        "E-ONE": 1.0,
        "E-TWO": 2.0,
        "B-ONE": 4.0,
        "B-TWO": 6.0,
    }[item_id]


def build_purchase_list_scenario(tmp_path: Path) -> PurchaseListScenario:
    """Monta tabelas canônicas tipadas e grava somente o cache em `tmp_path`."""
    params = load_params(PARAMS_PATH)
    # Warmup inteiro antes da decisão; segunda-feira, oito dias após a revisão
    # anterior, permite observar estoque e pedidos já recebidos de fato.
    as_of = params.simulation.start_date + timedelta(days=params.simulation.warmup_days + 16)
    first_day = params.simulation.start_date - timedelta(
        weeks=params.subset_selection.min_weeks_of_history
    )
    supplier_categories = {
        "SUP-GROCERY": ("GROCERY I", ("G-REGULAR", "G-SMALL", "G-SURGE", "G-NEW", "G-DORMANT")),
        "SUP-PRODUCE": ("PRODUCE", ("P-REGULAR", "P-TREND", "P-NEVER")),
        "SUP-EGGS": ("EGGS", ("E-ONE", "E-TWO")),
        "SUP-CLOSED": ("BEVERAGES", ("B-ONE", "B-TWO")),
    }
    items: list[dict[str, Any]] = []
    suppliers: list[dict[str, Any]] = []
    sales: list[dict[str, Any]] = []
    for supplier_id, (category, item_ids) in supplier_categories.items():
        suppliers.append(
            Supplier(
                supplier_id=supplier_id,
                lead_time_days=params.supplier_assumptions.default_lead_time_days,
                review_period_days=params.supplier_assumptions.default_review_period_days,
                order_days=[2] if supplier_id == "SUP-CLOSED" else [1, 2, 3, 4, 5],
                min_order_value=0.0,
                min_order_units=0.0,
            ).model_dump()
        )
        price = params.economics.uniform_unit_price
        margin = params.economics.category_margin_pct[category]
        for item_id in item_ids:
            items.append(
                Item(
                    item_id=item_id,
                    category=category,
                    supplier_id=supplier_id,
                    unit_of_sale=UnitOfSale.UNIDADE,
                    pack_multiple=1.0,
                    is_perishable=category in {"PRODUCE", "EGGS"},
                    cost=price * (1.0 - margin),
                    price_ref=price,
                    economics_origin="fixture sintética Sprint 25; margem do params.yaml",
                ).model_dump()
            )
            for offset in range((as_of - first_day).days):
                day = first_day + timedelta(days=offset)
                sales.append(
                    Sale(
                        store_id=params.subset_selection.store_id,
                        item_id=item_id,
                        date=day,
                        units_sold=_daily_units(item_id, day, first_day=first_day, as_of=as_of),
                        units_returned=0.0,
                        on_promo=False,
                        price=price,
                        is_operating_day=True,
                        is_anomaly=False,
                    ).model_dump()
                )
    items_df = pl.DataFrame(items, schema=expected_polars_schema(Item))
    cache_path = tmp_path / "subset_selection.json"
    cache_path.write_text(
        json.dumps(
            {
                "params_hash": _selection_params_hash(params),
                "store_id": params.subset_selection.store_id,
                "item_ids": sorted(items_df["item_id"].to_list()),
                "funnel": [{"stage": "fixture sintética explícita", "n_items": items_df.height}],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return PurchaseListScenario(
        params=params,
        as_of=as_of,
        tables=CanonicalTables(
            sales=pl.DataFrame(sales, schema=expected_polars_schema(Sale)).lazy(),
            items=items_df,
            suppliers=pl.DataFrame(suppliers, schema=expected_polars_schema(Supplier)),
            stock=pl.DataFrame(schema=expected_polars_schema(Stock)),
            subset_cache_path=cache_path,
        ),
    )


def params_with_budget(params: Params, weekly_budget_rs: float) -> Params:
    """Altera só o orçamento em memória e executa todos os validadores."""
    payload = params.model_dump()
    payload["guardrails"]["weekly_budget_rs"] = weekly_budget_rs
    return Params.model_validate(payload)


def build_supplier_timing_scenario(tmp_path: Path) -> PurchaseListScenario:
    """Variante independente do golden, com prazos diferentes e overrides nulos."""
    scenario = build_purchase_list_scenario(tmp_path)
    timings = {
        "SUP-GROCERY": (2, 7),
        "SUP-PRODUCE": (5, 14),
        "SUP-EGGS": (3, 7),
        "SUP-CLOSED": (4, 7),
    }
    rows = []
    for row in scenario.tables.suppliers.iter_rows(named=True):
        lead, review = timings[row["supplier_id"]]
        rows.append({**row, "lead_time_days": lead, "review_period_days": review})
    suppliers = pl.DataFrame(rows, schema=expected_polars_schema(Supplier))
    payload = scenario.params.model_dump()
    payload["purchase_list"]["lead_time_days_override"] = None
    payload["purchase_list"]["review_period_days_override"] = None
    return replace(
        scenario,
        params=Params.model_validate(payload),
        tables=replace(scenario.tables, suppliers=suppliers),
    )


def characterization_cases(scenario: PurchaseListScenario) -> dict[str, PurchaseListScenario]:
    """Exercita orçamento normal, dois estresses e preenchimento viável de mínimo."""
    # Valores apenas sintéticos: R$ 7.000/ciclo permite os pisos; R$ 4.000
    # não cobre sua soma. Nenhuma premissa do arquivo de produção é alterada.
    minimum_sales = scenario.tables.sales.with_columns(
        pl.when(pl.col("item_id").is_in(["E-ONE", "E-TWO"]))
        .then(13.0)
        .otherwise(pl.col("units_sold"))
        .alias("units_sold")
    )
    return {
        "default": scenario,
        "cash_limited": replace(scenario, params=params_with_budget(scenario.params, 3500.0)),
        "cash_below_floors": replace(scenario, params=params_with_budget(scenario.params, 2000.0)),
        "minimum_filled": replace(scenario, tables=replace(scenario.tables, sales=minimum_sales)),
    }


def serialize_purchase_list(
    results: dict[str, SupplierPurchaseList], report: GuardrailFiringReport
) -> dict[str, Any]:
    """Preserva todos os campos, ordena IDs/chaves e arredonda floats a seis casas."""
    suppliers = []
    for supplier_id in sorted(results):
        supplier = asdict(results[supplier_id])
        for section in ("main", "exceptions"):
            supplier[section] = sorted(supplier[section], key=lambda row: row["item_id"])
        suppliers.append(supplier)
    # O round passa pelos números, inclusive em listas, tuplas e alertas;
    # o JSON normaliza enums str e tuplas sem descartar textos de auditoria.
    serialized = json.dumps({"suppliers": suppliers, "report": asdict(report)}, sort_keys=True)
    return json.loads(serialized, parse_float=lambda value: round(float(value), 6))
