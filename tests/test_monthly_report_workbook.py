"""Verifica o que o comprador lê: células, totais, notas, ordenação e abas."""

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from motor.config import load_params
from motor.experiments import monthly_report as report
from tests.monthly_report_fixtures import (
    MonthlyReportScenario,
    build_monthly_report_scenario,
    redirected_monthly_sources,
)
from tests.xlsx_assertions import WorkbookCells, read_workbook_cells


@pytest.fixture(scope="module")
def monthly_case(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MonthlyReportScenario]:
    case = build_monthly_report_scenario(tmp_path_factory.mktemp("monthly_workbook"))
    with redirected_monthly_sources(case):
        yield case


@pytest.fixture(scope="module")
def workbook(monthly_case: MonthlyReportScenario) -> tuple[Path, WorkbookCells]:
    path = report.write_monthly_report_workbook(monthly_case.root / "report.xlsx")
    return path, read_workbook_cells(path)


def test_synthetic_sources_produce_exact_totals_and_ranking(
    monthly_case: MonthlyReportScenario,
) -> None:
    data = report._build_report_data()
    assert data.n_months == 2.0
    assert data.motor.n_items == 3
    assert data.motor.margem_realizada_rs == 950.0
    assert data.motor.ruptura_rs == 150.0
    assert data.recalibrado.margem_realizada_rs == 900.0
    assert data.recalibrado.ruptura_rs == 200.0
    assert data.andar1_ruptura_evitada == {"calibrado_lt3_rp7": 350.0, "calibrado_lt5_rp7": 250.0}
    assert data.andar1_aumento_capital == {"calibrado_lt3_rp7": 500.0, "calibrado_lt5_rp7": 350.0}
    assert data.andar2_capital_liberado == 100.0
    assert data.andar2_ruptura_evitada == 50.0
    ranking = report.itens_sangrando_margem(top_n=2)
    assert ranking["item_id"].to_list() == ["A", "B"]
    assert ranking["ruptura_rs"].to_list() == [100.0, 40.0]
    assert ranking["pct_margem_potencial_perdida"].to_list() == [0.25, 0.2]
    assert str(monthly_case.root) in str(report.PARAMS_PATH)


def test_workbook_has_all_seven_sheets_in_the_expected_order(
    workbook: tuple[Path, WorkbookCells],
) -> None:
    assert list(workbook[1]) == [
        "Resumo executivo",
        "Andar 1 - Correção de cadastro",
        "Andar 2 - Refinamento do modelo",
        "Itens sangrando margem",
        "Taxa de aceitação",
        "Premissas",
        "Limitações",
    ]


def test_executive_summary_reports_monthly_values_and_notes(
    workbook: tuple[Path, WorkbookCells],
) -> None:
    cells = workbook[1]["Resumo executivo"]
    assert cells["A1"] == "RELATÓRIO MENSAL EM R$ -- MOTOR DE DECISÃO DE COMPRA"
    assert "60 dias -- equivalente a 2.00 meses" in str(cells["A2"])
    assert {
        ref: cells[ref] for ref in ("B5", "B7", "B8", "B9", "B12", "B13", "B14", "B15", "B16")
    } == {
        "B5": 175.0,
        "B7": 0.6,
        "B8": 0.95,
        "B9": 250.0,
        "B12": 50.0,
        "B13": 0.125,
        "B14": 4.0,
        "B15": 4.5,
        "B16": 25.0,
    }
    assert cells["B6"] == "122.50 a 227.50"
    assert cells["B18"] == "R$ 0,00 -- ver aba Limitações"
    assert cells["B19"] == "n/d -- ver aba Taxa de aceitação"


def test_first_floor_shows_both_stale_cases_and_sensitivity(
    workbook: tuple[Path, WorkbookCells],
) -> None:
    cells = workbook[1]["Andar 1 - Correção de cadastro"]
    assert cells["B1"] == "desatualizado (calibrado_lt3_rp7)"
    assert cells["C1"] == "desatualizado (calibrado_lt5_rp7)"
    assert [cells[f"{col}3"] for col in "BCD"] == [550.0, 450.0, 200.0]
    assert [cells[f"{col}4"] for col in "BCD"] == [300.0, 450.0, 800.0]
    assert cells["B8"] == 350.0
    assert cells["B9"] == 250.0
    assert cells["B12"] == 500.0
    assert cells["B13"] == 350.0
    assert "Recalibrar EXIGE mais capital empregado" in str(cells["A15"])
    assert [cells[f"B{row}"] for row in (18, 19, 20)] == [245.0, 350.0, 455.0]
    assert "margem -30%" in str(cells["A18"])
    assert "margem medida" in str(cells["A19"])
    assert "margem +30%" in str(cells["A20"])


def test_second_floor_separates_capital_and_margin_gains(
    workbook: tuple[Path, WorkbookCells],
) -> None:
    cells = workbook[1]["Andar 2 - Refinamento do modelo"]
    assert cells["B3"] == 200.0 and cells["C3"] == 150.0
    assert cells["B4"] == 800.0 and cells["C4"] == 700.0
    assert cells["B6"] == 900.0 and cells["C6"] == 950.0
    assert cells["B8"] == 100.0
    assert cells["B9"] == 0.125
    assert cells["B10"] == 0.125
    assert "R$ 50.00 no período" in str(cells["A12"])


def test_item_sheet_sorts_shortage_and_preserves_units_values_and_note(
    workbook: tuple[Path, WorkbookCells],
) -> None:
    cells = workbook[1]["Itens sangrando margem"]
    assert cells["A1"] == "código" and cells["H1"] == "ruptura (R$)"
    assert [cells[f"A{row}"] for row in (2, 3, 4)] == ["A", "B", "C"]
    assert cells["C3"] == "kg"
    assert [cells[f"H{row}"] for row in (2, 3, 4)] == [100.0, 40.0, 10.0]
    assert [cells[f"I{row}"] for row in (2, 3, 4)] == [0.25, 0.2, 0.02]
    assert cells["G2"] == 300.0 and cells["F2"] == 0.3
    assert "Top 20 itens por ruptura_rs ABSOLUTA" in str(cells["A6"])


def test_assumptions_acceptance_and_limitations_keep_explanatory_text(
    monthly_case: MonthlyReportScenario,
    workbook: tuple[Path, WorkbookCells],
) -> None:
    sheets = workbook[1]
    assumptions = sheets["Premissas"]
    assert assumptions["B2"] == "7" and assumptions["B3"] == "14"
    assert assumptions["B4"] == 0.15 and assumptions["B5"] == 10.0
    assert assumptions["B7"] == "30 dias"
    assert assumptions["B8"] == "não modelada"
    assert assumptions["B9"] == "fora de escopo deste relatório"
    params = load_params(monthly_case.params_path)
    categories = sorted(params.economics.category_margin_pct)
    for row, category in enumerate(categories, start=12):
        assert assumptions[f"A{row}"] == f"  {category}"
        assert assumptions[f"B{row}"] == params.economics.category_margin_pct[category]
    default_row = 12 + len(categories)
    assert assumptions[f"B{default_row}"] == params.economics.default_margin_pct
    assert "default_margin_pct" in str(assumptions[f"C{default_row}"])
    assert "n/d nesta etapa" in str(sheets["Taxa de aceitação"]["A2"])
    assert "MODO SOMBRA" in str(sheets["Taxa de aceitação"]["A3"])
    assert "NÃO é observada" in str(sheets["Limitações"]["A2"])
    assert "mês-calendário real" in str(sheets["Limitações"]["A6"])


def test_monthly_cli_uses_only_synthetic_default_relative_paths(
    monthly_case: MonthlyReportScenario,
    workbook: tuple[Path, WorkbookCells],
) -> None:
    output = monthly_case.root / "cli" / "monthly.xlsx"
    result = subprocess.run(
        [sys.executable, "-m", "motor.experiments.monthly_report", "--output", str(output)],
        cwd=monthly_case.root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"relatório salvo em {output}"
    assert output.read_bytes() == workbook[0].read_bytes()
