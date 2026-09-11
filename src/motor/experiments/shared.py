"""Premissas de simulação compartilhadas entre TODOS os braços (Sprint 7,
seção 1 da proposta aprovada). Um único lugar: qualquer assimetria aqui
contamina a comparação inteira entre braços (CLAUDE.md, seção 10 e Sprint 7).

`build_simulator_for_pair` monta um `Simulator` (Sprint 6) para um par
loja-item com:

  - horizonte de previsão = `lead_time_days + review_period_days` do
    fornecedor do item -- o contrato de `motor.forecast.base.Forecaster`;
  - calendário de revisão = revisão a cada `review_period_days` dias, a
    partir de `start` (`motor.simulator.engine.review_every_n_days`). Não usa
    `Supplier.order_days` ainda -- a interação entre os dois calendários é
    Sprint 11 (ver `motor.io.contracts.Supplier`);
  - estoque inicial = cobertura de um ciclo de risco (`initial_stock_units`,
    abaixo) -- constante experimental IDÊNTICA em todos os braços, porque a
    fórmula não depende de nenhuma política nem de nenhum forecaster, só do
    fornecedor e da demanda real observada no warmup;
  - `shelf_life_from_arrival_days=None` para todo item -- premissa
    DECLARADA: o canônico só tem `Item.is_perishable: bool`, nenhum dado de
    dias de validade. Sem isso, nenhum item expira nesta sprint, em nenhum
    braço. Revisitar quando houver dado real de shelf life.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from motor.forecast.base import Forecaster
from motor.inventory import InventoryState
from motor.policy.base import Policy
from motor.simulator.engine import Simulator, review_every_n_days


def initial_stock_units(
    demand: pl.DataFrame,
    *,
    warmup_days: int,
    lead_time_days: int,
    review_period_days: int,
    start: date,
) -> float:
    """Estoque inicial arbitrado: cobertura de um ciclo de risco (lead_time +
    review_period) na demanda média diária observada nos primeiros
    `warmup_days` dias de `demand` a partir de `start`.

    Não é uma previsão -- lê demanda REAL já ocorrida (o experimento já
    conhece o warmup inteiro de antemão, só não conta com ele nas métricas,
    igual a qualquer warmup -- CLAUDE.md, seção 6). É uma constante
    experimental, idêntica em todos os braços porque a fórmula não depende de
    nenhuma política nem de nenhum forecaster -- só do fornecedor (lead_time,
    review_period) e da demanda real do warmup.

    Sem nenhuma linha de demanda no warmup (item sem histórico ali), devolve
    0.0 -- comportamento definido, não exceção.
    """
    warmup_end = start + timedelta(days=warmup_days)  # exclusivo
    warmup_slice = demand.filter((pl.col("date") >= start) & (pl.col("date") < warmup_end))
    if warmup_slice.height == 0:
        return 0.0
    avg_daily_demand = float(warmup_slice["units_sold"].mean())  # type: ignore[arg-type]
    return avg_daily_demand * (lead_time_days + review_period_days)


def build_simulator_for_pair(
    *,
    demand: pl.DataFrame,
    forecaster: Forecaster,
    policy: Policy,
    lead_time_days: int,
    review_period_days: int,
    start: date,
    warmup_days: int,
    quantiles: list[float],
) -> Simulator:
    """Monta o `Simulator` de um par loja-item com as premissas compartilhadas
    desta sprint (ver docstring do módulo).

    `demand` precisa cobrir, no mínimo, de `start` até o fim do período que
    será simulado -- histórico anterior a `start`, se existir, deve estar
    incluído também: é dele que `Simulator._decide` monta o `history` (já
    filtrado por `date < as_of`) que o forecaster recebe em `fit`.
    """
    horizon_days = lead_time_days + review_period_days
    initial_stock = initial_stock_units(
        demand,
        warmup_days=warmup_days,
        lead_time_days=lead_time_days,
        review_period_days=review_period_days,
        start=start,
    )

    state = InventoryState(data_inicial=start - timedelta(days=1))
    if initial_stock > 0:
        state.receber(initial_stock, validade=None)

    is_review_day = review_every_n_days(reference=start, period_days=review_period_days)

    return Simulator(
        state,
        forecaster,
        policy,
        demand,
        lead_time_days=lead_time_days,
        horizon_days=horizon_days,
        quantiles=quantiles,
        is_review_day=is_review_day,
        shelf_life_from_arrival_days=None,
    )
