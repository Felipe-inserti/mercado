"""Coerência da janela de risco entre os três consumidores (Sprint 15):
`NaiveForecaster`/`StatisticalForecaster` (backtest de resíduos) e
`motor.forecast.quantile_gbm` (alvo do braço 3). Os três chamam
`motor.forecast.base.risk_window_dates`/`risk_window_bounds` -- nenhum
reimplementa o range por conta própria. Isso é o que impede a divergência
silenciosa entre política e modelo que CLAUDE.md, seção 5, chama de
"resultado inteiro vira ruído".

A técnica: monkeypatch da função por uma versão DELIBERADAMENTE errada. Se um
consumidor de fato delega, seu resultado muda junto. Se algum consumidor
tivesse sua própria cópia do range (a regressão que este teste existe pra
pegar), ele NÃO mudaria -- o teste falharia por "resultado idêntico ao
correto", não por erro de execução, e é exatamente esse silêncio que faria a
falha valer a pena.

Duas versões erradas, não uma só -- a primeira tentativa (deslocar a janela
em 1 dia, mantendo o mesmo comprimento) não bastou para `NaiveForecaster`/
`StatisticalForecaster`: o backtest de resíduos itera por TODAS as origens
históricas, e deslocar a janela só RELABELA qual origem captura um evento
isolado (ex.: um pico de demanda), sem mudar o MULTICONJUNTO de valores de
resíduo -- a distribuição empírica de quantis sai idêntica por simetria,
mesmo com a função de fato sendo chamada. Só ENCURTAR a janela (mesmo início,
um dia a menos) muda a soma acumulada em toda origem, de forma sistemática,
o suficiente pra aparecer no quantil final -- por isso é essa a versão errada
usada abaixo para os dois forecasters de backtest. Para
`quantile_gbm.target_for_origin`, que não itera origens (usa `as_of`
diretamente, sem essa simetria), o deslocamento simples já basta e é mais
direto de justificar.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

import motor.forecast.naive as naive_module
import motor.forecast.quantile_gbm as qgbm_module
import motor.forecast.statistical as statistical_module
from motor.forecast.base import risk_window_bounds, risk_window_dates
from motor.forecast.naive import NaiveForecaster
from motor.forecast.quantile_gbm import target_for_origin
from motor.forecast.statistical import StatisticalForecaster

D0 = date(2020, 1, 1)


# -- a função pura em si --------------------------------------------------


def test_risk_window_dates_inclui_o_proprio_as_of() -> None:
    dates = risk_window_dates(D0, horizon=3)
    assert dates == [D0, D0 + timedelta(days=1), D0 + timedelta(days=2)]


def test_risk_window_bounds_consistente_com_risk_window_dates() -> None:
    for horizon in (1, 3, 10, 30):
        dates = risk_window_dates(D0, horizon)
        start, end_exclusive = risk_window_bounds(D0, horizon)
        assert start == dates[0]
        assert end_exclusive == dates[-1] + timedelta(days=1)


def test_risk_window_dates_rejeita_horizon_nao_positivo() -> None:
    with pytest.raises(ValueError, match="horizon"):
        risk_window_dates(D0, horizon=0)


# -- monkeypatch cross-cutting: os três consumidores de fato delegam -------


def _demanda_com_pico(pico_dia: date, valor_pico: float, *, dias_totais: int) -> pl.DataFrame:
    """Série de demanda constante (1.0/dia) com um pico isolado em `pico_dia`
    -- history cobre `dias_totais` dias terminando em `pico_dia`."""
    start = pico_dia - timedelta(days=dias_totais - 1)
    dates = [start + timedelta(days=i) for i in range(dias_totais)]
    units = [valor_pico if d == pico_dia else 1.0 for d in dates]
    return pl.DataFrame({"date": dates, "units_sold": units})


def _janela_mais_curta(as_of: date, horizon: int) -> list[date]:
    """Janela ERRADA de propósito: mesmo início, um dia mais curta que o
    `horizon` pedido -- muda a soma acumulada de toda origem do backtest de
    forma sistemática (ao contrário de um deslocamento, que só relabela qual
    origem vê qual dia -- ver docstring do módulo)."""
    return [as_of + timedelta(days=i) for i in range(horizon - 1)]


def test_naive_forecaster_delega_em_risk_window_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    horizon = 5
    as_of = D0 + timedelta(days=60)
    dia_do_pico = as_of - timedelta(days=1)
    history = _demanda_com_pico(dia_do_pico, valor_pico=1000.0, dias_totais=90).filter(
        pl.col("date") < as_of
    )

    forecaster = NaiveForecaster(moving_average_weeks=4, min_residual_samples=1)
    forecaster.fit(history, as_of=as_of)
    correto = forecaster.predict_quantiles(as_of, horizon, [0.95])["value"][0]

    monkeypatch.setattr(naive_module, "risk_window_dates", _janela_mais_curta)
    forecaster2 = NaiveForecaster(moving_average_weeks=4, min_residual_samples=1)
    forecaster2.fit(history, as_of=as_of)
    com_janela_errada = forecaster2.predict_quantiles(as_of, horizon, [0.95])["value"][0]

    assert com_janela_errada != correto  # a previsão muda: o forecaster de fato delega


def test_statistical_forecaster_delega_em_risk_window_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    horizon = 5
    as_of = D0 + timedelta(days=90)
    dia_do_pico = as_of - timedelta(days=1)
    history = _demanda_com_pico(dia_do_pico, valor_pico=1000.0, dias_totais=120).filter(
        pl.col("date") < as_of
    )

    def _make() -> StatisticalForecaster:
        return StatisticalForecaster(
            level_window_weeks=4, seasonal_window_weeks=8, min_residual_samples=1
        )

    forecaster = _make()
    forecaster.fit(history, as_of=as_of)
    correto = forecaster.predict_quantiles(as_of, horizon, [0.95])["value"][0]

    monkeypatch.setattr(statistical_module, "risk_window_dates", _janela_mais_curta)
    forecaster2 = _make()
    forecaster2.fit(history, as_of=as_of)
    com_janela_errada = forecaster2.predict_quantiles(as_of, horizon, [0.95])["value"][0]

    assert com_janela_errada != correto


def test_quantile_gbm_target_for_origin_delega_em_risk_window_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    horizon = 5
    as_of = D0 + timedelta(days=30)
    # pico no PRIMEIRO dia da janela correta (o próprio as_of) -- a janela
    # deslocada (começa em as_of+1) não o inclui, então as duas somas
    # divergem de forma inequívoca. `target_for_origin` não itera origens
    # históricas (usa `as_of` direto), então o deslocamento simples já basta.
    dia_do_pico = as_of
    sales = pl.DataFrame(
        {
            "store_id": ["1"] * 90,
            "item_id": ["x"] * 90,
            "date": [as_of - timedelta(days=60) + timedelta(days=i) for i in range(90)],
        }
    ).with_columns(
        pl.when(pl.col("date") == dia_do_pico).then(1000.0).otherwise(1.0).alias("units_sold")
    )

    correto = target_for_origin(sales, item_ids=["x"], horizon_by_item={"x": horizon}, as_of=as_of)[
        "target"
    ][0]

    def _janela_deslocada(a: date, h: int) -> tuple[date, date]:
        return a + timedelta(days=1), a + timedelta(days=1 + h)

    monkeypatch.setattr(qgbm_module, "risk_window_bounds", _janela_deslocada)
    com_janela_errada = target_for_origin(
        sales, item_ids=["x"], horizon_by_item={"x": horizon}, as_of=as_of
    )["target"][0]

    assert com_janela_errada != correto
