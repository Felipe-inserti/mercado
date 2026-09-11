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

from datetime import date
from typing import Protocol

import polars as pl


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
