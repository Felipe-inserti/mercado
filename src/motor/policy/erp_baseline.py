"""Política do braço 1 (ERP baseline, Sprint 7): pedido = média das últimas
`moving_average_weeks` semanas x `factor` menos posição de estoque, com piso num
mínimo fixo por item (`min_order_units`).

Contrato: `motor.policy.base.Policy`, grão de um par loja-item.

MUDANÇA DA SPRINT 24 (etapa 24.5) -- o artifício abaixo deixou de existir:

A política não lê mais o forecast. Ela recebe `daily_average: Callable[[date],
float]` no construtor -- a média diária das últimas `moving_average_weeks`
semanas ANTES de `as_of` -- e a chama com `ctx.as_of`. Quem monta a política
calcula essa média sobre o histórico já CENSURADO (`moving_average_daily`,
`daily_average_from_history`), o mesmo que o forecaster do par recebe. Motivos:
(1) o braço 1 passa a não depender de qual `Forecaster` roda ao lado dele --
trocar a previsão (naive, estatística, GBM) não muda mais o pedido do ERP, o
que deixa a comparação do backtest honesta; (2) sai `_median_forecast`, a
dependência do quantil 0,5 e o `horizon_days` do construtor, que só existiam
para desfazer a escala do horizonte. O contrato `Policy`, `DecisionContext` e
`engine.py` seguem intactos. EFEITO NUMÉRICO: a mediana do `NaiveForecaster` era
`media x horizonte` MAIS o quantil 0,5 dos resíduos (não exatamente zero), então
o pedido do braço 1 pode diferir levemente do de antes da Sprint 24; a
regressão do Favorita mede essa diferença.

ARTIFÍCIO DELIBERADO (Sprint 7, HISTÓRICO -- mantido pelo raciocínio, não mais
em vigor) -- leia antes de mexer aqui ou em `motor.policy.base`:

`DecisionContext.forecast` só carrega a demanda ACUMULADA no horizonte de
risco (lead_time + review_period) -- é o contrato de `motor.forecast.base.Forecaster`,
e não muda por causa desta política. Só que um ERP honesto NÃO deriva o
pedido da janela de risco -- essa é justamente a diferença central para o
braço de nível-alvo de sprint futura: ele olha a média móvel de venda diária
e multiplica por um fator plano, sem lead time, sem review period, sem
quantil de risco.

Pra recuperar essa média diária sem tocar em `DecisionContext`, no protocolo
`Policy` nem em `engine.py` (fora de escopo desta sprint por decisão
explícita), a política lê o valor MEDIANO do forecast (`quantile == 0.5` --
o ponto central de `motor.forecast.naive.NaiveForecaster`, não uma escolha de
risco) e desfaz a escala do horizonte dividindo por `horizon_days`:

    mu_daily = mediana / horizon_days

Como o próprio `NaiveForecaster` constrói a mediana como
`media_movel_diaria x horizon_days` mais um resíduo empírico pequeno (perto
de zero pra uma distribuição sem viés forte -- ver `motor.forecast.naive`),
essa divisão cancela o horizonte de risco e devolve, na prática, a mesma taxa
diária que a média móvel do forecaster já calculava -- sem esta política
precisar enxergar o histórico bruto de vendas. O resultado final NÃO escala
com lead time nem review period: é exatamente o contraste que esta sprint
pede (`ErpBaselinePolicy` "sem janela de risco derivada" vs. o braço de
nível-alvo, que deriva dela).

`horizon_days` e `moving_average_weeks` são passados no construtor (mesmo
padrão de `tests/fakes.py::OrderUpToPolicy`). `moving_average_weeks` tem que
ser o MESMO valor usado para construir o `NaiveForecaster` deste par --
`config/params.yaml`, seção `forecast_naive`, é compartilhada entre os dois
de propósito (ver comentário lá).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from statistics import mean

import polars as pl

from motor.features.censoring import drop_censored
from motor.policy.base import DecisionContext

_DAYS_PER_WEEK = 7


def moving_average_daily(history: pl.DataFrame, as_of: date, weeks: int) -> float:
    """Média diária de `units_sold` nos dias de `[as_of - 7*weeks, as_of)`
    presentes em `history` (colunas `date`, `units_sold`).

    Pura. Dia sem linha é excluído da média, não tratado como zero (dado
    ausente não é dado zero, CLAUDE.md, seção 8) -- mesma regra do
    `NaiveForecaster`. Sem nenhum dia na janela: 0.0, comportamento definido.
    O chamador passa o histórico JÁ censurado; linhas com `date >= as_of` são
    ignoradas por construção (a janela é aberta em `as_of`).
    """
    if weeks <= 0:
        msg = f"weeks deve ser positivo, recebeu {weeks}"
        raise ValueError(msg)
    window_start = as_of - timedelta(days=weeks * _DAYS_PER_WEEK)
    window = history.filter((pl.col("date") >= window_start) & (pl.col("date") < as_of))
    values: list[float] = window["units_sold"].to_list()
    return mean(values) if values else 0.0


def daily_average_from_history(
    demand: pl.DataFrame, weeks: int, censoring_flags: pl.DataFrame | None = None
) -> Callable[[date], float]:
    """Monta o `daily_average` de `ErpBaselinePolicy` para UM par loja-item.

    `demand`: colunas `date`, `units_sold`. Os dias marcados em
    `censoring_flags` (formato de `flags_for_item`) saem UMA vez, aqui; a flag
    de um dia só depende do passado dele, então remover todos de uma vez não
    vaza futuro. A função devolvida só enxerga `date < as_of` (corte dentro de
    `moving_average_daily`), o mesmo recorte que o simulador entrega ao forecaster.
    """
    history = drop_censored(demand, censoring_flags) if censoring_flags is not None else demand
    return lambda as_of: moving_average_daily(history, as_of, weeks)


class ErpBaselinePolicy:
    """Sem quantil, sem alfa, sem janela de risco derivada -- ver docstring do módulo."""

    def __init__(
        self,
        *,
        daily_average: Callable[[date], float],
        moving_average_weeks: int,
        factor: float,
        min_order_units: float,
    ) -> None:
        if moving_average_weeks <= 0:
            msg = f"moving_average_weeks deve ser positivo, recebeu {moving_average_weeks}"
            raise ValueError(msg)
        if factor < 0:
            msg = f"factor não pode ser negativo, recebeu {factor}"
            raise ValueError(msg)
        if min_order_units < 0:
            msg = f"min_order_units não pode ser negativo, recebeu {min_order_units}"
            raise ValueError(msg)
        self._daily_average = daily_average
        self._moving_average_days = moving_average_weeks * _DAYS_PER_WEEK
        self._factor = factor
        self._min_order_units = min_order_units

    def order(self, ctx: DecisionContext) -> float:
        """`target = mu_daily x moving_average_days x factor`; pedido = `target -
        posição`, com piso em `min_order_units` quando o pedido bruto é positivo.
        `mu_daily = daily_average(ctx.as_of)`; `ctx.forecast` não é lido.

        Pedido bruto <= 0 nunca vira `min_order_units`: o piso é uma
        quantidade mínima de pedido quando HÁ pedido, não um gatilho pra
        pedir sem necessidade.
        """
        mu_daily = self._daily_average(ctx.as_of)
        target = mu_daily * self._moving_average_days * self._factor
        position = ctx.on_hand + ctx.in_transit
        order_raw = target - position

        if order_raw <= 0:
            return 0.0
        return max(order_raw, self._min_order_units)
