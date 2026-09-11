"""Política de nível-alvo, no grão de um par loja-item (Sprint 12).

`motor.policy.target_level.compute_order_quantity` (Sprint 11) é lógica pura,
sem `DecisionContext`, sem `Policy` -- foi construída assim de propósito para
não depender do loop do simulador. `BasestockPolicy` é o elo que faltava para
o braço 2 rodar de verdade: implementa `motor.policy.base.Policy`, converte
`ctx.forecast` (a tabela `quantile`/`value` que `Forecaster.predict_quantiles`
devolve) num `WindowQuantileForecast` e delega a `compute_order_quantity`.

Nenhuma regra nova mora aqui -- é só o adaptador de tipos entre o grão do
simulador e a função pura da Sprint 11.
"""

from __future__ import annotations

from motor.policy.base import DecisionContext
from motor.policy.target_level import WindowQuantileForecast, compute_order_quantity


class BasestockPolicy:
    """Contrato `Policy`: nível-alvo = quantil `alpha` da demanda acumulada
    na janela de risco, via `compute_order_quantity`.

    LIMITAÇÃO CONHECIDA, não descuido: a regra 1 de `compute_order_quantity`
    (confere `forecast.window_days` contra `expected_window_days`) NUNCA
    dispara através deste adaptador. `ctx.forecast` (protocolo `Forecaster`
    reduzido ao par, Sprint 6) não carrega nenhum metadado de janela -- só
    `quantile`/`value` -- então `order()` constrói `WindowQuantileForecast`
    com `window_days=self._expected_window_days`, o MESMO valor que passa
    para `expected_window_days` em `compute_order_quantity`: os dois lados
    da comparação são sempre o mesmo número, por construção. A garantia real
    de que `ctx.forecast` de fato representa a janela certa vem de fora --
    de quem constrói o par `(Forecaster, Policy)` com o mesmo `horizon_days`
    para os dois (`motor.experiments.shared.build_simulator_for_pair` e
    `motor.experiments.run._build_policy`/`_build_forecaster`, que derivam
    `horizon_days` de uma única variável e a repassam para ambos). Um erro de
    wiring que desalinhasse os dois lados não seria pego aqui.
    """

    def __init__(self, *, alpha: float, expected_window_days: int) -> None:
        self._alpha = alpha
        self._expected_window_days = expected_window_days

    def order(self, ctx: DecisionContext) -> float:
        forecast = WindowQuantileForecast(
            window_days=self._expected_window_days,
            quantiles=dict(
                zip(
                    ctx.forecast["quantile"].to_list(),
                    ctx.forecast["value"].to_list(),
                    strict=True,
                )
            ),
        )
        position = ctx.on_hand + ctx.in_transit
        decision = compute_order_quantity(
            forecast,
            position,
            self._alpha,
            expected_window_days=self._expected_window_days,
        )
        return decision.raw_quantity
