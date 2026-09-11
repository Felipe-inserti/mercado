"""Política de nível-alvo (Sprint 11): `compute_order_quantity`.

Lógica pura -- sem `Params`, sem I/O, sem leitura de `config/params.yaml`,
mesma disciplina de `motor.policy.supplier`. Devolve a quantidade DESEJADA
de um par loja-item, antes das regras de fornecedor: a composição com
`motor.policy.supplier.apply_supplier_constraints` (fardo, mínimo,
calendário) é da Sprint 12, que fecha o braço 2 -- antecipá-la aqui sujaria
todo valor esperado dos testes com arredondamento de fardo. Nenhuma previsão
real entra neste módulo: toda `WindowQuantileForecast` é injetada por quem
chama.

`compute_order_quantity` recebe um quarto argumento, `expected_window_days`,
além dos três do enunciado da sprint (`forecast`, `position`, `alpha`). Isso
não é invenção livre: a regra 1 abaixo exige que a política "confira que o
horizonte declarado bate com o esperado e levante erro claro se não bater" --
e o valor esperado (`lead_time_days` + o intervalo real até a próxima
entrega viável, que varia com a data de decisão -- ver a nota "janela de
risco" na docstring de `motor.io.contracts.Supplier` e `next_order_day` em
`motor.policy.supplier`) só existe em quem conhece o `Supplier`, algo que
este módulo -- deliberadamente -- não conhece. `expected_window_days` é o
único jeito de a política cumprir a regra 1 permanecendo pura.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType


@dataclass(frozen=True)
class WindowQuantileForecast:
    """Previsão de demanda ACUMULADA na janela de risco (lead_time + ciclo
    de revisão) -- nunca demanda diária, e nunca quantis diários somados: o
    q90 da soma de 11 dias é bem menor que a soma de 11 q90 diários, porque
    os erros se cancelam parcialmente (CLAUDE.md, seção 5). Somar quantis
    diários superestima o estoque de forma grosseira.

    Carregar `window_days` junto do mapeamento quantil->valor é deliberado:
    torna estruturalmente difícil passar uma previsão diária sem também
    declarar, explicitamente, para quantos dias ela vale --
    `compute_order_quantity` confere esse número contra o horizonte esperado
    (ver docstring do módulo) e recusa a previsão se não bater, em vez de
    consumir silenciosamente um valor calculado para outra janela.

    `quantiles` é validado e congelado em `__post_init__`: mapeamento
    não-vazio, toda chave estritamente em (0, 1), valores não-decrescentes
    conforme o quantil cresce (uma previsão internamente inconsistente --
    q90 menor que q70 -- é o tipo de erro que aparece se alguém montar o
    mapeamento a partir de previsões diárias não acumuladas por engano).
    Congelado via `MappingProxyType` para que ninguém mute o mapeamento
    depois de construído -- o dataclass já é `frozen`, mas isso só protege o
    atributo em si, não o dict por trás dele.
    """

    window_days: int
    quantiles: Mapping[float, float]

    def __post_init__(self) -> None:
        if self.window_days <= 0:
            msg = f"window_days deve ser positivo, recebeu {self.window_days}"
            raise ValueError(msg)
        if not self.quantiles:
            msg = "quantiles não pode ser vazio -- previsão sem nenhum quantil não é previsão"
            raise ValueError(msg)

        quantis_ordenados = sorted(self.quantiles)
        for q in quantis_ordenados:
            if not 0.0 < q < 1.0:
                msg = f"todo quantil deve satisfazer 0 < quantil < 1, recebeu {q}"
                raise ValueError(msg)

        valores_em_ordem = [self.quantiles[q] for q in quantis_ordenados]
        for anterior, atual in pairwise(valores_em_ordem):
            if atual < anterior:
                msg = (
                    f"quantiles deve ser não-decrescente conforme o quantil cresce -- "
                    f"{quantis_ordenados} produz valores {valores_em_ordem}, que não são"
                )
                raise ValueError(msg)

        object.__setattr__(self, "quantiles", MappingProxyType(dict(self.quantiles)))


@dataclass(frozen=True)
class TargetLevelDecision:
    """Saída de `compute_order_quantity`.

    `target_level` e `position_used` são guardados explicitamente, não só
    `raw_quantity`/`surplus` derivados deles: a Sprint 13 (teto de
    cobertura) e a Sprint 17 (coluna "motivo" da lista de exceções)
    precisam dos dois números separados, e reconstruí-los depois (a partir
    só de `raw_quantity`) é onde entra bug -- mesmo raciocínio de
    `SupplierOrderResult` em `motor.policy.supplier`.

    `surplus` é o valor NEGATIVO original (`target_level - position`) quando
    a posição excede o alvo -- não descartado, é o sinal de capital preso.
    Quando não há excedente, `surplus == 0.0`.
    """

    target_level: float
    position_used: float
    raw_quantity: float
    surplus: float
    alpha: float


def compute_order_quantity(
    forecast: WindowQuantileForecast,
    position: float,
    alpha: float,
    *,
    expected_window_days: int,
) -> TargetLevelDecision:
    """Nível-alvo: `target_level = quantil alpha da demanda acumulada na
    janela`; `raw_quantity = max(0, target_level - position)`.

    Regras não-negociáveis (Sprint 11):

    1. A janela é lead_time + ciclo de revisão, nunca só o lead time -- mas
       esta função não a calcula, só confere: `forecast.window_days` tem
       que bater com `expected_window_days` (calculado por quem chama, que
       conhece o `Supplier` -- ver docstring do módulo), senão levanta erro
       claro em vez de consumir uma previsão calculada para outra janela.
    2. `position` vem PRONTA de `InventoryState.posicao()` (on_hand +
       in_transit) -- não recalculada aqui. Isso é o que faz o pedido em
       trânsito com chegada POSTERIOR ao fim da janela de risco ainda
       contar integralmente: `posicao()` não sabe nem deveria saber a data
       de chegada de cada lote (ela soma TODO o pipeline, ver sua
       docstring). Para revisão periódica isso é a decisão certa, não um
       descuido -- excluir esse lote geraria pedido duplicado na revisão
       seguinte, porque ele de qualquer forma vai chegar e reduzir a
       necessidade futura de estoque. `compute_order_quantity` não tem
       (nem deveria ter) como distinguir os dois casos, e não tenta --
       ver `tests/test_target_level.py`, que fixa essa equivalência com
       dois cenários idênticos exceto pela data de chegada.
    3. `0 < alpha < 1`; `alpha == 1.0` é rejeitado explicitamente. Com
       quantis empíricos, alpha=1.0 devolve o máximo histórico em silêncio
       -- um comportamento surpreendente demais para deixar passar sem
       erro.
    4. `alpha` entra como argumento, sempre. Quem deriva de
       custo_de_faltar / (custo_de_faltar + custo_de_sobrar) é a camada de
       config (Sprint 8+), nunca esta função.

    Levanta `ValueError` também quando `alpha` não é uma chave presente em
    `forecast.quantiles` -- a política não interpola entre quantis vizinhos
    nesta sprint; consumir o quantil mais próximo em silêncio seria o mesmo
    tipo de falha silenciosa que a regra 1 proíbe para a janela.
    """
    if alpha == 1.0:
        msg = (
            "alpha=1.0 é rejeitado explicitamente: com quantis empíricos, "
            "devolveria o máximo histórico em silêncio."
        )
        raise ValueError(msg)
    if not 0.0 < alpha < 1.0:
        msg = f"alpha deve satisfazer 0 < alpha < 1, recebeu {alpha}"
        raise ValueError(msg)

    if forecast.window_days != expected_window_days:
        msg = (
            f"forecast.window_days ({forecast.window_days}) não bate com o horizonte "
            f"esperado ({expected_window_days}) -- previsão calculada para outra janela "
            "de risco não pode ser consumida aqui."
        )
        raise ValueError(msg)

    if alpha not in forecast.quantiles:
        msg = (
            f"alpha={alpha} não está entre os quantis fornecidos pela previsão "
            f"({sorted(forecast.quantiles)})"
        )
        raise ValueError(msg)

    target_level = forecast.quantiles[alpha]
    raw_diff = target_level - position
    raw_quantity = max(0.0, raw_diff)
    surplus = min(0.0, raw_diff)

    return TargetLevelDecision(
        target_level=target_level,
        position_used=position,
        raw_quantity=raw_quantity,
        surplus=surplus,
        alpha=alpha,
    )
