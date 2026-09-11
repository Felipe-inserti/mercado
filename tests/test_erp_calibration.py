"""Testes de `motor.policy.erp_calibration` (Sprint 7).

Cenário sintético: demanda constante (`DAILY_DEMAND`), lead_time e
review_period fixos. Em regime permanente com demanda constante, o limiar
analítico de ruptura zero é `d x (lead_time + review_period)` -- o mesmo
resultado provado em `tests/test_simulator.py::test_regime_permanente_*` para
`OrderUpToPolicy`. `ErpBaselinePolicy.order` se comporta como um order-up-to
de nível `target = mu_daily x moving_average_days x factor` sempre que o
piso `min_order_units` não é o fator limitante -- por isso o mesmo limiar
serve pra escolher um fator "insuficiente" (recorrentemente abaixo da meta de
nível de serviço) e fatores "suficientes" (acima do limiar) de forma
determinística, sem precisar recalcular a série dia a dia à mão.
"""

from datetime import date, timedelta
from typing import Any

import polars as pl
import pytest

from motor.policy.erp_calibration import (
    CalibrationItem,
    _PrecomputedForecaster,
    _review_dates,
    sweep_erp_baseline,
)

START = date(2026, 3, 1)
LEAD_TIME_DAYS = 2
REVIEW_PERIOD_DAYS = 3
DAILY_DEMAND = 10.0
HISTORICO_DIAS_ANTES = 30
DIAS_SIMULADOS = 30
WARMUP_DAYS = 10
END = START + timedelta(days=DIAS_SIMULADOS - 1)

# target = mu_daily(10) x moving_average_days(7) x factor
# limiar analítico (d x (L+R) = 10 x (2+3) = 50): target < 50 gera ruptura
# recorrente em regime permanente; target >= 50 dá nível de serviço ~100%.
_FACTOR_INSUFICIENTE = 0.5  # target = 35 < 50
_FACTOR_SUFICIENTE = 1.0  # target = 70 >= 50
_FACTOR_FOLGADO = 1.5  # target = 105 >= 50, estoque médio maior


def _item_demanda_constante() -> CalibrationItem:
    inicio_historico = START - timedelta(days=HISTORICO_DIAS_ANTES)
    n_dias = (END - inicio_historico).days + 1
    dates = [inicio_historico + timedelta(days=i) for i in range(n_dias)]
    demand = pl.DataFrame({"date": dates, "units_sold": [DAILY_DEMAND] * n_dias})
    return CalibrationItem(
        item_id="item_1",
        demand=demand,
        lead_time_days=LEAD_TIME_DAYS,
        review_period_days=REVIEW_PERIOD_DAYS,
    )


def _sweep(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "items": [_item_demanda_constante()],
        "start": START,
        "end": END,
        "warmup_days": WARMUP_DAYS,
        "moving_average_weeks": 1,
        "min_residual_samples": 1,
        "quantiles": [0.5],
        "factor_grid": [_FACTOR_INSUFICIENTE, _FACTOR_SUFICIENTE, _FACTOR_FOLGADO],
        "min_order_grid": [0.0, 100.0],
        "target_service_level": 0.95,
    }
    kwargs.update(overrides)
    return sweep_erp_baseline(**kwargs)


# -- grade e escolha -------------------------------------------------------


def test_grade_tem_uma_linha_por_combinacao() -> None:
    result = _sweep()
    assert len(result.grid) == 3 * 2


def test_configuracao_com_target_abaixo_do_limiar_analitico_nao_atinge_a_meta() -> None:
    result = _sweep()
    # Com min_order_units=0.0, o piso não interfere -- só o fator define o
    # target. Com min_order_units=100.0 o piso força pedidos bem acima do
    # necessário e mascara o fator insuficiente (fill_rate sobe pra 1.0) --
    # por isso a comparação é isolada em min_order_units=0.0, não "todas as
    # combinações com este fator".
    (insuficiente,) = [
        g for g in result.grid if g.factor == _FACTOR_INSUFICIENTE and g.min_order_units == 0.0
    ]
    assert insuficiente.fill_rate < 0.95


def test_configuracoes_com_target_acima_do_limiar_atingem_a_meta() -> None:
    result = _sweep()
    suficientes = [g for g in result.grid if g.factor in (_FACTOR_SUFICIENTE, _FACTOR_FOLGADO)]
    assert suficientes
    assert all(g.fill_rate >= 0.95 for g in suficientes)


def test_escolhe_a_configuracao_de_menor_estoque_medio_entre_as_que_atingem_a_meta() -> None:
    result = _sweep()
    assert result.target_met is True
    # Entre as que batem a meta, a de menor avg_on_hand é o fator suficiente
    # (menor target) com min_order_units=0 -- fator folgado e min_order alto
    # só aumentam estoque médio sem melhorar um nível de serviço que já está
    # no teto.
    assert result.chosen.factor == _FACTOR_SUFICIENTE
    assert result.chosen.min_order_units == 0.0


def test_determinismo_duas_rodadas_produzem_a_mesma_grade() -> None:
    result_a = _sweep()
    result_b = _sweep()
    assert result_a.grid == result_b.grid
    assert result_a.chosen == result_b.chosen


def test_nenhuma_configuracao_atinge_a_meta_escolhe_maior_fill_rate_e_marca_nao_atingido() -> None:
    result = _sweep(
        factor_grid=[_FACTOR_INSUFICIENTE],
        min_order_grid=[0.0],
        target_service_level=0.999,
    )
    assert result.target_met is False
    assert result.chosen.fill_rate == max(g.fill_rate for g in result.grid)


def test_sweep_erp_baseline_rejeita_grade_vazia() -> None:
    with pytest.raises(ValueError, match="grid"):
        _sweep(factor_grid=[])


def test_sweep_erp_baseline_rejeita_sem_itens() -> None:
    with pytest.raises(ValueError, match="item"):
        _sweep(items=[])


# -- pré-cálculo de forecast -------------------------------------------------


def test_review_dates_respeita_o_calendario_de_revisao() -> None:
    dates = _review_dates(START, END, REVIEW_PERIOD_DAYS)
    assert dates[0] == START
    assert all((d - START).days % REVIEW_PERIOD_DAYS == 0 for d in dates)


def test_precomputed_forecaster_levanta_erro_para_as_of_fora_do_cache() -> None:
    forecaster = _PrecomputedForecaster({START: pl.DataFrame({"quantile": [0.5], "value": [1.0]})})
    with pytest.raises(KeyError, match="sem cache"):
        forecaster.predict_quantiles(START + timedelta(days=1), horizon=1, quantiles=[0.5])
