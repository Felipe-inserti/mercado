"""Política do braço 1 (ERP baseline, Sprint 7): pedido = média das últimas
`moving_average_weeks` semanas x `factor` menos posição de estoque, com piso num
mínimo fixo por item (`min_order_units`).

Contrato: `motor.policy.base.Policy`, grão de um par loja-item.

ARTIFÍCIO DELIBERADO -- leia antes de mexer aqui ou em `motor.policy.base`:

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

import polars as pl

from motor.policy.base import DecisionContext


class ErpBaselinePolicy:
    """Sem quantil, sem alfa, sem janela de risco derivada -- ver docstring do módulo."""

    def __init__(
        self,
        *,
        horizon_days: int,
        moving_average_weeks: int,
        factor: float,
        min_order_units: float,
    ) -> None:
        if horizon_days <= 0:
            msg = f"horizon_days deve ser positivo, recebeu {horizon_days}"
            raise ValueError(msg)
        if moving_average_weeks <= 0:
            msg = f"moving_average_weeks deve ser positivo, recebeu {moving_average_weeks}"
            raise ValueError(msg)
        if factor < 0:
            msg = f"factor não pode ser negativo, recebeu {factor}"
            raise ValueError(msg)
        if min_order_units < 0:
            msg = f"min_order_units não pode ser negativo, recebeu {min_order_units}"
            raise ValueError(msg)
        self._horizon_days = horizon_days
        self._moving_average_days = moving_average_weeks * 7
        self._factor = factor
        self._min_order_units = min_order_units

    def order(self, ctx: DecisionContext) -> float:
        """`target = mu_daily x moving_average_days x factor`; pedido = `target -
        posição`, com piso em `min_order_units` quando o pedido bruto é positivo.

        Pedido bruto <= 0 nunca vira `min_order_units`: o piso é uma
        quantidade mínima de pedido quando HÁ pedido, não um gatilho pra
        pedir sem necessidade.
        """
        mu_daily = self._median_forecast(ctx) / self._horizon_days
        target = mu_daily * self._moving_average_days * self._factor
        position = ctx.on_hand + ctx.in_transit
        order_raw = target - position

        if order_raw <= 0:
            return 0.0
        return max(order_raw, self._min_order_units)

    def _median_forecast(self, ctx: DecisionContext) -> float:
        mediana = ctx.forecast.filter(pl.col("quantile") == 0.5)
        if mediana.height != 1:
            msg = (
                "ErpBaselinePolicy exige exatamente uma linha com quantile==0.5 em "
                f"ctx.forecast (o ponto central de NaiveForecaster está sempre lá); "
                f"encontrado {mediana.height} linha(s)"
            )
            raise ValueError(msg)
        return float(mediana["value"][0])
