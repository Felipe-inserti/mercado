"""Testes de `motor.forecast.statistical.StatisticalForecaster` (Sprint 12).

Cenários com padrão semanal EXATO e sem ruído (`_pattern_a`/`_pattern_b`):
fim de semana (sáb/dom) e início de semana (seg/ter) com o dobro da demanda
dos outros dias, mesma soma semanal (90) nos dois padrões -- deliberado, para
isolar o efeito da SAZONALIDADE do efeito do NÍVEL nos testes que comparam
períodos com padrões diferentes (ver `test_indice_sazonal_de_um_periodo_nao_vaza...`).
Qualquer janela cujo tamanho é múltiplo exato de 7 dias reconstrói o padrão
sem nenhum erro de arredondamento -- os valores manuais abaixo não são
aproximação, são exatos.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from motor.forecast.statistical import StatisticalForecaster

D0 = date(2026, 1, 1)


def _dias(n: int) -> date:
    return D0 + timedelta(days=n)


def _historico(units: list[float], start: date = D0) -> pl.DataFrame:
    dates = [start + timedelta(days=i) for i in range(len(units))]
    return pl.DataFrame({"date": dates, "units_sold": units})


def _pattern_a(weekday: int) -> float:
    """Fim de semana (sáb=6, dom=7) forte -- soma semanal = 5*10 + 2*20 = 90."""
    return 20.0 if weekday in (6, 7) else 10.0


def _pattern_b(weekday: int) -> float:
    """Início de semana (seg=1, ter=2) forte -- MESMA soma semanal (90), padrão diferente."""
    return 20.0 if weekday in (1, 2) else 10.0


def _serie_padrao(pattern: object, n_days: int, start: date = D0) -> list[float]:
    return [pattern((start + timedelta(days=i)).isoweekday()) for i in range(n_days)]  # type: ignore[operator]


# -- construtor ---------------------------------------------------------------


def test_level_window_weeks_nao_positivo_levanta_value_error() -> None:
    with pytest.raises(ValueError, match="level_window_weeks"):
        StatisticalForecaster(level_window_weeks=0, seasonal_window_weeks=1, min_residual_samples=1)


def test_seasonal_window_weeks_nao_positivo_levanta_value_error() -> None:
    with pytest.raises(ValueError, match="seasonal_window_weeks"):
        StatisticalForecaster(level_window_weeks=1, seasonal_window_weeks=0, min_residual_samples=1)


def test_min_residual_samples_nao_positivo_levanta_value_error() -> None:
    with pytest.raises(ValueError, match="min_residual_samples"):
        StatisticalForecaster(level_window_weeks=1, seasonal_window_weeks=1, min_residual_samples=0)


# -- histórico insuficiente não quebra -----------------------------------------


def test_historico_vazio_nao_quebra_e_preve_zero() -> None:
    forecaster = StatisticalForecaster(
        level_window_weeks=1, seasonal_window_weeks=1, min_residual_samples=1
    )
    historico_vazio = pl.DataFrame(
        {"date": [], "units_sold": []}, schema={"date": pl.Date, "units_sold": pl.Float64}
    )
    forecaster.fit(historico_vazio, as_of=D0)
    result = forecaster.predict_quantiles(D0, horizon=3, quantiles=[0.1, 0.5, 0.9])
    assert result["value"].to_list() == [0.0, 0.0, 0.0]


# -- ponto central bate com cálculo manual -------------------------------------


def test_ponto_central_bate_com_calculo_manual_em_padrao_semanal_conhecido() -> None:
    """8 semanas de `_pattern_a`; `level_window_weeks`/`seasonal_window_weeks`
    múltiplos exatos de 7 dias reconstroem o padrão sem erro -- qualquer
    janela de 7 dias soma exatamente 90 (um ciclo semanal completo).
    `min_residual_samples` alto colapsa o quantil no ponto central.
    """
    units = _serie_padrao(_pattern_a, n_days=56)
    forecaster = StatisticalForecaster(
        level_window_weeks=2, seasonal_window_weeks=4, min_residual_samples=999
    )
    forecaster.fit(_historico(units), as_of=_dias(56))

    result = forecaster.predict_quantiles(_dias(56), horizon=7, quantiles=[0.5])
    assert result["value"].to_list() == pytest.approx([90.0])


def test_ponto_central_de_horizonte_nao_multiplo_de_7_soma_dias_desiguais() -> None:
    """Horizonte de 3 dias a partir de uma quinta-feira (dia da semana do
    `_dias(59)`, ver comentário) cobre dias de semana comuns -- soma manual
    3*10=30, distinto do caso de horizonte=7 (sempre 90, ciclo completo)."""
    units = _serie_padrao(_pattern_a, n_days=56)
    forecaster = StatisticalForecaster(
        level_window_weeks=2, seasonal_window_weeks=4, min_residual_samples=999
    )
    forecaster.fit(_historico(units), as_of=_dias(56))

    # D56, D57, D58 -- 3 dias após 8 semanas cheias a partir de D0; como o
    # padrão é periódico de período 7, esses 3 dias têm o mesmo dia-da-semana
    # que D0, D1, D2. Calcula à mão a soma de pattern_a nesses 3 dias-da-semana.
    esperado = sum(_pattern_a(_dias(i).isoweekday()) for i in range(3))
    result = forecaster.predict_quantiles(_dias(56), horizon=3, quantiles=[0.5])
    assert result["value"].to_list() == pytest.approx([esperado])


# -- quantis empíricos: monotonicidade e colapso -------------------------------


def test_quantis_empiricos_sao_monotonicos_em_alpha() -> None:
    """Mesmo cenário de padrão exato, com um choque isolado (D10 += 5) para
    gerar resíduos não degenerados no backtest. D10 fica FORA das janelas
    (`[28,56)`/`[42,56)`) que `predict_quantiles(as_of=_dias(56), ...)` usa
    para o próprio ponto central -- o choque só aparece nos resíduos do
    backtest (candidatos `t` cujas janelas alcançam D10), nunca no ponto
    central real, o que mantém esse valor em 90.0 exatos (ver o teste de
    colapso logo abaixo, que depende disso)."""
    units = _serie_padrao(_pattern_a, n_days=56)
    units[10] += 5.0
    forecaster = StatisticalForecaster(
        level_window_weeks=2, seasonal_window_weeks=4, min_residual_samples=3
    )
    forecaster.fit(_historico(units), as_of=_dias(56))

    result = forecaster.predict_quantiles(
        _dias(56), horizon=7, quantiles=[0.05, 0.1, 0.3, 0.5, 0.7, 0.9, 0.95]
    )
    values = result["value"].to_list()

    assert values == sorted(values)
    assert values[0] < values[-1]  # não degenerado: o choque cria spread real


def test_residuos_insuficientes_colapsam_no_ponto_central() -> None:
    units = _serie_padrao(_pattern_a, n_days=56)
    units[10] += 5.0  # fora das janelas do ponto central em as_of=D56, ver teste acima
    forecaster = StatisticalForecaster(
        level_window_weeks=2, seasonal_window_weeks=4, min_residual_samples=999
    )
    forecaster.fit(_historico(units), as_of=_dias(56))

    result = forecaster.predict_quantiles(_dias(56), horizon=7, quantiles=[0.1, 0.5, 0.9])
    assert result["value"].to_list() == pytest.approx([90.0, 90.0, 90.0])


# -- sem lookahead --------------------------------------------------------------


def test_fit_recusa_historico_com_data_maior_ou_igual_a_as_of() -> None:
    forecaster = StatisticalForecaster(
        level_window_weeks=1, seasonal_window_weeks=1, min_residual_samples=1
    )
    units = _serie_padrao(_pattern_a, n_days=10)
    with pytest.raises(AssertionError, match="history contém data >= as_of"):
        forecaster.fit(_historico(units), as_of=_dias(9))  # D9 está EM history, não antes


def test_backtest_so_usa_dias_cujo_horizonte_cabe_inteiro_no_historico_visivel() -> None:
    """Mesma borda de `NaiveForecaster` (ver `tests/test_naive.py`): histórico
    denso D0..D13 (14 dias), horizon=5 -- só `t<=D9` cabe inteiro (D9+4=D13)."""
    units = _serie_padrao(_pattern_a, n_days=14)
    forecaster = StatisticalForecaster(
        level_window_weeks=1, seasonal_window_weeks=1, min_residual_samples=1
    )
    forecaster.fit(_historico(units), as_of=_dias(14))

    residuals = forecaster._backtest_residuals(horizon=5)
    assert len(residuals) == 10  # t = D0..D9 -> 14 - (5 - 1) = 10 amostras


# -- vazamento por feature global (sazonalidade) -- teste obrigatório ----------


def test_indice_sazonal_de_um_periodo_nao_vaza_para_previsoes_de_periodo_anterior() -> None:
    """Histórico com DOIS padrões semanais bem diferentes: D0..D55 seguem
    `_pattern_a` (fim de semana forte), D56..D111 seguem `_pattern_b` (início
    de semana forte) -- MESMA soma semanal (90) nos dois, de propósito, para
    isolar o efeito da sazonalidade do efeito do nível.

    Se o índice sazonal (ou o nível recente) fosse calculado UMA VEZ sobre o
    histórico inteiro (vazamento por feature global, CLAUDE.md seção 8), o
    índice de cada dia da semana seria uma mistura de padrão A e padrão B, e
    a previsão para um candidato `t` de backtest dentro do período A não
    bateria mais com a demanda real (que ali é puramente A) -- os resíduos
    deixariam de ser zero. Com a implementação correta (`_seasonal_indices`/
    `_recent_level` recalculados a cada `t`, usando só dados `< t`), todo `t`
    cujas janelas de nível/sazonalidade E cuja janela real de demanda caem
    inteiramente dentro do período A reconstrói o padrão A exatamente.

    `t` em [28, 49]: janela sazonal `[t-28, t)`, janela de nível `[t-14, t)`
    e janela real `[t, t+6]` cabem todas dentro de D0..D55 (padrão A) --
    fora desse intervalo a janela real alcançaria D56 (padrão B) e o
    resíduo deixaria de ser um teste de vazamento (viraria erro de previsão
    legítimo, não vazamento).
    """
    units = _serie_padrao(_pattern_a, n_days=56) + _serie_padrao(
        _pattern_b, n_days=56, start=_dias(56)
    )
    forecaster = StatisticalForecaster(
        level_window_weeks=2, seasonal_window_weeks=4, min_residual_samples=1
    )
    forecaster.fit(_historico(units), as_of=_dias(112))

    residuals = forecaster._backtest_residuals(horizon=7)
    # histórico denso D0..D111 -- residuals[i] corresponde exatamente a t=D_i.
    for t in range(28, 50):
        assert residuals[t] == pytest.approx(0.0, abs=1e-9), f"vazou sazonalidade em t={t}"
