"""Loop diário do simulador, para um único par loja-item (CLAUDE.md, seção 6).

Ordem fixa dentro de cada dia, não alterável:

    recebimento -> demanda -> atendimento -> envelhecimento/expiração -> decisão -> registro

Esta sprint injeta previsão e política de mentira (`ConstantForecaster`,
`OrderUpToPolicy` em `tests/fakes.py`) -- nenhuma previsão real, nenhuma
política real, nenhum I/O e nenhuma config aqui. `Forecaster` e `Policy` são
os protocolos reduzidos ao par loja-item (`motor.forecast.base`,
`motor.policy.base`); ver a emenda em CLAUDE.md, seção 5, para a relação com
o consolidador por fornecedor de sprints futuras.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from motor.forecast.base import Forecaster
from motor.inventory import InventoryState
from motor.policy.base import DecisionContext, Policy


@dataclass(frozen=True)
class DailyEvent:
    """Um dia de simulação, registrado depois que todos os passos do loop ocorreram.

    `on_hand_start`/`in_transit_start` são a posição no INÍCIO do dia, antes
    do recebimento -- ou seja, exatamente o saldo final do dia anterior.
    `on_hand_end`/`in_transit_end` são o saldo depois de recebimento,
    atendimento, expiração e decisão (a decisão só move `in_transit_end` via
    `agendar_pedido`; nunca `on_hand_end`).

    `order_placed` distingue dois casos que, sem essa distinção, ficariam
    indistinguíveis depois: `None` significa "não era dia de revisão" (a
    política nem foi chamada); `0.0` significa "revisou e decidiu pedir
    zero". Essa distinção é o que permite auditar depois a taxa de revisão
    separadamente da taxa de pedido zero -- colapsar os dois em `0.0` sempre
    esconderia quantos dias o simulador de fato revisou.
    """

    day: date
    on_hand_start: float
    in_transit_start: float
    demand: float
    sold: float
    unmet_demand: float
    expired: float
    order_placed: float | None
    on_hand_end: float
    in_transit_end: float


def review_every_n_days(reference: date, period_days: int) -> Callable[[date], bool]:
    """Calendário de revisão: verdadeiro a cada `period_days` dias, a partir de `reference`."""
    if period_days <= 0:
        msg = f"period_days deve ser positivo, recebeu {period_days}"
        raise ValueError(msg)

    def _is_review_day(day: date) -> bool:
        return (day - reference).days % period_days == 0

    return _is_review_day


def review_on_weekdays(iso_weekdays: Sequence[int]) -> Callable[[date], bool]:
    """Calendário de revisão: dias fixos da semana (ISO, 1=segunda .. 7=domingo)."""
    allowed = set(iso_weekdays)

    def _is_review_day(day: date) -> bool:
        return day.isoweekday() in allowed

    return _is_review_day


def _in_transit(state: InventoryState) -> float:
    """Unidades em trânsito: posição total menos o que já está em mãos.

    `InventoryState` expõe `posicao()` (em mãos + em trânsito) e `em_maos()`,
    mas não a diferença entre os dois diretamente. Centralizar a subtração
    aqui, com teste próprio, evita repeti-la ad-hoc em cada lugar que monta
    um `DecisionContext` -- é exatamente esse tipo de subtração implícita
    espalhada que faz o bug do pipeline ignorado nascer (CLAUDE.md, seção 5).
    """
    return state.posicao() - state.em_maos()


class Simulator:
    """Loop diário do simulador, para um único par loja-item."""

    def __init__(
        self,
        state: InventoryState,
        forecaster: Forecaster,
        policy: Policy,
        demand: pl.DataFrame,
        *,
        lead_time_days: int,
        horizon_days: int,
        quantiles: list[float],
        is_review_day: Callable[[date], bool],
        shelf_life_from_arrival_days: int | None,
    ) -> None:
        """
        `demand`: tabela verdade com colunas `date`, `units_sold` -- a
        demanda real de cada dia, vinda dos dados (o simulador nunca a
        calcula). Usada tanto para o atendimento diário quanto como o
        histórico que `forecaster.fit` recebe, já filtrado por `date < as_of`.

        `shelf_life_from_arrival_days`: premissa DECLARADA, não medida --
        todo lote recebido é tratado como "novo" na data de chegada, com
        validade = data de chegada + este valor (`None` = item não
        perecível, sem validade). Um lote pode ter sido fabricado bem antes
        de chegar ao ponto de recebimento; sem dado de fabricação, esta é a
        premissa mais simples que se pode declarar de forma explícita, em
        vez de escondê-la atrás de um cálculo qualquer.
        """
        self._state = state
        self._forecaster = forecaster
        self._policy = policy
        self._demand_table = demand
        dates: list[date] = demand["date"].to_list()
        units: list[float] = demand["units_sold"].to_list()
        self._demand_by_day: dict[date, float] = dict(zip(dates, units, strict=True))
        self._lead_time_days = lead_time_days
        self._horizon_days = horizon_days
        self._quantiles = quantiles
        self._is_review_day = is_review_day
        self._shelf_life_from_arrival_days = shelf_life_from_arrival_days

    def run(self, start: date, end: date) -> list[DailyEvent]:
        """Roda o loop de `start` a `end` (inclusive), um evento por dia.

        Não há caso especial para o "dia 0": todo dia simulado passa pelos
        mesmos cinco passos, incluindo o primeiro -- `start` precisa ser
        exatamente um dia depois da data corrente do estado recebido no
        construtor (`InventoryState.avancar_para` já recusa data não
        posterior; deixamos esse erro se propagar em vez de duplicar a
        validação aqui).
        """
        events: list[DailyEvent] = []
        day = start
        while day <= end:
            events.append(self._run_one_day(day))
            day += timedelta(days=1)
        return events

    def _run_one_day(self, day: date) -> DailyEvent:
        on_hand_start = self._state.em_maos()
        in_transit_start = _in_transit(self._state)

        self._state.avancar_para(day)  # 1. recebimento

        demand = self._demand_by_day[day]  # 2. demanda do dia
        sold = self._state.consumir(demand)  # 3. atendimento
        unmet_demand = demand - sold

        expired = self._state.expirar()  # 4. envelhecimento/expiração

        order_placed: float | None = None
        if self._is_review_day(day):  # 5. decisão
            order_placed = self._decide(day)

        # 6. registro
        return DailyEvent(
            day=day,
            on_hand_start=on_hand_start,
            in_transit_start=in_transit_start,
            demand=demand,
            sold=sold,
            unmet_demand=unmet_demand,
            expired=expired,
            order_placed=order_placed,
            on_hand_end=self._state.em_maos(),
            in_transit_end=_in_transit(self._state),
        )

    def _decide(self, day: date) -> float:
        """Monta o `DecisionContext`, chama a política e agenda o pedido, se houver."""
        history = self._demand_table.filter(pl.col("date") < day)
        self._forecaster.fit(history, as_of=day)
        forecast = self._forecaster.predict_quantiles(day, self._horizon_days, self._quantiles)

        ctx = DecisionContext(
            as_of=day,
            on_hand=self._state.em_maos(),
            in_transit=_in_transit(self._state),
            forecast=forecast,
        )
        quantity = self._policy.order(ctx)

        if quantity > 0:
            arrival = day + timedelta(days=self._lead_time_days)
            validity = (
                arrival + timedelta(days=self._shelf_life_from_arrival_days)
                if self._shelf_life_from_arrival_days is not None
                else None
            )
            self._state.agendar_pedido(quantity, data_chegada=arrival, validade=validity)

        return quantity
