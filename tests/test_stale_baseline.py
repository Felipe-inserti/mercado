"""Testes de `motor.experiments.stale_baseline` (Sprint 18, Fase 4).

Só a parte pura/de leitura (`_coverage_ratio`, `load_stale_calibration`,
`load_baseline_recalibrado`, `load_motor_iso_servico`, `load_stale_scenario`,
`build_comparison_table`, `decomposicao_gap_servico`,
`decomposicao_bruta_decision_metric`) -- `run_stale_baseline` roda
o `Simulator` real sobre 275 itens e é caro demais para teste automatizado,
mesmo espírito de `tests/test_sensitivity.py`/`tests/test_iso_service.py`.

Os manifestos/parquet fixture só têm os campos que o módulo de fato lê --
não uma cópia de um manifesto real (que tem centenas de campos irrelevantes
aqui).
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from motor.experiments import stale_baseline as sb


def _write_erp_manifest(
    path: Path,
    *,
    factor: float,
    min_order_units: float,
    nivel_servico: float,
    decision_metric: float,
    capital_medio_rs: float,
    moving_average_weeks: int = 4,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "erp_baseline_calibration": {
                    "factor": factor,
                    "min_order_units": min_order_units,
                    "target_service_level": 0.95,
                    "moving_average_weeks": moving_average_weeks,
                    "coverage_days_implied": factor * moving_average_weeks * 7,
                    "coverage_context": "texto preso em outra célula -- nunca lido por este módulo",
                },
                "results": {
                    "portfolio": {
                        "nivel_servico": nivel_servico,
                        "decision_metric": decision_metric,
                        "capital_medio_rs": capital_medio_rs,
                    }
                },
            }
        )
    )


@pytest.fixture
def cenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Monta a árvore mínima de resultados que `stale_baseline` espera,
    redirecionando os diretórios do módulo para dentro de `tmp_path`."""
    results = tmp_path / "results"
    sensitivity_dir = results / "sensibilidade_dirigida"
    iso_dir = results / "iso_servico"
    stale_dir = results / "baseline_desatualizado"
    monkeypatch.setattr(sb, "RESULTS_DIR", results)
    monkeypatch.setattr(sb, "SENSITIVITY_DIR", sensitivity_dir)
    monkeypatch.setattr(sb, "ISO_SERVICE_DIR", iso_dir)
    monkeypatch.setattr(sb, "STALE_BASELINE_DIR", stale_dir)

    # célula-fonte lt3/rp7 -- factor calibrado baixo (janela curta)
    _write_erp_manifest(
        sensitivity_dir / "lt3_rp7" / "erp_baseline" / "manifest.json",
        factor=0.34,
        min_order_units=0.0,
        nivel_servico=0.93869149,
        decision_metric=17.17948929,
        capital_medio_rs=274093.57270607,
    )
    # célula-fonte lt5/rp7
    _write_erp_manifest(
        sensitivity_dir / "lt5_rp7" / "erp_baseline" / "manifest.json",
        factor=0.40,
        min_order_units=3.0,
        nivel_servico=0.9358073,
        decision_metric=17.41777597,
        capital_medio_rs=269644.3648571,
    )
    # baseline recalibrado na célula-alvo lt7/rp14
    _write_erp_manifest(
        sensitivity_dir / "lt7_rp14" / "erp_baseline" / "manifest.json",
        factor=0.8,
        min_order_units=0.0,
        nivel_servico=0.9485436,
        decision_metric=7.08751197,
        capital_medio_rs=672427.37257384,
    )
    # motor (braço 2, iso-serviço) na célula-alvo
    iso_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "alpha": [0.66],
            "nivel_servico": [0.9483648],
            "decision_metric": [7.291916],
            "capital_medio_rs": [653587.462182],
        }
    ).write_parquet(iso_dir / "arm2_alpha_grid.parquet")

    # os dois braços "desatualizados" na célula-alvo (o que `run_stale_baseline`
    # teria gravado) -- fatores das células-fonte, mas MEDIDOS em lt7/rp14
    # (piores, porque a janela de risco cresceu sem recalibrar).
    _write_erp_manifest(
        stale_dir / "calibrado_lt3_rp7" / "erp_baseline" / "manifest.json",
        factor=0.34,
        min_order_units=0.0,
        nivel_servico=0.80,
        decision_metric=12.0,
        capital_medio_rs=300000.0,
    )
    _write_erp_manifest(
        stale_dir / "calibrado_lt5_rp7" / "erp_baseline" / "manifest.json",
        factor=0.40,
        min_order_units=3.0,
        nivel_servico=0.87,
        decision_metric=13.0,
        capital_medio_rs=320000.0,
    )
    return results


def test_coverage_ratio_usa_janela_de_risco_da_celula_alvo() -> None:
    # factor=0.34, moving_average_days=28 -> coverage_days_implied=9.52,
    # mas a janela de risco da célula-ALVO (lt=7/rp=14) é 21, não 10 (a
    # janela da célula-FONTE onde o factor foi calibrado) -- é exatamente o
    # descasamento que a sprint mede.
    ratio = sb._coverage_ratio(9.52, review_period_days=sb.CELL_REVIEW_PERIOD_DAYS)
    assert ratio == pytest.approx(9.52 / 21)


@pytest.mark.usefixtures("cenario")
def test_load_stale_calibration_le_apenas_campos_numericos() -> None:
    source = sb.load_stale_calibration("calibrado_lt3_rp7")
    assert source.factor == 0.34
    assert source.min_order_units == 0.0
    assert source.source_lead_time_days == 3
    assert source.source_review_period_days == 7


@pytest.mark.usefixtures("cenario")
def test_load_baseline_recalibrado() -> None:
    baseline = sb.load_baseline_recalibrado()
    assert baseline.nivel_servico == pytest.approx(0.9485436)
    assert baseline.decision_metric == pytest.approx(7.08751197)


@pytest.mark.usefixtures("cenario")
def test_load_motor_iso_servico_filtra_pelo_alpha_escolhido() -> None:
    motor = sb.load_motor_iso_servico()
    assert motor.decision_metric == pytest.approx(7.291916)
    assert motor.factor is None  # motor não tem factor -- não é ERP


@pytest.mark.usefixtures("cenario")
def test_load_stale_scenario_recomputa_cobertura_contra_a_celula_alvo() -> None:
    stale = sb.load_stale_scenario("calibrado_lt3_rp7")
    assert stale.nivel_servico == pytest.approx(0.80)
    # coverage_days_implied = factor x moving_average_days = 0.34 x 28 = 9.52,
    # SEMPRE o mesmo número (não depende de onde é aplicado) -- é a RAZÃO
    # contra a janela de risco que muda entre a célula-fonte e a célula-alvo.
    assert stale.coverage_days_implied_na_celula_alvo == pytest.approx(9.52)


@pytest.mark.usefixtures("cenario")
def test_build_comparison_table_tem_uma_linha_por_cenario() -> None:
    table = sb.build_comparison_table()
    assert table.height == 4  # 2 desatualizados + 1 recalibrado + 1 motor
    assert set(table["cenario"].to_list()) == {
        s.cenario
        for s in [
            sb.load_stale_scenario("calibrado_lt3_rp7"),
            sb.load_stale_scenario("calibrado_lt5_rp7"),
            sb.load_baseline_recalibrado(),
            sb.load_motor_iso_servico(),
        ]
    }


@pytest.mark.usefixtures("cenario")
def test_build_comparison_table_gap_de_servico_do_baseline_recalibrado_e_zero() -> None:
    table = sb.build_comparison_table()
    linha = table.filter(pl.col("cenario") == sb.load_baseline_recalibrado().cenario)
    assert linha["gap_servico_vs_baseline_recalibrado_pp"][0] == pytest.approx(0.0)


@pytest.mark.usefixtures("cenario")
def test_decomposicao_bruta_decision_metric_soma_dos_dois_passos_bate_com_o_total() -> None:
    dec = sb.decomposicao_bruta_decision_metric("calibrado_lt3_rp7")
    assert dec["ganho_recalibracao"] + dec["ganho_modelo"] == pytest.approx(dec["ganho_total"])
    # valores da fixture: stale=12.0, recalibrado=7.08751197, motor=7.291916
    # -- recalibrar de 12.0 para 7.08751197 é uma QUEDA de decision_metric
    # bruto (o baseline desatualizado só "parece" eficiente por sub-abastecer
    # -- ver decomposicao_gap_servico para a decomposição de negócio válida).
    assert dec["ganho_recalibracao"] < 0
    assert dec["ganho_modelo"] > 0


@pytest.mark.usefixtures("cenario")
def test_decomposicao_gap_servico_recalibracao_fecha_o_gap_inteiro_por_construcao() -> None:
    # fixture: stale=0.80, baseline_recalibrado=0.9485436, motor=0.9483648
    # -- motor roda em alpha iso-serviço, calibrado pra bater o MESMO nível
    # do baseline recalibrado, não pra fechar mais gap sozinho -- por
    # construção, fechado_pelo_modelo_pp fica perto de zero (pode ser
    # levemente negativo, grade de alpha não bate exato).
    gap = sb.decomposicao_gap_servico("calibrado_lt3_rp7")
    assert gap["gap_total_pp"] == pytest.approx(gap["fechado_por_recalibracao_pp"])
    assert gap["pct_fechado_por_recalibracao"] == pytest.approx(100.0)
    assert abs(gap["fechado_pelo_modelo_pp"]) < 1.0


@pytest.mark.usefixtures("cenario")
def test_decomposicao_gap_servico_dois_rotulos_diferentes_dao_gaps_diferentes() -> None:
    gap_lt3 = sb.decomposicao_gap_servico("calibrado_lt3_rp7")
    gap_lt5 = sb.decomposicao_gap_servico("calibrado_lt5_rp7")
    assert gap_lt3["gap_total_pp"] != gap_lt5["gap_total_pp"]
