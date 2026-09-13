"""Regras de guarda, aplicadas depois da política, antes do pedido final
(Sprint 13, CLAUDE.md seção 3 -- implementadas na Etapa 3.16 da Sprint 17).

Lógica pura, sem `Params`, sem I/O, mesma disciplina de `motor.policy.
supplier`/`target_level`: cada função recebe valores já resolvidos (nunca
`config/params.yaml` inteiro) e devolve a quantidade ajustada mais um
`GuardrailFlag | None` -- o registro estruturado que vira a coluna "motivo"
da lista de exceções (Sprint 17). `None` significa "não disparou", nunca
"não foi checado".

Quatro das seis regras do desenho original:

1. `apply_coverage_cap` -- teto de dias de estoque por família de
   categoria. Sugestão que ultrapassa é CORTADA no teto.
2. `check_order_variation` -- sugestão acima de N vezes a média das
   compras (não vendas) recentes do item é SINALIZADA para revisão
   humana, nunca cortada.
3. `apply_cash_constraint` -- orçamento do ciclo (portfólio inteiro, não
   por item): itens ordenados por margem gerada por real investido,
   cortados do fim pra trás quando o orçamento estoura -- nunca
   proporcionalmente. O que fica de fora é registrado, não descartado.
4. `is_new_item`/`new_item_quantity` -- item novo (histórico curto demais
   pra ter uma previsão confiável) sai por quantidade fixa (mediana da
   categoria), nunca por modelo -- sempre um `GuardrailFlag`.

As duas restantes (promoção prevista, item âncora) NÃO estão implementadas
-- ver `NOT_IMPLEMENTED_GUARDRAILS`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final


class GuardrailReason(StrEnum):
    """Motivo de um `GuardrailFlag` -- dado estruturado, não string solta,
    mesmo padrão de `motor.policy.supplier.AdjustmentReason`."""

    TETO_DE_COBERTURA = "teto_de_cobertura"
    LIMITE_DE_VARIACAO = "limite_de_variacao"
    RESTRICAO_DE_CAIXA = "restricao_de_caixa"
    ITEM_NOVO = "item_novo"


@dataclass(frozen=True)
class GuardrailFlag:
    """Um disparo de regra de guarda sobre um item.

    `adjusted_quantity == original_quantity` para `LIMITE_DE_VARIACAO`
    (sinaliza, não corta) -- os dois valores divergem nas outras três
    regras. `detail` carrega os números reais (não só o nome da regra):
    é o texto que vai para a coluna "motivo" de um dono de mercado.
    """

    item_id: str
    reason: GuardrailReason
    detail: str
    original_quantity: float
    adjusted_quantity: float


NOT_IMPLEMENTED_GUARDRAILS: Final[tuple[str, ...]] = (
    "promocao_prevista -- exige calendário promocional (Item.on_promo futuro/planejado); "
    "o canônico Favorita só carrega on_promo HISTÓRICO em sales.parquet (o que já "
    "aconteceu), nunca o que está planejado -- não dá pra reagir a uma promoção que o "
    "dado não anuncia com antecedência. Não implementada.",
    "item_ancora -- exige análise de cesta (quais itens saem juntos, para proteger "
    "presença de item de entrada mesmo com margem comprimida) -- fora de escopo da v1 "
    "(Item.is_anchor é 100% nulo no canônico, Sprint 3 D7). Não implementada.",
)
"""Duas das seis regras de guarda do desenho original -- declaradas aqui,
não escondidas, mesmo tratamento dado ao gap de `GuardrailsParams` inteiro
antes desta etapa (CLAUDE.md, emenda Sprint 17)."""


def apply_coverage_cap(
    item_id: str,
    quantity: float,
    *,
    position: float,
    expected_daily_demand: float,
    shelf_life_days: float,
    risk_window_days: float,
) -> tuple[float, GuardrailFlag | None]:
    """Corta `quantity` para que `position + quantity` não exceda o teto
    EFETIVO de cobertura -- `max(shelf_life_days, risk_window_days)`,
    NUNCA `shelf_life_days` sozinha (Etapa 3.16.2).

    `shelf_life_days` é a validade física da família (perecível fresco
    estraga em 7 dias, por exemplo) -- um teto de negócio legítimo.
    `risk_window_days` (`lead_time_days + review_period_days`) é o PISO
    arquitetural: pedir menos que a própria janela de risco garante
    ruptura estrutural a cada ciclo, não é proteção, é bug. Quando
    `risk_window_days > shelf_life_days`, a guarda está detectando um
    parâmetro de fornecedor IMPOSSÍVEL para aquela família (ciclo de
    revisão longo demais pra um produto que estraga rápido) -- registrado
    no motivo (`GuardrailFlag.detail`) sempre que a diferença teria
    importado para este item, mesmo que o teto efetivo (já com o piso)
    não precise cortar a quantidade.

    `expected_daily_demand <= 0` não corta -- sem demanda esperada, "dias
    de cobertura" não tem denominador; item sem venda recente é assunto de
    outra regra (`is_new_item`), não desta. `quantity <= 0` também não
    corta -- não há o que cortar.
    """
    if expected_daily_demand <= 0.0 or quantity <= 0.0:
        return quantity, None

    effective_cap_days = max(shelf_life_days, risk_window_days)
    shelf_life_cap = max(0.0, shelf_life_days * expected_daily_demand - position)
    effective_cap = max(0.0, effective_cap_days * expected_daily_demand - position)

    conflict = risk_window_days > shelf_life_days and quantity > shelf_life_cap
    cut = quantity > effective_cap
    final_quantity = effective_cap if cut else quantity

    if not conflict and not cut:
        return quantity, None

    detail_parts = []
    if conflict:
        detail_parts.append(
            f"teto de validade ({shelf_life_days:g}d) menor que a janela de risco "
            f"({risk_window_days:g}d); ciclo de compra incompatível com a família -- "
            f"piso de {risk_window_days:g}d aplicado no lugar da validade"
        )
    if cut:
        detail_parts.append(
            f"cortado de {quantity:.2f} para {final_quantity:.2f} unidades -- teto "
            f"efetivo de {effective_cap_days:g} dias de cobertura (posição atual "
            f"{position:.2f} unidades, demanda esperada {expected_daily_demand:.2f} "
            "unidades/dia)"
        )
    flag = GuardrailFlag(
        item_id=item_id,
        reason=GuardrailReason.TETO_DE_COBERTURA,
        detail="; ".join(detail_parts),
        original_quantity=quantity,
        adjusted_quantity=final_quantity,
    )
    return final_quantity, flag


def check_order_variation(
    item_id: str,
    quantity: float,
    *,
    recent_average_purchase: float,
    limit_multiple: float,
) -> GuardrailFlag | None:
    """Sinaliza (NUNCA corta) quando `quantity` excede `limit_multiple`
    vezes `recent_average_purchase` -- revisão humana, não correção
    automática (diferença deliberada de `apply_coverage_cap`: aqui o
    motivo de negócio para uma variação grande pode ser legítimo -- uma
    promoção real, um evento -- e cortar sem contexto erraria por excesso
    de zelo com a mesma frequência que erraria por falta).

    `recent_average_purchase <= 0` não dispara -- sem histórico de compra
    (item novo, ou nenhum ciclo de revisão ainda passou), não há média
    contra a qual comparar; ver docstring do módulo, regra 4.
    """
    if recent_average_purchase <= 0.0:
        return None
    limit = recent_average_purchase * limit_multiple
    if quantity <= limit:
        return None

    ratio = quantity / recent_average_purchase
    detail = (
        f"sugestão de {quantity:.2f} unidades é {ratio:.1f}x a média das compras dos "
        f"últimos dias ({recent_average_purchase:.2f}) -- acima do limite de "
        f"{limit_multiple:g}x, sinalizado para revisão humana (quantidade NÃO alterada)"
    )
    return GuardrailFlag(
        item_id=item_id,
        reason=GuardrailReason.LIMITE_DE_VARIACAO,
        detail=detail,
        original_quantity=quantity,
        adjusted_quantity=quantity,
    )


def is_new_item(
    *,
    first_sale_date: date | None,
    days_with_sales: int,
    as_of: date,
    min_history_days: int,
    min_days_with_sales: int,
) -> bool:
    """`True` quando o item não tem histórico de venda suficiente para uma
    previsão confiável -- sem NENHUM registro de venda (`first_sale_date`
    `None`) é o caso extremo, trivialmente `True`."""
    if first_sale_date is None:
        return True
    history_days = (as_of - first_sale_date).days
    return history_days < min_history_days or days_with_sales < min_days_with_sales


def new_item_quantity(
    item_id: str,
    *,
    model_suggested_quantity: float,
    category_median_quantity: float,
    used_global_fallback: bool,
) -> GuardrailFlag:
    """Devolve o `GuardrailFlag` de um item novo -- SEMPRE dispara (item
    novo sempre vai para exceções, nunca silenciosamente). Quantidade final
    é a mediana da categoria, nunca o que o modelo teria sugerido
    (`model_suggested_quantity` entra só como registro de auditoria em
    `detail`, nunca na decisão).

    `used_global_fallback`: quando a categoria não tem NENHUM item não-novo
    para calcular a própria mediana (categoria pequena, ou todos os itens
    dela são novos), usa a mediana global da lista -- declarado no
    `detail`, não escondido.
    """
    fallback_note = (
        " (categoria sem referência -- mediana global usada)" if used_global_fallback else ""
    )
    detail = (
        f"item novo -- quantidade fixa pela mediana da categoria "
        f"({category_median_quantity:.2f} unidades{fallback_note}), não pelo modelo "
        f"(que sugeriria {model_suggested_quantity:.2f} unidades sobre histórico curto "
        "demais para confiar)"
    )
    return GuardrailFlag(
        item_id=item_id,
        reason=GuardrailReason.ITEM_NOVO,
        detail=detail,
        original_quantity=model_suggested_quantity,
        adjusted_quantity=category_median_quantity,
    )


@dataclass(frozen=True)
class CashConstraintCandidate:
    """Um item candidato à restrição de caixa -- já com quantidade e valor
    finais (pós fardo/mínimo de fornecedor), porque o orçamento é sobre
    R$ realmente gastos, não sobre a sugestão bruta."""

    item_id: str
    category: str
    quantity: float
    value_rs: float
    margin_pct: float


@dataclass(frozen=True)
class CategoryFloorAlert:
    """Emitido quando a SOMA dos pisos de categoria sozinha já excede o
    orçamento do ciclo -- o orçamento não cobre nem o mínimo operacional
    da loja (Etapa 3.16.4). Informação de negócio, não detalhe de
    algoritmo: nenhuma combinação de cortes resolve isso, só aumentar o
    orçamento ou reduzir o piso."""

    total_floor_rs: float
    budget_rs: float
    shortfall_rs: float


def _rank_by_margin(candidates: Sequence[CashConstraintCandidate]) -> list[CashConstraintCandidate]:
    """Margem gerada por real investido, descendente -- com
    `uniform_unit_price`, `margin_pct` sozinho já ordena por isso (ver
    `motor.metrics.financial`); desempate por `item_id` ascendente
    (determinístico)."""
    return sorted(candidates, key=lambda c: (-c.margin_pct, c.item_id))


def _greedy_cutoff_kept(
    ordered: Sequence[CashConstraintCandidate], budget_rs: float
) -> dict[str, bool]:
    """`True`/`False` por item -- mantido ou cortado, em ORDEM (já rankeada
    por margem): "corte do fim", não encaixe guloso (ver docstring de
    `apply_cash_constraint`)."""
    kept: dict[str, bool] = {}
    running_rs = 0.0
    cutoff_reached = False
    for candidate in ordered:
        if not cutoff_reached and running_rs + candidate.value_rs <= budget_rs:
            kept[candidate.item_id] = True
            running_rs += candidate.value_rs
        else:
            cutoff_reached = True
            kept[candidate.item_id] = False
    return kept


def _reduced_flag(
    candidate: CashConstraintCandidate, budget_rs: float, *, extra: str = ""
) -> GuardrailFlag:
    detail = (
        f"reduzido por restrição de caixa -- fora do orçamento do ciclo "
        f"(R$ {budget_rs:,.2f}), valor original R$ {candidate.value_rs:,.2f}, margem "
        f"{candidate.margin_pct:.1%}; cortado por ordem de margem gerada por real "
        "investido, não proporcionalmente" + (f" ({extra})" if extra else "")
    )
    return GuardrailFlag(
        item_id=candidate.item_id,
        reason=GuardrailReason.RESTRICAO_DE_CAIXA,
        detail=detail,
        original_quantity=candidate.quantity,
        adjusted_quantity=0.0,
    )


def _protected_flag(
    candidate: CashConstraintCandidate, *, floor_rs: float, floor_fraction: float
) -> GuardrailFlag:
    detail = (
        f"protegido pelo piso de categoria -- {candidate.category!r} nunca cai abaixo "
        f"de R$ {floor_rs:,.2f} ({floor_fraction:.0%} do valor originalmente sugerido "
        f"para a categoria), mesmo com margem {candidate.margin_pct:.1%} que seria "
        "cortada pela ordem de margem sozinha"
    )
    return GuardrailFlag(
        item_id=candidate.item_id,
        reason=GuardrailReason.RESTRICAO_DE_CAIXA,
        detail=detail,
        original_quantity=candidate.quantity,
        adjusted_quantity=candidate.quantity,
    )


def _group_by_category(
    candidates: Sequence[CashConstraintCandidate],
) -> dict[str, list[CashConstraintCandidate]]:
    by_category: dict[str, list[CashConstraintCandidate]] = {}
    for c in candidates:
        by_category.setdefault(c.category, []).append(c)
    return by_category


def _split_floor_and_headroom(
    by_category: dict[str, list[CashConstraintCandidate]], *, category_floor_fraction: float
) -> tuple[dict[str, list[CashConstraintCandidate]], dict[str, list[CashConstraintCandidate]]]:
    """Por categoria, separa os itens em PROTEGIDOS (o piso) e EXCEDENTE
    (`headroom`, sujeito a corte por margem).

    O excedente é formado pelos itens de PIOR margem da categoria, até
    somar no máximo `(1 - category_floor_fraction)` do valor da categoria
    -- nunca mais que isso, porque itens são atômicos (não dá pra cortar
    "metade" de um item): se o próximo pior item não coube inteiro no
    espaço que resta do excedente, ele (e todos os melhores que ele) ficam
    protegidos. Isso garante que o valor protegido de cada categoria é
    SEMPRE >= `category_floor_fraction` do original -- pode passar disso
    (quando um item não cabe exato no limite do excedente), nunca ficar
    abaixo. Overshoot no protegido é a direção seguRA de um piso; overshoot
    no excedente (cortar mais que o combinado) não seria.
    """
    protected: dict[str, list[CashConstraintCandidate]] = {}
    headroom: dict[str, list[CashConstraintCandidate]] = {}
    for cat, items in by_category.items():
        category_value = sum(c.value_rs for c in items)
        allowance = (1.0 - category_floor_fraction) * category_value
        worst_first = sorted(items, key=lambda c: (c.margin_pct, c.item_id))
        acc = 0.0
        split_index = 0
        for item in worst_first:
            if acc + item.value_rs > allowance:
                break
            acc += item.value_rs
            split_index += 1
        headroom[cat] = worst_first[:split_index]
        protected[cat] = worst_first[split_index:]
    return protected, headroom


def _floor_shortfall_case(
    protected: dict[str, list[CashConstraintCandidate]],
    headroom: dict[str, list[CashConstraintCandidate]],
    *,
    budget_rs: float,
    total_protected_rs: float,
    baseline_kept: dict[str, bool],
) -> tuple[dict[str, float], tuple[GuardrailFlag, ...], CategoryFloorAlert]:
    """SOMA do protegido (real, já considerando atomicidade) > orçamento --
    nenhuma combinação de cortes no excedente resolveria isso (não sobra
    excedente pra cortar quando o piso sozinho já estoura). Concede o
    protegido de categorias INTEIRAS, por ordem de margem MÉDIA (ponderada
    por valor) da categoria, até o orçamento acabar -- categoria sem piso
    concedido fica com TUDO cortado (protegido e excedente). Ver docstring
    de `apply_cash_constraint`."""
    alert = CategoryFloorAlert(
        total_floor_rs=total_protected_rs,
        budget_rs=budget_rs,
        shortfall_rs=total_protected_rs - budget_rs,
    )
    all_items_by_cat = {
        cat: [*protected.get(cat, []), *headroom.get(cat, [])]
        for cat in set(protected) | set(headroom)
    }
    protected_value = {cat: sum(c.value_rs for c in items) for cat, items in protected.items()}
    category_avg_margin = {
        cat: sum(c.value_rs * c.margin_pct for c in items) / sum(c.value_rs for c in items)
        for cat, items in all_items_by_cat.items()
    }
    granted: set[str] = set()
    running_rs = 0.0
    for cat in sorted(category_avg_margin, key=lambda c: (-category_avg_margin[c], c)):
        cost = protected_value.get(cat, 0.0)
        if running_rs + cost <= budget_rs:
            running_rs += cost
            granted.add(cat)

    kept: dict[str, float] = {}
    flags: list[GuardrailFlag] = []
    for cat, items in all_items_by_cat.items():
        if cat in granted:
            for item in protected.get(cat, []):
                kept[item.item_id] = item.quantity
                if not baseline_kept[item.item_id]:
                    flags.append(
                        _protected_flag(
                            item,
                            floor_rs=protected_value[cat],
                            floor_fraction=protected_value[cat] / sum(c.value_rs for c in items),
                        )
                    )
            for item in headroom.get(cat, []):
                kept[item.item_id] = 0.0
                flags.append(
                    _reduced_flag(
                        item,
                        budget_rs,
                        extra="fora do piso -- só o piso desta categoria foi concedido",
                    )
                )
        else:
            for item in items:
                kept[item.item_id] = 0.0
                flags.append(
                    _reduced_flag(
                        item, budget_rs, extra="orçamento não cobre nem o piso desta categoria"
                    )
                )
    return kept, tuple(flags), alert


def _floor_fits_case(
    protected: dict[str, list[CashConstraintCandidate]],
    headroom: dict[str, list[CashConstraintCandidate]],
    *,
    budget_rs: float,
    total_protected_rs: float,
    category_floor_fraction: float,
    baseline_kept: dict[str, bool],
) -> tuple[dict[str, float], tuple[GuardrailFlag, ...], None]:
    """SOMA do protegido cabe no orçamento -- reserva o protegido de TODA
    categoria e usa o que sobra pra competir por margem entre os
    excedentes de TODAS as categorias juntos ("corte do fim", ver
    `_greedy_cutoff_kept`). Ver docstring de `apply_cash_constraint`."""
    remaining_budget = budget_rs - total_protected_rs
    all_headroom = [item for items in headroom.values() for item in items]
    headroom_kept = _greedy_cutoff_kept(_rank_by_margin(all_headroom), remaining_budget)

    kept: dict[str, float] = {}
    flags: list[GuardrailFlag] = []
    for cat, items in protected.items():
        category_value = sum(c.value_rs for c in [*items, *headroom.get(cat, [])])
        for item in items:
            kept[item.item_id] = item.quantity
            if not baseline_kept[item.item_id]:
                flags.append(
                    _protected_flag(
                        item,
                        floor_rs=category_floor_fraction * category_value,
                        floor_fraction=category_floor_fraction,
                    )
                )
    for item in all_headroom:
        if headroom_kept[item.item_id]:
            kept[item.item_id] = item.quantity
        else:
            kept[item.item_id] = 0.0
            flags.append(_reduced_flag(item, budget_rs))

    return kept, tuple(flags), None


def apply_cash_constraint(
    candidates: Sequence[CashConstraintCandidate],
    *,
    budget_rs: float,
    category_floor_fraction: float,
) -> tuple[dict[str, float], tuple[GuardrailFlag, ...], CategoryFloorAlert | None]:
    """Restrição de caixa com piso de negócio por categoria (Etapa 3.16.4).

    Dois passos, nesta ordem, NÃO um único ranking global de margem:

    1. Separa cada categoria em PROTEGIDO (pelo menos
       `category_floor_fraction` do valor original, qualquer que seja a
       margem -- os itens de PIOR margem da categoria formam o excedente,
       o resto é protegido) e EXCEDENTE. Ver `_split_floor_and_headroom`.
    2. Com o que sobra do orçamento depois de reservar o protegido de
       TODAS as categorias, os excedentes de TODAS as categorias competem
       juntos por margem, "corte do fim" -- exatamente o mecanismo de
       antes da Etapa 3.16.4, agora restrito ao excedente
       (`_floor_fits_case`).

    Quando a SOMA do protegido sozinha já excede `budget_rs` (não sobra
    excedente pra cortar -- nenhuma combinação resolveria isso), a guarda
    NÃO tenta salvar todas as categorias: concede o protegido de
    categorias INTEIRAS, por ordem de margem MÉDIA (ponderada por valor),
    até o orçamento acabar -- categoria sem piso concedido fica com TUDO
    cortado (`_floor_shortfall_case`). Devolve um `CategoryFloorAlert`
    neste caso -- é informação de negócio (o orçamento não cobre o mínimo
    operacional), não um detalhe de algoritmo.

    Devolve `(quantidade_final_por_item, flags, alerta_ou_none)` -- todo
    item de `candidates` aparece em `quantidade_final_por_item`; um
    `GuardrailFlag` é emitido para todo item CORTADO ("reduzido por
    restrição de caixa") e para todo item que só sobreviveu por causa do
    piso ("protegido pelo piso de categoria") -- item que sobrevive por
    mérito próprio (dentro do excedente, sem precisar do piso) não gera
    flag, igual ao comportamento anterior à Etapa 3.16.4.
    """
    if not candidates:
        return {}, (), None

    baseline_kept = _greedy_cutoff_kept(_rank_by_margin(candidates), budget_rs)
    by_category = _group_by_category(candidates)
    protected, headroom = _split_floor_and_headroom(
        by_category, category_floor_fraction=category_floor_fraction
    )
    total_protected_rs = sum(c.value_rs for items in protected.values() for c in items)

    if total_protected_rs > budget_rs:
        return _floor_shortfall_case(
            protected,
            headroom,
            budget_rs=budget_rs,
            total_protected_rs=total_protected_rs,
            baseline_kept=baseline_kept,
        )
    return _floor_fits_case(
        protected,
        headroom,
        budget_rs=budget_rs,
        total_protected_rs=total_protected_rs,
        category_floor_fraction=category_floor_fraction,
        baseline_kept=baseline_kept,
    )
