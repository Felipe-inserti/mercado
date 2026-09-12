"""Testes de `motor.experiments.iso_service` (Sprint 17, Etapa 3.13) -- só
as funções puras (`build_arm2_single_alpha_params`, `build_arm3_alpha_params`,
`point_summary`, `compute_item_decomposition`). Rodar `run_arm2_alpha_point`/
`run_arm3_alpha_point` de verdade exercita o pipeline inteiro (caro demais
para teste automatizado) -- exercitados manualmente via CLI (`--run-point`),
não aqui, mesmo espírito de `tests/test_sensitivity.py`.
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise
from pathlib import Path

import polars as pl
import pytest

from motor.config import load_params
from motor.experiments.iso_service import (
    ARM2_ALPHA_GRID,
    ARM3_ALPHA_GRID,
    CELL_ERP_FACTOR,
    CELL_ERP_MIN_ORDER_UNITS,
    CELL_LEAD_TIME_DAYS,
    CELL_REVIEW_PERIOD_DAYS,
    build_arm2_single_alpha_params,
    build_arm3_alpha_params,
    compute_item_decomposition,
    consolidate_points,
    point_summary,
)
from motor.metrics.financial import PortfolioFinancialMetrics

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"


@pytest.fixture(scope="module")
def base_params():
    return load_params(PARAMS_PATH)


def test_build_arm2_single_alpha_params_usa_grade_de_um_valor_so(base_params) -> None:
    cell_params = build_arm2_single_alpha_params(base_params, 0.66)

    assert cell_params.model.quantiles == [0.66]
    assert cell_params.economics.default_alpha == 0.66
    assert cell_params.model.retrain_cadence_days == CELL_REVIEW_PERIOD_DAYS
    assert cell_params.erp_baseline.factor == CELL_ERP_FACTOR
    assert cell_params.erp_baseline.min_order_units == CELL_ERP_MIN_ORDER_UNITS


def test_build_arm2_single_alpha_params_aceita_alpha_fora_da_grade_de_producao(base_params) -> None:
    # 0.66 não está em model.quantiles de produção (params.yaml) -- é
    # exatamente o ponto: braço 2 não tem correção de não-cruzamento, então
    # é seguro sair da grade. Confirma que build_cell_params (que EXIGE
    # pertencer à grade) não é reusada aqui por engano.
    assert 0.66 not in set(base_params.model.quantiles)
    cell_params = build_arm2_single_alpha_params(base_params, 0.66)
    assert cell_params.model.quantiles == [0.66]


def test_build_arm2_single_alpha_params_e_puro(base_params) -> None:
    original_quantiles = list(base_params.model.quantiles)
    build_arm2_single_alpha_params(base_params, 0.66)
    assert base_params.model.quantiles == original_quantiles


def test_build_arm3_alpha_params_preserva_a_grade_de_producao_inteira(base_params) -> None:
    cell_params = build_arm3_alpha_params(base_params, 0.70)

    assert cell_params.model.quantiles == list(base_params.model.quantiles)
    assert 0.70 in cell_params.model.quantiles
    assert cell_params.economics.default_alpha == 0.70


def test_build_arm3_alpha_params_rejeita_alpha_fora_da_grade(base_params) -> None:
    with pytest.raises(ValueError, match=r"não está em model\.quantiles"):
        build_arm3_alpha_params(base_params, 0.66)


def test_arm3_alpha_grid_e_subconjunto_da_grade_de_producao(base_params) -> None:
    grade_producao = set(base_params.model.quantiles)
    assert set(ARM3_ALPHA_GRID) <= grade_producao


def test_arm2_alpha_grid_tem_16_pontos_passo_002() -> None:
    assert len(ARM2_ALPHA_GRID) == 16
    assert ARM2_ALPHA_GRID[0] == 0.60
    assert ARM2_ALPHA_GRID[-1] == 0.90
    passos = [round(b - a, 10) for a, b in pairwise(ARM2_ALPHA_GRID)]
    assert all(p == 0.02 for p in passos)


def _fake_portfolio_metrics(**overrides: float) -> PortfolioFinancialMetrics:
    base = {
        "margem_realizada_rs": 1.0,
        "ruptura_rs": 0.0,
        "perda_rs": 0.0,
        "capital_medio_rs": 100.0,
        "nivel_servico": 0.95,
        "giro_anualizado": 1.0,
        "carrying_cost_rs": 0.0,
        "decision_metric": 5.0,
    }
    base.update(overrides)
    return PortfolioFinancialMetrics(**base)


class _FakeResult:
    def __init__(self, portfolio_metrics: PortfolioFinancialMetrics) -> None:
        self.portfolio_metrics = portfolio_metrics


def test_point_summary_carrega_todas_as_premissas_exigidas_pela_etapa_313() -> None:
    resultado = _FakeResult(_fake_portfolio_metrics(nivel_servico=0.9484, decision_metric=7.29))

    resumo = point_summary(
        arm="estatistico_basestock",
        alpha=0.66,
        active_quantiles=[0.66],
        seed=42,
        polars_max_threads=2,
        result=resultado,
        segundos=684.66,
    )

    campos_obrigatorios = {
        "arm",
        "alpha",
        "lead_time_days",
        "review_period_days",
        "erp_factor",
        "erp_min_order_units",
        "active_quantiles",
        "seed",
        "polars_max_threads",
        "nivel_servico",
        "decision_metric",
        "capital_medio_rs",
        "segundos",
    }
    assert campos_obrigatorios <= resumo.keys()
    assert resumo["lead_time_days"] == CELL_LEAD_TIME_DAYS
    assert resumo["review_period_days"] == CELL_REVIEW_PERIOD_DAYS
    assert resumo["seed"] == 42
    assert resumo["polars_max_threads"] == 2


def test_point_summary_registra_polars_max_threads_none_quando_nao_setado() -> None:
    resultado = _FakeResult(_fake_portfolio_metrics())
    resumo = point_summary(
        arm="quantile_gbm_basestock",
        alpha=0.85,
        active_quantiles=[0.5, 0.7, 0.8, 0.85, 0.9, 0.95],
        seed=42,
        polars_max_threads=None,
        result=resultado,
        segundos=113.3,
    )
    # None explícito, não omitido -- self-sufficient summary tem que dizer
    # "não sei" em vez de fingir que o campo não existe.
    assert "polars_max_threads" in resumo
    assert resumo["polars_max_threads"] is None


def test_compute_item_decomposition_cruza_decision_metric_com_pct_dias_com_venda() -> None:
    events = pl.DataFrame(
        {
            "item_id": ["A", "A", "A", "A", "B", "B", "B", "B"],
            "day": [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 4)] * 2,
            "sold": [1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        }
    )
    item_metrics = pl.DataFrame({"item_id": ["A", "B"], "decision_metric": [8.0, 3.0]})

    resultado = compute_item_decomposition(events, item_metrics, evaluation_start=date(2020, 1, 1))

    linha_a = resultado.filter(pl.col("item_id") == "A").row(0, named=True)
    linha_b = resultado.filter(pl.col("item_id") == "B").row(0, named=True)
    assert linha_a["dias_avaliados"] == 4
    assert linha_a["dias_com_venda"] == 3
    assert linha_a["pct_dias_com_venda"] == pytest.approx(0.75)
    assert linha_b["pct_dias_com_venda"] == pytest.approx(0.25)
    # ordenado por decision_metric descendente
    assert resultado["item_id"].to_list() == ["A", "B"]


def test_compute_item_decomposition_respeita_a_fronteira_de_warmup() -> None:
    # dia anterior a evaluation_start não conta -- sem isso o warmup
    # contaminaria pct_dias_com_venda (CLAUDE.md seção 6).
    events = pl.DataFrame(
        {
            "item_id": ["A", "A"],
            "day": [date(2020, 1, 1), date(2020, 1, 2)],
            "sold": [1.0, 0.0],
        }
    )
    item_metrics = pl.DataFrame({"item_id": ["A"], "decision_metric": [1.0]})

    resultado = compute_item_decomposition(events, item_metrics, evaluation_start=date(2020, 1, 2))

    linha = resultado.row(0, named=True)
    assert linha["dias_avaliados"] == 1
    assert linha["dias_com_venda"] == 0


def test_consolidate_points_ordena_por_alpha(tmp_path: Path) -> None:
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    p1.write_text('{"alpha": 0.80, "nivel_servico": 0.96}')
    p2.write_text('{"alpha": 0.70, "nivel_servico": 0.94}')

    tabela = consolidate_points([p1, p2])

    assert tabela["alpha"].to_list() == [0.70, 0.80]
