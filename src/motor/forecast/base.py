"""Protocolo `Forecaster`, no grão de um único par loja-item.

Este protocolo é deliberadamente mais estreito que o `Forecaster` descrito no
CLAUDE.md (seção 5): aquele opera no grão do CONSOLIDADOR por fornecedor
(`keys: pl.DataFrame` com várias linhas loja-item, `item_params`,
`supplier_params`). Esse grão só existe a partir da sprint que introduz a
consolidação por fornecedor. O loop diário do simulador (Sprint 6,
`motor.simulator.engine.Simulator`) usa DIRETAMENTE o protocolo abaixo, no
grão de um par -- a consolidação por fornecedor envolve isto por fora, sem
alterar o loop. Ver a emenda datada em CLAUDE.md, seção 5.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

import polars as pl


def risk_window_dates(as_of: date, horizon: int) -> list[date]:
    """A janela de risco: `[as_of, as_of + horizon - 1]`, INCLUINDO o próprio
    `as_of` -- não `as_of + 1`. Fonte ÚNICA desta convenção no projeto
    (Sprint 15): `NaiveForecaster`/`StatisticalForecaster` (backtest de
    resíduos) e `motor.forecast.quantile_gbm` (construção do alvo) chamam
    esta função -- nenhum dos três reescreve o range por conta própria.

    Por que `as_of` entra na janela: é assim que os dois forecasters de
    sprints anteriores já foram construídos (`_backtest_residuals` de ambos
    usa `t + timedelta(days=i) for i in range(horizon)`), e mudar essa
    convenção numa sprint futura sem mudar as outras é o tipo de divergência
    silenciosa que não levanta exceção nenhuma e só envenena o resultado
    (`tests/test_risk_window_consistency.py` existe pra pegar exatamente
    isso -- ver a docstring de lá antes de tocar aqui).
    """
    if horizon <= 0:
        msg = f"horizon deve ser positivo, recebeu {horizon}"
        raise ValueError(msg)
    return [as_of + timedelta(days=i) for i in range(horizon)]


def risk_window_bounds(as_of: date, horizon: int) -> tuple[date, date]:
    """`(início_inclusive, fim_exclusivo)` da mesma janela de
    `risk_window_dates` -- conveniência para filtro por intervalo
    (`date >= início) & (date < fim)`) em vez de lista de datas. As duas
    formas têm que concordar sempre: `tests/test_risk_window_consistency.py`
    fixa essa equivalência."""
    dates = risk_window_dates(as_of, horizon)
    return dates[0], dates[-1] + timedelta(days=1)


class Forecaster(Protocol):
    """Previsão de demanda para um único par loja-item."""

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        """Ajusta o modelo a `history`.

        `history` contém apenas linhas com `date < as_of` -- é o simulador
        que garante o corte, filtrando antes de chamar `fit` (CLAUDE.md,
        seção 6: "não confie em o modelo se comportar bem -- filtre antes de
        entregar"). Implementações não precisam refiltrar, mas um
        `Forecaster` espião de teste verifica essa garantia explicitamente
        (ver `tests/fakes.py`).
        """

    def predict_quantiles(self, as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        """Devolve colunas `quantile`, `value`: demanda ACUMULADA nos
        próximos `horizon` dias a partir de `as_of` -- nunca demanda diária.

        Somar quantis diários para chegar num quantil da demanda total no
        horizonte é matematicamente errado (o quantil de uma soma de
        variáveis não é a soma dos quantis, exceto em casos degenerados).
        Por isso este método devolve diretamente o quantil da demanda
        acumulada na janela de risco, nunca um quantil por dia para o
        chamador agregar. A previsão estatística real (sprint futura)
        depende dessa garantia -- não a quebre.
        """
