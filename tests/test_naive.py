"""Testes de `motor.forecast.naive.NaiveForecaster` (Sprint 7).

Cenário de referência (`_historico_de_referencia`): 10 dias de demanda
conhecida, com dois "choques" (dia 7 alto, dia 8 baixo) para gerar resíduos
não degenerados. Os valores esperados em cada teste foram calculados à mão a
partir da mesma lógica que `NaiveForecaster` implementa (média móvel de
janela `window_days` terminando antes do dia, quantil empírico tipo 7 sobre
os resíduos ordenados) -- ver comentários inline para a conta.
"""

from datetime import date, timedelta

import polars as pl
import pytest

from motor.forecast.naive import NaiveForecaster, _empirical_quantile

D0 = date(2026, 1, 1)


def _dias(n: int) -> date:
    return D0 + timedelta(days=n)


def _historico(units: list[float], start: date = D0) -> pl.DataFrame:
    dates = [start + timedelta(days=i) for i in range(len(units))]
    return pl.DataFrame({"date": dates, "units_sold": units})


# Demanda constante em 7, com choque de +3 no dia 7 (D7=10) e -3 no dia 8 (D8=4).
_UNITS_REFERENCIA = [7, 7, 7, 7, 7, 7, 7, 10, 4, 7]  # D0 .. D9


# -- construtor --------------------------------------------------------------


def test_moving_average_weeks_nao_positivo_levanta_value_error() -> None:
    with pytest.raises(ValueError, match="moving_average_weeks"):
        NaiveForecaster(moving_average_weeks=0, min_residual_samples=1)


def test_min_residual_samples_nao_positivo_levanta_value_error() -> None:
    with pytest.raises(ValueError, match="min_residual_samples"):
        NaiveForecaster(moving_average_weeks=1, min_residual_samples=0)


# -- histórico insuficiente não quebra ---------------------------------------


def test_historico_vazio_nao_quebra_e_preve_zero() -> None:
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=1)
    historico_vazio = pl.DataFrame(
        {"date": [], "units_sold": []}, schema={"date": pl.Date, "units_sold": pl.Float64}
    )
    forecaster.fit(historico_vazio, as_of=D0)
    result = forecaster.predict_quantiles(D0, horizon=3, quantiles=[0.1, 0.5, 0.9])
    assert result["value"].to_list() == [0.0, 0.0, 0.0]


def test_historico_curto_usa_media_do_que_existir() -> None:
    # window_days = 7, mas só há 2 dias de histórico -- média cai para a
    # média desses 2 dias, não para zero nem para exceção.
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=100)
    forecaster.fit(_historico([4.0, 6.0]), as_of=_dias(2))
    result = forecaster.predict_quantiles(_dias(2), horizon=1, quantiles=[0.5])
    # média(4,6) = 5; poucas amostras de resíduo (min_residual_samples=100
    # nunca bate) -- quantil colapsa no ponto central.
    assert result["value"].to_list() == pytest.approx([5.0])


# -- quantis empíricos: monotonicidade e valor exato -------------------------


def test_quantis_e_ponto_central_batem_com_calculo_manual() -> None:
    """Valores calculados à mão -- ver docstring do módulo para a derivação
    completa da média móvel e dos resíduos deste cenário."""
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=3)
    forecaster.fit(_historico(_UNITS_REFERENCIA), as_of=_dias(10))

    result = forecaster.predict_quantiles(_dias(10), horizon=1, quantiles=[0.1, 0.5, 0.9])
    values = result["value"].to_list()

    assert values == pytest.approx([6.657142857142857, 7.0, 10.4])


def test_quantis_empiricos_sao_monotonicos_em_alpha() -> None:
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=3)
    forecaster.fit(_historico(_UNITS_REFERENCIA), as_of=_dias(10))

    result = forecaster.predict_quantiles(
        _dias(10), horizon=1, quantiles=[0.05, 0.1, 0.3, 0.5, 0.7, 0.9, 0.95]
    )
    values = result["value"].to_list()

    assert values == sorted(values)
    assert values[0] < values[-1]  # não degenerado: há spread real


def test_residuos_insuficientes_colapsam_no_ponto_central() -> None:
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=999)
    forecaster.fit(_historico(_UNITS_REFERENCIA), as_of=_dias(10))

    result = forecaster.predict_quantiles(_dias(10), horizon=1, quantiles=[0.1, 0.5, 0.9])
    # ponto central: média dos 7 dias antes de D10 (D3..D9) = 7.0
    assert result["value"].to_list() == pytest.approx([7.0, 7.0, 7.0])


def test_empirical_quantile_com_um_unico_valor_devolve_o_proprio_valor() -> None:
    assert _empirical_quantile([42.0], 0.9) == 42.0


# -- demanda acumulada no horizonte != soma de previsões diárias -------------


def test_acumulado_no_horizonte_dois_dias_difere_da_soma_de_duas_previsoes_diarias() -> None:
    """CLAUDE.md, seção 5: somar quantis diários para chegar num quantil da
    demanda acumulada é matematicamente errado. Este teste mostra a diferença
    numérica de fato, no mesmo cenário de referência, em vez de só documentar
    a regra em prosa.
    """
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=3)
    forecaster.fit(_historico(_UNITS_REFERENCIA), as_of=_dias(10))

    # "Errado": previsão de 1 dia no quantil 0.9, dobrada como se fosse a
    # previsão de 2 dias -- é a soma de quantis diários que o contrato proíbe.
    daily = forecaster.predict_quantiles(_dias(10), horizon=1, quantiles=[0.9])
    soma_de_diarios_dobrada = daily["value"].to_list()[0] * 2
    assert soma_de_diarios_dobrada == pytest.approx(20.8)

    # Certo: quantil calculado direto sobre a demanda acumulada de 2 dias.
    accumulated = forecaster.predict_quantiles(_dias(10), horizon=2, quantiles=[0.9])
    valor_acumulado_direto = accumulated["value"].to_list()[0]
    assert valor_acumulado_direto == pytest.approx(19.2)

    assert valor_acumulado_direto != pytest.approx(soma_de_diarios_dobrada)


# -- sem lookahead -------------------------------------------------------


def test_fit_recusa_historico_com_data_maior_ou_igual_a_as_of() -> None:
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=1)
    historico_com_vazamento = _historico(_UNITS_REFERENCIA, start=D0)  # cobre D0..D9
    with pytest.raises(AssertionError, match="history contém data >= as_of"):
        forecaster.fit(historico_com_vazamento, as_of=_dias(9))  # D9 está EM history, não antes


def test_predict_quantiles_nao_recebe_dado_alem_do_que_fit_registrou() -> None:
    """`NaiveForecaster` só conhece o que `fit` gravou -- não há nenhum outro
    canal de dado. Prova indireta (mas completa) de que a previsão para
    `as_of` não vê nada de `as_of` em diante: o histórico passado a `fit`
    termina em D9, e a previsão para D10 não muda se dados futuros (D10 em
    diante) simplesmente não existirem em lugar nenhum do processo.
    """
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=3)
    forecaster.fit(_historico(_UNITS_REFERENCIA), as_of=_dias(10))  # história só até D9
    result = forecaster.predict_quantiles(_dias(10), horizon=1, quantiles=[0.5])
    assert result["value"].to_list() == pytest.approx([7.0])


def test_backtest_so_usa_dias_cujo_horizonte_cabe_inteiro_no_historico_visivel() -> None:
    """Ajuste pedido na revisão da Sprint 7: teste explícito da borda do
    backtest, não só o teste genérico de sem-lookahead do simulador.

    Histórico denso D0..D9 (10 dias), horizon=3. Um dia `t` só vira amostra de
    resíduo se `t, t+1, t+2` (os 3 dias do horizonte) estiverem TODOS no
    histórico -- ou seja, `t <= D7` (`D7+2 = D9`, o último dia disponível).
    `D8` e `D9` não podem virar `t`: seus horizontes alcançariam `D10`/`D11`,
    dias que não existem no histórico (e que, no uso real via `Simulator`,
    cairiam em `as_of` ou além -- exatamente o que não pode acontecer).
    """
    forecaster = NaiveForecaster(moving_average_weeks=1, min_residual_samples=1)
    forecaster.fit(_historico(_UNITS_REFERENCIA), as_of=_dias(10))

    residuals_completo = forecaster._backtest_residuals(horizon=3)
    # t válidos: D0..D7 -> 8 amostras (10 dias - (horizon - 1) = 10 - 2 = 8)
    assert len(residuals_completo) == 8

    # Remove o último dia do histórico visível (simula um `as_of` um dia
    # antes) -- agora D7 também deixa de caber inteiro (D7+2=D9, que não
    # existe mais), então só D0..D6 sobram: 7 amostras.
    forecaster.fit(_historico(_UNITS_REFERENCIA[:-1]), as_of=_dias(9))
    residuals_um_dia_a_menos = forecaster._backtest_residuals(horizon=3)
    assert len(residuals_um_dia_a_menos) == 7
