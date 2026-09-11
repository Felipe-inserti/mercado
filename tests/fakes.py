"""Fakes para os testes do simulador: previsão e política de mentira.

`ConstantForecaster`, `SpyForecaster` e `OrderUpToPolicy` não são
implementações reais (isso é sprint futura). Existem só para provar a
corretude do loop diário (`motor.simulator.engine.Simulator`) contra um
cenário analiticamente conhecido -- CLAUDE.md, seção 6.

Ficam em `tests/` de propósito: nenhum código fora de teste usa isto hoje.
Se algum dia surgir um uso real fora de teste, movem para `src/motor/forecast`
e `src/motor/policy` -- não antes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import polars as pl

from motor.inventory import InventoryState
from motor.policy.base import DecisionContext
from motor.simulator.engine import Simulator, review_every_n_days


class ConstantForecaster:
    """Previsão de mentira: demanda diária constante, acumulada no horizonte.

    Implementa `Forecaster` (`motor.forecast.base`) sem olhar `history` de
    fato -- existe só para o loop ter alguém para chamar.
    """

    def __init__(self, demand_per_day: float) -> None:
        self._demand_per_day = demand_per_day

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        pass

    def predict_quantiles(self, _as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        value = self._demand_per_day * horizon
        return pl.DataFrame({"quantile": quantiles, "value": [value] * len(quantiles)})


@dataclass
class SpyForecaster:
    """Previsão de mentira que registra cada chamada, para provar a garantia
    de "sem lookahead" do simulador (CLAUDE.md, seção 8: vazamento por
    histórico global).

    Levanta `AssertionError` se algum dia receber, em `history`, uma linha
    com `date >= as_of` -- é essa falha que o teste de lookahead verifica.
    """

    demand_per_day: float
    as_of_calls: list[date] = field(default_factory=list, init=False)
    max_history_date_seen: date | None = field(default=None, init=False)

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        self.as_of_calls.append(as_of)
        if history.height == 0:
            return
        max_date = history["date"].max()
        assert isinstance(max_date, date)
        if max_date >= as_of:
            msg = f"history contém data >= as_of: {max_date} >= {as_of}"
            raise AssertionError(msg)
        if self.max_history_date_seen is None or max_date > self.max_history_date_seen:
            self.max_history_date_seen = max_date

    def predict_quantiles(self, _as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        value = self.demand_per_day * horizon
        return pl.DataFrame({"quantile": quantiles, "value": [value] * len(quantiles)})


class OrderUpToPolicy:
    """Política de mentira: pede até completar o nível-alvo `S` (order-up-to).

    Implementa `Policy` (`motor.policy.base`). Não olha `ctx.forecast` -- `S`
    é fixo, passado no construtor. É a política real de sprint futura
    (nível-alvo por quantil) que deriva `S` da previsão; esta versão só
    prova que o loop trata posição (em mãos + em trânsito) corretamente.
    """

    def __init__(self, target_level: float) -> None:
        self._target_level = target_level

    def order(self, ctx: DecisionContext) -> float:
        position = ctx.on_hand + ctx.in_transit
        return max(0.0, self._target_level - position)


@dataclass(frozen=True)
class AnalyticScenario:
    """Cenário de demanda constante + política order-up-to, com resultado
    conhecido em forma fechada.

    Ver a derivação completa em `tests/test_simulator.py`. Reutilizado pela
    sprint que confere métricas financeiras contra cálculo manual -- import
    esta função lá, não recrie o cenário.
    """

    simulator: Simulator
    start: date
    end: date
    daily_demand: float
    lead_time_days: int
    review_period_days: int
    target_level: float

    @property
    def expected_order_per_review(self) -> float:
        """Em regime permanente, cada revisão pede exatamente d x R."""
        return self.daily_demand * self.review_period_days

    @property
    def expected_average_on_hand(self) -> float:
        """d x (R + 1) / 2 em regime permanente.

        Não é d x R / 2: essa é a aproximação contínua, e o loop discreto
        (CLAUDE.md, seção 6: recebimento acontece ANTES da demanda do mesmo
        dia) desloca o resultado exato em d / 2. Ver a derivação completa,
        passo a passo, em `test_simulator.py`.
        """
        return self.daily_demand * (self.review_period_days + 1) / 2


def build_analytic_scenario(
    *,
    daily_demand: float,
    lead_time_days: int,
    review_period_days: int,
    total_days: int,
    slack: float = 0.0,
    start: date = date(2026, 1, 1),
    quantiles: list[float] | None = None,
) -> AnalyticScenario:
    """Monta o cenário d, L, R, S = d x (L + R) + `slack`, pronto para `simulator.run`.

    `slack` soma um deslocamento fixo `f` sobre o nível-alvo `S` -- usado
    pelo teste que confirma que a folga aparece como deslocamento no estoque
    médio, não como escala.

    O estado inicial começa vazio (sem estoque, sem pipeline) em
    `start - 1 dia`; por isso os primeiros ciclos de revisão têm ruptura --
    quem chama deve descartar esse período de aquecimento antes de medir
    (CLAUDE.md, seção 6). `total_days`, a partir de `start`, define até onde
    a tabela de demanda é construída (e portanto até onde `run` pode ir).
    """
    target_level = daily_demand * (lead_time_days + review_period_days) + slack
    horizon_days = lead_time_days + review_period_days
    resolved_quantiles = quantiles if quantiles is not None else [0.5]

    end = start + timedelta(days=total_days - 1)
    dates = [start + timedelta(days=i) for i in range(total_days)]
    demand_table = pl.DataFrame({"date": dates, "units_sold": [daily_demand] * total_days})

    state = InventoryState(data_inicial=start - timedelta(days=1))
    forecaster = ConstantForecaster(daily_demand)
    policy = OrderUpToPolicy(target_level)
    is_review_day = review_every_n_days(reference=start, period_days=review_period_days)

    simulator = Simulator(
        state,
        forecaster,
        policy,
        demand_table,
        lead_time_days=lead_time_days,
        horizon_days=horizon_days,
        quantiles=resolved_quantiles,
        is_review_day=is_review_day,
        shelf_life_from_arrival_days=None,
    )

    return AnalyticScenario(
        simulator=simulator,
        start=start,
        end=end,
        daily_demand=daily_demand,
        lead_time_days=lead_time_days,
        review_period_days=review_period_days,
        target_level=target_level,
    )
