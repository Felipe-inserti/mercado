"""Determinismo da decisão e dos bytes XLSX, com entradas sintéticas reais."""

from collections.abc import Iterator
from pathlib import Path
from time import sleep
from zipfile import ZipFile

import pytest

from motor.experiments.monthly_report import write_monthly_report_workbook
from motor.reporting.purchase_list import (
    GuardrailFiringReport,
    SupplierPurchaseList,
    generate_purchase_list,
    write_all_workbooks,
)
from tests.monthly_report_fixtures import (
    MonthlyReportScenario,
    build_monthly_report_scenario,
    redirected_monthly_sources,
)
from tests.purchase_list_fixtures import (
    PurchaseListScenario,
    build_purchase_list_scenario,
    serialize_purchase_list,
)

PurchaseOutput = tuple[dict[str, SupplierPurchaseList], GuardrailFiringReport]


@pytest.fixture(scope="module")
def purchase_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[PurchaseListScenario, PurchaseOutput, PurchaseOutput]:
    case = build_purchase_list_scenario(tmp_path_factory.mktemp("determinism_purchase"))
    first = generate_purchase_list(case.as_of, base_params=case.params, tables=case.tables)
    second = generate_purchase_list(case.as_of, base_params=case.params, tables=case.tables)
    return case, first, second


@pytest.fixture(scope="module")
def monthly_case(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MonthlyReportScenario]:
    case = build_monthly_report_scenario(tmp_path_factory.mktemp("determinism_monthly"))
    with redirected_monthly_sources(case):
        yield case


def _differing_zip_members(first: Path, second: Path) -> list[str]:
    with ZipFile(first) as a, ZipFile(second) as b:
        return [
            name
            for name in sorted(set(a.namelist()) | set(b.namelist()))
            if name not in a.namelist() or name not in b.namelist() or a.read(name) != b.read(name)
        ]


def test_purchase_list_decisions_are_identical_across_runs(
    purchase_runs: tuple[PurchaseListScenario, PurchaseOutput, PurchaseOutput],
) -> None:
    _, first, second = purchase_runs
    assert first[0]
    assert serialize_purchase_list(*first) == serialize_purchase_list(*second)
    assert first == second


def test_purchase_workbook_bytes_are_identical_across_clock_seconds(
    purchase_runs: tuple[PurchaseListScenario, PurchaseOutput, PurchaseOutput],
    tmp_path: Path,
) -> None:
    case, first, second = purchase_runs
    paths_a = write_all_workbooks(
        first[0],
        as_of=case.as_of,
        out_dir=tmp_path / "first",
        params=case.params,
        suppliers=case.tables.suppliers,
    )
    # Metadados do XLSX têm precisão de segundos; a pausa impede uma aprovação
    # acidental por duas gravações ocorridas no mesmo segundo do relógio.
    sleep(1.1)
    paths_b = write_all_workbooks(
        second[0],
        as_of=case.as_of,
        out_dir=tmp_path / "second",
        params=case.params,
        suppliers=case.tables.suppliers,
    )
    assert sorted(p.name for p in paths_a) == sorted(p.name for p in paths_b)
    assert len(paths_a) == 3
    for a in paths_a:
        b = tmp_path / "second" / a.name
        identical = a.read_bytes() == b.read_bytes()
        assert identical, f"{a.name}: membros diferentes {_differing_zip_members(a, b)}"
        with ZipFile(a) as workbook:
            assert (
                f">{case.as_of.isoformat()}T00:00:00Z<"
                in workbook.read("docProps/core.xml").decode()
            )


def test_monthly_workbook_bytes_are_identical_across_clock_seconds(
    monthly_case: MonthlyReportScenario,
) -> None:
    first = write_monthly_report_workbook(monthly_case.root / "first" / "monthly.xlsx")
    sleep(1.1)
    second = write_monthly_report_workbook(monthly_case.root / "second" / "monthly.xlsx")
    identical = first.read_bytes() == second.read_bytes()
    assert identical, f"Membros diferentes: {_differing_zip_members(first, second)}"
    with ZipFile(first) as workbook:
        assert ">2017-01-10T00:00:00Z<" in workbook.read("docProps/core.xml").decode()
