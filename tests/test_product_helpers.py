"""Utilitários promovidos a produto e compatibilidade dos caminhos antigos."""

from __future__ import annotations

import importlib
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from motor.config import Params
from motor.io.canonical import CanonicalTables, load_canonical_tables
from motor.io.supplier_overrides import (
    cell_suppliers,
    override_supplier_lead_time,
    override_supplier_review_period,
)
from motor.selection_cache import (
    StaleSubsetSelectionError,
    _selection_params_hash,
    load_or_select_subset,
)
from motor.simulator.pair import build_simulator_for_pair, initial_stock_units
from tests.purchase_list_fixtures import build_purchase_list_scenario


def test_legacy_exports_keep_product_implementations() -> None:
    shared = importlib.import_module("motor.experiments.shared")
    runner = importlib.import_module("motor.experiments.run")
    iso = importlib.import_module("motor.experiments.iso_service")
    sensitivity = importlib.import_module("motor.experiments.sensitivity")
    assert shared.build_simulator_for_pair is build_simulator_for_pair
    assert shared.initial_stock_units is initial_stock_units
    assert runner._selection_params_hash is _selection_params_hash
    assert runner.load_or_select_subset is load_or_select_subset
    assert runner.StaleSubsetSelectionError is StaleSubsetSelectionError
    assert iso.CanonicalTables is CanonicalTables
    assert iso.load_canonical_tables is load_canonical_tables
    assert sensitivity.override_supplier_lead_time is override_supplier_lead_time
    assert sensitivity.override_supplier_review_period is override_supplier_review_period
    assert iso.override_supplier_lead_time is override_supplier_lead_time
    assert iso.override_supplier_review_period is override_supplier_review_period
    suppliers = pl.DataFrame({"lead_time_days": [2, 5], "review_period_days": [7, 14]})
    assert_frame_equal(
        iso.cell_suppliers(suppliers),
        cell_suppliers(
            suppliers,
            lead_time_days=iso.CELL_LEAD_TIME_DAYS,
            review_period_days=iso.CELL_REVIEW_PERIOD_DAYS,
        ),
    )
    assert_frame_equal(
        iso.cell_suppliers(suppliers, lead_time_days=3, review_period_days=7),
        cell_suppliers(suppliers, lead_time_days=3, review_period_days=7),
    )


@pytest.mark.parametrize(("lead", "review"), [(None, None), (4, None), (None, 9), (4, 9)])
def test_supplier_overrides_are_independent_and_preserve_input(
    lead: int | None,
    review: int | None,
) -> None:
    suppliers = pl.DataFrame(
        {"supplier_id": ["A", "B"], "lead_time_days": [2, 5], "review_period_days": [7, 14]}
    )
    original = suppliers.clone()
    result = cell_suppliers(suppliers, lead_time_days=lead, review_period_days=review)
    assert result["lead_time_days"].to_list() == ([2, 5] if lead is None else [lead, lead])
    assert result["review_period_days"].to_list() == (
        [7, 14] if review is None else [review, review]
    )
    assert result["supplier_id"].to_list() == ["A", "B"]
    assert_frame_equal(suppliers, original)


def test_canonical_loader_reads_synthetic_tables_and_explicit_cache(tmp_path: Path) -> None:
    scenario = build_purchase_list_scenario(tmp_path)
    expected = scenario.tables
    expected.sales.collect().write_parquet(tmp_path / "sales.parquet")
    expected.items.write_parquet(tmp_path / "items.parquet")
    expected.suppliers.write_parquet(tmp_path / "suppliers.parquet")
    expected.stock.write_parquet(tmp_path / "stock.parquet")
    payload = scenario.params.model_dump()
    payload["data"]["canonical_dir"] = tmp_path
    params = Params.model_validate(payload)
    actual = load_canonical_tables(params, subset_cache_path=expected.subset_cache_path)
    assert_frame_equal(actual.sales.collect(), expected.sales.collect())
    assert_frame_equal(actual.items, expected.items)
    assert_frame_equal(actual.suppliers, expected.suppliers)
    assert_frame_equal(actual.stock, expected.stock)
    assert actual.subset_cache_path == expected.subset_cache_path
