"""Previsão ingênua (`NaiveForecaster`): média móvel de N semanas sobre a
demanda diária, escalada para a demanda ACUMULADA na janela de risco, com
quantis empíricos dos resíduos da própria média móvel.

Contrato: `motor.forecast.base.Forecaster`, grão de um par loja-item (Sprint 6).
Esta é a previsão que sustenta o braço 1 (ERP baseline, Sprint 7): nenhum
modelo paramétrico, nenhuma sazonalidade -- só a média móvel e o erro
histórico dela mesma contra a demanda real.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

import polars as pl


def _empirical_quantile(sorted_values: list[float], q: float) -> float:
    """Quantil empírico por interpolação linear sobre uma lista JÁ ordenada
    (equivalente ao tipo 7 de Hyndman & Fan, o default de `numpy`/`polars`).

    Reimplementado aqui, em vez de materializar um `pl.Series`, porque os
    resíduos são poucas dezenas de valores -- não o volume que justifica
    `polars` (CLAUDE.md, seção 2).
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    position = q * (n - 1)
    lower = int(position)
    upper = min(lower + 1, n - 1)
    frac = position - lower
    return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])


class NaiveForecaster:
    """Média móvel de `moving_average_weeks` semanas + quantis empíricos dos
    resíduos dessa mesma média móvel, medidos por backtest dentro do próprio
    histórico visível (`fit`).

    Sem nenhum dia de janela disponível, a média cai para 0.0 -- comportamento
    definido, não exceção (`_moving_average_ending_before`). Sem
    `min_residual_samples` resíduos, os quantis colapsam no ponto central, sem
    spread -- também definido, não acidental. Os dois casos cobrem "item sem
    histórico suficiente" sem lançar erro.
    """

    def __init__(self, moving_average_weeks: int, min_residual_samples: int) -> None:
        if moving_average_weeks <= 0:
            msg = f"moving_average_weeks deve ser positivo, recebeu {moving_average_weeks}"
            raise ValueError(msg)
        if min_residual_samples <= 0:
            msg = f"min_residual_samples deve ser positivo, recebeu {min_residual_samples}"
            raise ValueError(msg)
        self._window_days = moving_average_weeks * 7
        self._min_residual_samples = min_residual_samples
        self._demand_by_day: dict[date, float] = {}
        self._sorted_dates: list[date] = []

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        """Guarda `history` (já filtrado por `date < as_of` pelo simulador) num
        dicionário dia -> unidades. Não ajusta nenhum parâmetro de fato -- a
        "previsão" é recalculada sob demanda em `predict_quantiles` a partir
        deste dicionário.

        Confere `as_of` contra o próprio `history` recebido -- defesa própria,
        redundante com o corte que o simulador já garante, mas esta classe é
        usada de verdade em produção (ao contrário de `tests/fakes.py`), então
        não depende só de um espião de teste para pegar uma violação.
        """
        dates: list[date] = history["date"].to_list()
        units: list[float] = history["units_sold"].to_list()
        if dates and max(dates) >= as_of:
            msg = f"history contém data >= as_of: {max(dates)} >= {as_of}"
            raise AssertionError(msg)
        self._demand_by_day = dict(zip(dates, units, strict=True))
        self._sorted_dates = sorted(self._demand_by_day)

    def predict_quantiles(self, as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        """Ponto central = média móvel corrente x `horizon`; quantil `q` = ponto
        central + quantil empírico dos resíduos, com piso em 0 (demanda nunca é
        negativa). Nunca soma quantis diários -- é a demanda acumulada direto,
        conforme o contrato de `motor.forecast.base.Forecaster`.
        """
        point = self._moving_average_ending_before(as_of) * horizon
        residuals = self._backtest_residuals(horizon)

        if len(residuals) < self._min_residual_samples:
            values = [point] * len(quantiles)
        else:
            sorted_residuals = sorted(residuals)
            values = [max(0.0, point + _empirical_quantile(sorted_residuals, q)) for q in quantiles]

        return pl.DataFrame({"quantile": quantiles, "value": values})

    def _moving_average_ending_before(self, cutoff: date) -> float:
        """Média de `units_sold` nos dias em `[cutoff - window_days, cutoff)`
        presentes no histórico visível. Dia sem linha é excluído da média, não
        tratado como zero -- dado ausente não é dado zero (CLAUDE.md, seção 8).
        """
        values = [
            self._demand_by_day[d] for d in self._window_dates(cutoff) if d in self._demand_by_day
        ]
        return mean(values) if values else 0.0

    def _window_dates(self, cutoff: date) -> list[date]:
        return [cutoff - timedelta(days=i) for i in range(self._window_days, 0, -1)]

    def _backtest_residuals(self, horizon: int) -> list[float]:
        """Erros históricos da própria média móvel.

        Para cada dia `t` do histórico visível cujos `horizon` dias seguintes
        (`t` até `t + horizon - 1`) estão TODOS presentes nesse mesmo
        histórico, compara a média móvel calculada em `t` (que só olha dias
        anteriores a `t`, via `_moving_average_ending_before`) contra a
        demanda real acumulada em `t..t + horizon - 1`.

        A condição `end_inclusive > last_available: continue` é o que garante
        que nenhum resíduo usa um dia além do histórico visível. Como
        `history` já chega aqui filtrado por `date < as_of` (garantia do
        simulador -- `fit`), `last_available < as_of` sempre, e portanto todo
        `t` aceito satisfaz `t + horizon - 1 <= last_available < as_of`: o
        backtest nunca alcança `as_of` nem o ultrapassa. Ver
        `tests/test_naive.py::test_backtest_so_usa_dias_cujo_horizonte_cabe_inteiro_no_historico_visivel`
        para o teste explícito dessa borda (distinto do teste genérico de
        sem-lookahead do simulador).
        """
        if not self._sorted_dates:
            return []
        last_available = self._sorted_dates[-1]
        residuals: list[float] = []
        for t in self._sorted_dates:
            end_inclusive = t + timedelta(days=horizon - 1)
            if end_inclusive > last_available:
                continue
            window_days_needed = [t + timedelta(days=i) for i in range(horizon)]
            if not all(d in self._demand_by_day for d in window_days_needed):
                continue
            actual = sum(self._demand_by_day[d] for d in window_days_needed)
            forecast = self._moving_average_ending_before(t) * horizon
            residuals.append(actual - forecast)
        return residuals
