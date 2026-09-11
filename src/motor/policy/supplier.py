"""Restrição de fornecedor (Sprint 10): calendário de pedido, fardo, pedido
mínimo e preenchimento -- lógica pura, sem estatística, sem tocar no loop do
simulador.

`apply_supplier_constraints` recebe um vetor de quantidades DESEJADAS por item
(quem o produz é a Sprint 11 -- aqui é entrada, não previsão nem nível-alvo),
a posição de estoque, a demanda diária esperada (necessária pro passo 4,
cobertura -- não estava no parágrafo de abertura do enunciado da sprint, mas o
cálculo de cobertura não fecha sem ela), as regras do fornecedor
(`motor.io.contracts.Supplier`) e a data de decisão, e devolve o pedido
EXECUTÁVEL por fornecedor mais o registro estruturado de cada ajuste.

Ordem de aplicação, fixa (Sprint 10, não alterar sem reabrir o desenho):

1. calendário de dias de pedido (`Supplier.order_days`) -- fora do calendário,
   pedido vazio, `OrderOutcome.FORA_DO_CALENDARIO`, sem `OrderAdjustment`;
2. arredondamento de fardo, sempre para cima (`Item.pack_multiple` -- a
   mesma grandeza do item, sem campo de conversão separado: um item vendido
   por peso com `pack_multiple=5.0` só compra em caixas de 5kg, e a conta é
   `ceil(desejado/pack_multiple)*pack_multiple` nos dois casos, fracionário
   ou inteiro -- ver `_round_up_to_pack`, que não assume nada sobre
   integralidade em lugar nenhum);
3. pedido mínimo, por valor E por unidades (semântica AND -- os dois, quando
   configurados > 0, precisam ser atingidos; `0.0` = sem restrição), avaliado
   sobre o pedido já arredondado;
4. preenchimento até o mínimo pelos itens de MENOR cobertura relativa
   (`(posição + pedido corrente) / demanda diária esperada`), um fardo por
   vez, recalculando a cada incremento -- nunca pelo item mais barato. Item
   com demanda esperada `<= 0` fica de fora do preenchimento (nunca empilha
   estoque de item sem demanda só pra bater mínimo de fornecedor). Empate de
   cobertura resolvido por `item_id` ascendente -- estável e determinístico
   mesmo com iteração de dict não ordenada;
5. se o mínimo continuar inatingível (estourou `max_additional_packs_for_minimum`,
   contador GLOBAL somado sobre todos os itens -- ou não havia nenhum item
   candidato pro preenchimento), o pedido INTEIRO do fornecedor é adiado --
   `OrderOutcome.MINIMO_INATINGIVEL`, todo item zerado, um `OrderAdjustment`
   de motivo `PEDIDO_ADIADO` por item que tinha quantidade não-nula (nunca
   parcialmente enviado).

`next_order_day` é sempre a próxima data ESTRITAMENTE posterior a `as_of` que
bate `Supplier.order_days` -- nunca `as_of` em si, mesmo quando `as_of` já é
dia de pedido. Isso é deliberado: quando `as_of` é dia de pedido,
`next_order_day - as_of` é o ciclo de revisão real daquele fornecedor, o termo
que a Sprint 11 soma ao lead time pra montar a janela de risco. Definir como
">= as_of" devolveria zero nesse caso e produziria janela curta demais.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from motor.io.contracts import Supplier, UnitOfSale

_PACK_ROUNDING_REL_TOL = 1e-9
"""Tolerância RELATIVA (não absoluta) usada em `math.isclose` pra decidir se
uma quantidade já está em cima de um múltiplo de fardo. Relativa porque um eps
absoluto de 1e-9 é inofensivo com `pack_multiple=0.5` (kg) mas erra com
`pack_multiple=1000` (unidades) -- ver `_round_up_to_pack`.
"""


class OrderOutcome(StrEnum):
    """O que aconteceu com o pedido deste fornecedor nesta decisão.

    Três casos, deliberadamente não colapsados num booleano `deferred`: pra
    lista de exceções da Sprint 17, "hoje não é dia de pedido" não é exceção e
    não aparece pro comprador; "mínimo inatingível" precisa aparecer, porque é
    acionável (negociar com o representante, juntar com outro fornecedor,
    enviar assim mesmo).
    """

    PEDIDO_EMITIDO = "pedido_emitido"
    FORA_DO_CALENDARIO = "fora_do_calendario"
    MINIMO_INATINGIVEL = "minimo_inatingivel"


class AdjustmentReason(StrEnum):
    """Motivo de um `OrderAdjustment` -- dado estruturado, não string solta:
    é a coluna "motivo" da lista de exceções da Sprint 17."""

    ARREDONDAMENTO_DE_FARDO = "arredondamento_de_fardo"
    PREENCHIMENTO_DE_MINIMO = "preenchimento_de_minimo"
    PEDIDO_ADIADO = "pedido_adiado"


@dataclass(frozen=True)
class OrderAdjustment:
    """Um ajuste aplicado a um item. `delta_units` positivo = adicionado ao
    pedido; negativo = removido (só ocorre em `PEDIDO_ADIADO`, quando o
    pedido inteiro é zerado)."""

    item_id: str
    reason: AdjustmentReason
    delta_units: float


@dataclass(frozen=True)
class ItemPurchaseInfo:
    """Atributos de compra de um item, na mesma grandeza do seu
    `unit_of_sale` -- `pack_multiple` não tem conversão de unidade própria
    (ver docstring do módulo)."""

    pack_multiple: float
    cost: float
    unit_of_sale: UnitOfSale


@dataclass(frozen=True)
class SupplierOrderResult:
    """Saída de `apply_supplier_constraints`.

    `order`: item_id -> quantidade final a pedir (`0.0` pra todo item quando
    `outcome != PEDIDO_EMITIDO` -- pedido adiado é sempre integral, nunca
    parcial). `next_order_day`: sempre presente, mesmo quando `outcome` não é
    `PEDIDO_EMITIDO` -- ver docstring do módulo.
    """

    order: dict[str, float]
    adjustments: tuple[OrderAdjustment, ...]
    outcome: OrderOutcome
    next_order_day: date

    @property
    def deferred(self) -> bool:
        """Conveniência: `True` sempre que nada é enviado hoje, por qualquer
        motivo. O dado primário é `outcome` -- use-o quando o motivo importar."""
        return self.outcome != OrderOutcome.PEDIDO_EMITIDO


def _assert_matching_item_ids(
    desired: dict[str, float],
    position: dict[str, float],
    expected_daily_demand: dict[str, float],
    item_purchase_info: dict[str, ItemPurchaseInfo],
) -> None:
    expected_ids = set(desired)
    others = {
        "position": set(position),
        "expected_daily_demand": set(expected_daily_demand),
        "item_purchase_info": set(item_purchase_info),
    }
    for name, ids in others.items():
        if ids != expected_ids:
            msg = (
                f"item_ids de `{name}` ({sorted(ids)}) não batem com `desired` "
                f"({sorted(expected_ids)}) -- apply_supplier_constraints espera "
                "que todos os dicts de entrada cubram exatamente os itens deste "
                "fornecedor, nem mais nem menos"
            )
            raise ValueError(msg)


def _next_order_day(after: date, order_days: list[int]) -> date:
    """Menor data ESTRITAMENTE posterior a `after` cujo `isoweekday()` está em
    `order_days`. `order_days` tem `MinLen(1)` e valores em 1..7 (contrato de
    `Supplier`) -- sempre encontra em no máximo 7 dias."""
    order_days_set = set(order_days)
    candidate = after + timedelta(days=1)
    for _ in range(7):
        if candidate.isoweekday() in order_days_set:
            return candidate
        candidate += timedelta(days=1)
    msg = f"nenhum dia em order_days={order_days!r} encontrado em 7 dias a partir de {after}"
    raise AssertionError(msg)


def _round_up_to_pack(desired_qty: float, pack_multiple: float) -> tuple[float, bool]:
    """Arredonda `desired_qty` pra cima até o próximo múltiplo de
    `pack_multiple` -- nunca pra baixo (CLAUDE.md, seção 8: pra baixo gera
    ruptura sistemática em item de giro baixo). `desired_qty <= 0` fica `0.0`,
    sem arredondar pra um fardo.

    Devolve `(quantidade_arredondada, houve_arredondamento)`: o booleano vem
    de dentro da conta, não de comparar os dois floats depois -- comparação
    posterior seria sensível ao mesmo ruído de ponto flutuante que este
    arredondamento existe pra absorver.

    `_PACK_ROUNDING_REL_TOL` é RELATIVA (via `math.isclose` sobre a razão
    `desired_qty/pack_multiple`, adimensional): funciona igual com
    `pack_multiple=0.5` (kg) e `pack_multiple=1000` (unidades) -- um eps
    absoluto não funcionaria nos dois extremos.
    """
    if desired_qty <= 0.0:
        return 0.0, False

    ratio = desired_qty / pack_multiple
    nearest_int = round(ratio)
    at_multiple = math.isclose(ratio, nearest_int, rel_tol=_PACK_ROUNDING_REL_TOL)
    n_packs = nearest_int if at_multiple else math.ceil(ratio)
    return n_packs * pack_multiple, not at_multiple


def _meets_minimum(
    order: dict[str, float], item_purchase_info: dict[str, ItemPurchaseInfo], supplier: Supplier
) -> bool:
    """Semântica AND: quando `min_order_value` E `min_order_units` estão
    configurados (> 0.0), os DOIS precisam ser atingidos. `0.0` em qualquer um
    dos dois significa "sem restrição" naquele eixo."""
    total_units = sum(order.values())
    total_value = sum(qty * item_purchase_info[item_id].cost for item_id, qty in order.items())
    meets_value = supplier.min_order_value <= 0.0 or total_value >= supplier.min_order_value
    meets_units = supplier.min_order_units <= 0.0 or total_units >= supplier.min_order_units
    return meets_value and meets_units


def _fill_to_minimum(
    order: dict[str, float],
    *,
    position: dict[str, float],
    expected_daily_demand: dict[str, float],
    item_purchase_info: dict[str, ItemPurchaseInfo],
    supplier: Supplier,
    max_additional_packs: int,
) -> tuple[dict[str, float], list[OrderAdjustment], bool]:
    """Preenche `order` um fardo por vez até `_meets_minimum` ou até estourar
    `max_additional_packs` (contador GLOBAL, somado sobre todos os itens).

    Devolve `(pedido_atualizado, ajustes_de_preenchimento, minimo_atingido)`.
    Item com `expected_daily_demand <= 0` nunca é candidato -- nunca empilha
    estoque de item sem demanda esperada só pra bater mínimo de fornecedor
    (acontece de fato com fornecedor de cauda longa). Se NENHUM item é
    candidato, o loop não itera nenhuma vez: `minimo_atingido=False` e
    `ajustes_de_preenchimento` fica vazio -- é a diferença entre "tentei e não
    deu" e "não havia o que tentar".

    Recalcula a cobertura -- `(posição + pedido_corrente) / demanda` -- a cada
    incremento, porque um fardo pode mudar qual item tem a menor cobertura.
    Empate resolvido por `item_id` ascendente (`min()` com chave em tupla
    `(cobertura, item_id)`): determinístico independente da ordem de
    iteração do dict.
    """
    current = dict(order)
    adjustments: list[OrderAdjustment] = []
    candidates = [item_id for item_id in current if expected_daily_demand[item_id] > 0.0]

    packs_added = 0
    while not _meets_minimum(current, item_purchase_info, supplier):
        if not candidates or packs_added >= max_additional_packs:
            return current, adjustments, False

        chosen = min(
            candidates,
            key=lambda item_id: (
                (position[item_id] + current[item_id]) / expected_daily_demand[item_id],
                item_id,
            ),
        )
        increment = item_purchase_info[chosen].pack_multiple
        current[chosen] += increment
        adjustments.append(
            OrderAdjustment(
                item_id=chosen,
                reason=AdjustmentReason.PREENCHIMENTO_DE_MINIMO,
                delta_units=increment,
            )
        )
        packs_added += 1

    return current, adjustments, True


def apply_supplier_constraints(
    desired: dict[str, float],
    *,
    position: dict[str, float],
    expected_daily_demand: dict[str, float],
    item_purchase_info: dict[str, ItemPurchaseInfo],
    supplier: Supplier,
    as_of: date,
    max_additional_packs_for_minimum: int,
) -> SupplierOrderResult:
    """Aplica as restrições de fornecedor, na ordem descrita na docstring do
    módulo, sobre as quantidades desejadas de um único fornecedor.

    Todos os dicts de entrada precisam cobrir exatamente o mesmo conjunto de
    `item_id` (os itens deste fornecedor) -- ver `_assert_matching_item_ids`.
    """
    _assert_matching_item_ids(desired, position, expected_daily_demand, item_purchase_info)
    next_order_day = _next_order_day(as_of, supplier.order_days)

    if as_of.isoweekday() not in supplier.order_days:
        return SupplierOrderResult(
            order=dict.fromkeys(desired, 0.0),
            adjustments=(),
            outcome=OrderOutcome.FORA_DO_CALENDARIO,
            next_order_day=next_order_day,
        )

    rounded_order: dict[str, float] = {}
    adjustments: list[OrderAdjustment] = []
    for item_id, qty in desired.items():
        rounded_qty, was_rounded = _round_up_to_pack(qty, item_purchase_info[item_id].pack_multiple)
        rounded_order[item_id] = rounded_qty
        if was_rounded:
            adjustments.append(
                OrderAdjustment(
                    item_id=item_id,
                    reason=AdjustmentReason.ARREDONDAMENTO_DE_FARDO,
                    delta_units=rounded_qty - qty,
                )
            )

    filled_order, fill_adjustments, minimum_met = _fill_to_minimum(
        rounded_order,
        position=position,
        expected_daily_demand=expected_daily_demand,
        item_purchase_info=item_purchase_info,
        supplier=supplier,
        max_additional_packs=max_additional_packs_for_minimum,
    )
    adjustments.extend(fill_adjustments)

    if not minimum_met:
        deferred_adjustments = [
            OrderAdjustment(
                item_id=item_id, reason=AdjustmentReason.PEDIDO_ADIADO, delta_units=-qty
            )
            for item_id, qty in sorted(filled_order.items())
            if qty > 0.0
        ]
        return SupplierOrderResult(
            order=dict.fromkeys(desired, 0.0),
            adjustments=tuple(adjustments) + tuple(deferred_adjustments),
            outcome=OrderOutcome.MINIMO_INATINGIVEL,
            next_order_day=next_order_day,
        )

    return SupplierOrderResult(
        order=filled_order,
        adjustments=tuple(adjustments),
        outcome=OrderOutcome.PEDIDO_EMITIDO,
        next_order_day=next_order_day,
    )
