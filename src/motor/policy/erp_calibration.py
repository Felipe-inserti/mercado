"""Calibração de `factor` e `min_order_units` de
`motor.policy.erp_baseline.ErpBaselinePolicy` (Sprint 7).

Critério aprovado na revisão da sprint -- não escolhido sozinho, CLAUDE.md
seção 10: meta de nível de serviço de 95%. Varre `factor` e `min_order_units`
numa grade, roda o `Simulator` real (Sprint 6; sem métrica em R$, isso é
Sprint 8) sobre uma janela de calibração para cada item, e escolhe:

  - entre as configurações cuja fill rate agregada (`sum(sold)/sum(demand)`,
    medida só depois do warmup) atinge a meta: a de menor estoque médio
    agregado (`avg_on_hand`);
  - se NENHUMA atinge a meta: a de maior fill rate, com `target_met=False`
    no resultado -- nunca escolhe em silêncio uma configuração que não bate
    a meta sem marcar isso.

Empate resolvido pela ordem da grade (`min`/`max` do Python são estáveis):
determinístico, sem julgamento manual (ajuste pedido na revisão da sprint).

Otimização deliberada: o forecast de `NaiveForecaster` não depende de qual
combinação de `factor`/`min_order_units` está sendo testada -- só do
histórico real de vendas e da data de decisão. `_precompute_forecasts`
calcula, uma vez por item, o forecast em cada data de revisão (com um
`NaiveForecaster` de verdade, replicando exatamente o que `Simulator._decide`
faria); `_PrecomputedForecaster` devolve esse cache no lugar de recalcular a
cada combinação da grade. Sem isso, a varredura real (Sprint 7, etapa d) não
termina em tempo hábil -- `len(factor_grid) x len(min_order_grid)` reexecuções
do mesmo backtest de resíduos por item seria puro desperdício, já que o
resultado é idêntico em todas elas.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

import polars as pl

from motor.experiments.shared import build_simulator_for_pair
from motor.forecast.naive import NaiveForecaster
from motor.policy.erp_baseline import ErpBaselinePolicy
from motor.simulator.engine import review_every_n_days


@dataclass(frozen=True)
class CalibrationItem:
    """Um par loja-item pronto pra calibração.

    `demand` cobre TODO o histórico disponível até `end` (não só a janela de
    calibração) -- é dele que o forecast de cada data de revisão deriva seu
    histórico, igual ao braço real (Sprint 7, seção 1 da proposta aprovada).
    """

    item_id: str
    demand: pl.DataFrame  # colunas: date, units_sold
    lead_time_days: int
    review_period_days: int


@dataclass(frozen=True)
class GridResult:
    """Resultado agregado (todos os itens, período pós-warmup) de uma combinação da grade."""

    factor: float
    min_order_units: float
    fill_rate: float
    avg_on_hand: float


@dataclass(frozen=True)
class CalibrationResult:
    grid: tuple[GridResult, ...]
    chosen: GridResult
    target_service_level: float
    target_met: bool


class _PrecomputedForecaster:
    """Forecaster de cache: os `predict_quantiles` já foram calculados, uma
    vez por item, com um `NaiveForecaster` de verdade (`_precompute_forecasts`).

    `fit` não faz nada -- o cache já reflete o corte `date < as_of` do
    `NaiveForecaster` real que o gerou (ver docstring do módulo).
    """

    def __init__(self, cache: dict[date, pl.DataFrame]) -> None:
        self._cache = cache

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        del history, as_of  # nada a fazer -- ver docstring da classe

    def predict_quantiles(self, as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        del horizon, quantiles  # já embutidos no cache calculado com os valores reais
        if as_of not in self._cache:
            msg = (
                f"_PrecomputedForecaster sem cache para as_of={as_of} -- grade de "
                "revisão do simulador incompatível com a usada no pré-cálculo"
            )
            raise KeyError(msg)
        return self._cache[as_of]


def _review_dates(start: date, end: date, review_period_days: int) -> list[date]:
    is_review_day = review_every_n_days(reference=start, period_days=review_period_days)
    dates: list[date] = []
    day = start
    while day <= end:
        if is_review_day(day):
            dates.append(day)
        day += timedelta(days=1)
    return dates


def _precompute_forecasts(
    demand: pl.DataFrame,
    *,
    start: date,
    end: date,
    review_period_days: int,
    horizon_days: int,
    moving_average_weeks: int,
    min_residual_samples: int,
    quantiles: list[float],
) -> dict[date, pl.DataFrame]:
    forecaster = NaiveForecaster(moving_average_weeks, min_residual_samples)
    cache: dict[date, pl.DataFrame] = {}
    for as_of in _review_dates(start, end, review_period_days):
        history = demand.filter(pl.col("date") < as_of)
        forecaster.fit(history, as_of=as_of)
        cache[as_of] = forecaster.predict_quantiles(as_of, horizon_days, quantiles)
    return cache


def _run_one_combination(
    items: Sequence[CalibrationItem],
    forecast_cache_by_item: dict[str, dict[date, pl.DataFrame]],
    *,
    factor: float,
    min_order_units: float,
    moving_average_weeks: int,
    start: date,
    end: date,
    warmup_days: int,
    quantiles: list[float],
) -> GridResult:
    evaluation_start = start + timedelta(days=warmup_days)
    total_sold = 0.0
    total_demand = 0.0
    on_hand_values: list[float] = []

    for item in items:
        horizon_days = item.lead_time_days + item.review_period_days
        forecaster = _PrecomputedForecaster(forecast_cache_by_item[item.item_id])
        policy = ErpBaselinePolicy(
            horizon_days=horizon_days,
            moving_average_weeks=moving_average_weeks,
            factor=factor,
            min_order_units=min_order_units,
        )
        simulator = build_simulator_for_pair(
            demand=item.demand,
            forecaster=forecaster,
            policy=policy,
            lead_time_days=item.lead_time_days,
            review_period_days=item.review_period_days,
            start=start,
            warmup_days=warmup_days,
            quantiles=quantiles,
        )
        events = simulator.run(start, end)
        evaluated = [e for e in events if e.day >= evaluation_start]
        total_sold += sum(e.sold for e in evaluated)
        total_demand += sum(e.demand for e in evaluated)
        on_hand_values.extend(e.on_hand_end for e in evaluated)

    fill_rate = total_sold / total_demand if total_demand > 0 else 1.0
    avg_on_hand = mean(on_hand_values) if on_hand_values else 0.0
    return GridResult(
        factor=factor,
        min_order_units=min_order_units,
        fill_rate=fill_rate,
        avg_on_hand=avg_on_hand,
    )


def _choose(grid: Sequence[GridResult], target_service_level: float) -> tuple[GridResult, bool]:
    """Entre as configurações com `fill_rate >= target_service_level`, a de
    menor `avg_on_hand`. Se nenhuma atinge a meta, a de maior `fill_rate`.

    `min`/`max` do Python são estáveis: em empate, fica a PRIMEIRA encontrada
    na ordem de `grid` -- determinístico, sem julgamento manual (ajuste
    pedido na revisão da sprint).
    """
    meeting_target = [g for g in grid if g.fill_rate >= target_service_level]
    if meeting_target:
        return min(meeting_target, key=lambda g: g.avg_on_hand), True
    return max(grid, key=lambda g: g.fill_rate), False


def sweep_erp_baseline(
    items: Sequence[CalibrationItem],
    *,
    start: date,
    end: date,
    warmup_days: int,
    moving_average_weeks: int,
    min_residual_samples: int,
    quantiles: list[float],
    factor_grid: Sequence[float],
    min_order_grid: Sequence[float],
    target_service_level: float,
) -> CalibrationResult:
    """Varre `factor_grid x min_order_grid`, roda o `Simulator` real por item
    em cada combinação (janela `[start, end]`, warmup `warmup_days`
    descartado da leitura -- ver docstring do módulo) e escolhe a combinação
    conforme `_choose`.
    """
    if not items:
        msg = "sweep_erp_baseline precisa de ao menos um item"
        raise ValueError(msg)
    if not factor_grid or not min_order_grid:
        msg = "factor_grid e min_order_grid precisam ter ao menos um valor"
        raise ValueError(msg)

    forecast_cache_by_item = {
        item.item_id: _precompute_forecasts(
            item.demand,
            start=start,
            end=end,
            review_period_days=item.review_period_days,
            horizon_days=item.lead_time_days + item.review_period_days,
            moving_average_weeks=moving_average_weeks,
            min_residual_samples=min_residual_samples,
            quantiles=quantiles,
        )
        for item in items
    }

    grid = [
        _run_one_combination(
            items,
            forecast_cache_by_item,
            factor=factor,
            min_order_units=min_order_units,
            moving_average_weeks=moving_average_weeks,
            start=start,
            end=end,
            warmup_days=warmup_days,
            quantiles=quantiles,
        )
        for factor in factor_grid
        for min_order_units in min_order_grid
    ]

    chosen, target_met = _choose(grid, target_service_level)
    return CalibrationResult(
        grid=tuple(grid),
        chosen=chosen,
        target_service_level=target_service_level,
        target_met=target_met,
    )
