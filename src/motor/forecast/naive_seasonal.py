"""Previsão ingênua sazonal (`NaiveSeasonalForecaster`, Sprint 24, etapa 24.3).

Régua de comparação do backtest do mercado piloto: a previsão de um dia `d` da
janela de risco é a venda do ÚLTIMO mesmo dia da semana ANTERIOR a `as_of`.
Para horizonte maior que 7 dias isso significa reusar a última semana
observada -- nunca `d - 7` quando isso cai em `d >= as_of` (dado que ainda não
existe no momento da decisão).

Contrato: `motor.forecast.base.Forecaster`, grão de um par loja-item. Só o
quantil 0,5 existe: o naive é uma previsão pontual, sem distribuição.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from motor.forecast.base import risk_window_dates

_MEDIAN: float = 0.5


class NaiveSeasonalForecaster:
    """Cada dia do horizonte recebe a venda do último mesmo dia da semana
    anterior a `as_of`; o acumulado é a soma dessas vendas.

    Se algum dia de referência não está no histórico visível, o acumulado é
    `None` (valor nulo no `DataFrame`) -- não zero, não soma parcial: dado
    ausente não é dado zero (CLAUDE.md, seção 8).
    """

    def __init__(self) -> None:
        self._demand_by_day: dict[date, float] = {}

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        """Guarda `history` (colunas `date`, `units_sold`; já filtrado por
        `date < as_of` pelo simulador) num dicionário dia -> unidades.

        Confere o corte contra o próprio `history`, como `NaiveForecaster`:
        defesa redundante com o simulador, mas esta classe roda fora dele (no
        backtest do piloto).
        """
        dates: list[date] = history["date"].to_list()
        units: list[float] = history["units_sold"].to_list()
        if dates and max(dates) >= as_of:
            msg = f"history contém data >= as_of: {max(dates)} >= {as_of}"
            raise AssertionError(msg)
        self._demand_by_day = dict(zip(dates, units, strict=True))

    def predict_quantiles(self, as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        """Acumulado no horizonte, só para `quantile == 0.5`; outro quantil
        levanta `ValueError`. Devolve `value = None` se faltar algum dia de
        referência.
        """
        if any(q != _MEDIAN for q in quantiles):
            msg = f"NaiveSeasonalForecaster só prevê o quantil 0.5, recebeu {quantiles}"
            raise ValueError(msg)

        references = [
            self._demand_by_day.get(_last_same_weekday_before(day, as_of))
            for day in risk_window_dates(as_of, horizon)
        ]
        total: float | None = None
        if all(reference is not None for reference in references):
            total = sum(reference for reference in references if reference is not None)
        return pl.DataFrame(
            {"quantile": quantiles, "value": [total] * len(quantiles)},
            schema={"quantile": pl.Float64, "value": pl.Float64},
        )


def _last_same_weekday_before(day: date, as_of: date) -> date:
    """Último dia com o mesmo dia da semana de `day` e estritamente anterior
    a `as_of`: `day - 7k`, com o menor `k >= 1` tal que o resultado é `< as_of`.

    Ex.: `day == as_of` -> `as_of - 7`; `day == as_of + 6` -> `as_of - 1`;
    `day == as_of + 7` -> `as_of - 7` de novo (a última semana é reusada).
    """
    weeks_back = (day - as_of).days // 7 + 1
    return day - timedelta(days=7 * weeks_back)
