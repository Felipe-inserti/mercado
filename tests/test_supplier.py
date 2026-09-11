"""Testes de `motor.policy.supplier` (Sprint 10).

Lógica pura, sem estatística -- todo cenário é sintético, construído à mão.
`D0` (2024-01-01) é uma segunda-feira (isoweekday()==1); a asserção logo
abaixo falha alto se essa premissa de calendário um dia deixar de valer.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from motor.io.contracts import Supplier, UnitOfSale
from motor.policy.supplier import (
    AdjustmentReason,
    ItemPurchaseInfo,
    OrderOutcome,
    apply_supplier_constraints,
)

D0 = date(2024, 1, 1)
assert D0.isoweekday() == 1  # segunda -- premissa de calendário dos testes abaixo


def _supplier(
    *,
    order_days: list[int],
    min_order_value: float = 0.0,
    min_order_units: float = 0.0,
    lead_time_days: int = 3,
    review_period_days: int = 7,
) -> Supplier:
    return Supplier(
        supplier_id="SUP1",
        lead_time_days=lead_time_days,
        order_days=order_days,
        review_period_days=review_period_days,
        min_order_value=min_order_value,
        min_order_units=min_order_units,
    )


def _item(
    *, pack_multiple: float, cost: float = 1.0, unit_of_sale: UnitOfSale = UnitOfSale.UNIDADE
) -> ItemPurchaseInfo:
    return ItemPurchaseInfo(pack_multiple=pack_multiple, cost=cost, unit_of_sale=unit_of_sale)


# --------------------------------------------------------------------------
# 1. Arredondamento de fardo -- sempre para cima
# --------------------------------------------------------------------------


def test_arredondamento_para_cima_em_multiplo() -> None:
    desired = {"A": 7.0, "B": 0.0, "C": 8.0}
    result = apply_supplier_constraints(
        desired,
        position=dict.fromkeys(desired, 0.0),
        expected_daily_demand=dict.fromkeys(desired, 1.0),
        item_purchase_info={k: _item(pack_multiple=4.0) for k in desired},
        supplier=_supplier(order_days=[D0.isoweekday()]),
        as_of=D0,
        max_additional_packs_for_minimum=0,
    )
    assert result.outcome == OrderOutcome.PEDIDO_EMITIDO
    # 7 arredonda para cima até 8 (2 fardos de 4)
    assert result.order["A"] == pytest.approx(8.0)
    # 0 permanece 0 -- nunca arredonda zero para um fardo
    assert result.order["B"] == pytest.approx(0.0)
    # 8 já é múltiplo exato -- permanece 8, sem ajuste registrado
    assert result.order["C"] == pytest.approx(8.0)

    ajustes_por_item = {a.item_id: a for a in result.adjustments}
    assert ajustes_por_item["A"].reason == AdjustmentReason.ARREDONDAMENTO_DE_FARDO
    assert ajustes_por_item["A"].delta_units == pytest.approx(1.0)  # 8 - 7
    assert "B" not in ajustes_por_item
    assert "C" not in ajustes_por_item  # múltiplo exato não gera ajuste


# --------------------------------------------------------------------------
# 2. Item fracionário (kg) -- unidade de compra na mesma grandeza da venda
# --------------------------------------------------------------------------


def test_item_fracionario_kg_arredonda_em_multiplo_fracionario() -> None:
    """Item vendido por peso: `pack_multiple` é expresso em kg (a mesma
    grandeza da venda, sem campo de conversão -- ver docstring do módulo).
    6.0kg desejados, caixa de 2.5kg -> 3 caixas = 7.5kg."""
    desired = {"CARNE": 6.0}
    result = apply_supplier_constraints(
        desired,
        position={"CARNE": 0.0},
        expected_daily_demand={"CARNE": 1.0},
        item_purchase_info={"CARNE": _item(pack_multiple=2.5, unit_of_sale=UnitOfSale.PESO)},
        supplier=_supplier(order_days=[D0.isoweekday()]),
        as_of=D0,
        max_additional_packs_for_minimum=0,
    )
    assert result.order["CARNE"] == pytest.approx(7.5)
    ajuste = result.adjustments[0]
    assert ajuste.reason == AdjustmentReason.ARREDONDAMENTO_DE_FARDO
    assert ajuste.delta_units == pytest.approx(1.5)  # 7.5 - 6.0


# --------------------------------------------------------------------------
# detalhe 1: epsilon relativo ao múltiplo -- fracionário pequeno e inteiro grande
# --------------------------------------------------------------------------


def test_desejado_exatamente_no_multiplo_nao_arredonda_escala_fracionaria() -> None:
    """pack_multiple pequeno (0.5): 1.5 é exatamente 3 fardos -- ruído de
    ponto flutuante (0.1+0.1+0.1 != 0.3 em float) não pode gerar ajuste espúrio."""
    desired_exato = 0.1 + 0.1 + 0.1  # 0.30000000000000004 em float puro
    desired = {"A": desired_exato * 5}  # ~1.5, mesmo ruído amplificado
    result = apply_supplier_constraints(
        desired,
        position={"A": 0.0},
        expected_daily_demand={"A": 1.0},
        item_purchase_info={"A": _item(pack_multiple=0.5)},
        supplier=_supplier(order_days=[D0.isoweekday()]),
        as_of=D0,
        max_additional_packs_for_minimum=0,
    )
    assert result.adjustments == ()  # já estava em cima do múltiplo -- sem ajuste
    assert result.order["A"] == pytest.approx(1.5)


def test_desejado_exatamente_no_multiplo_nao_arredonda_escala_inteira_grande() -> None:
    """pack_multiple grande (1000 unidades): um eps ABSOLUTO de 1e-9 seria
    irrelevante nessa escala -- o eps precisa ser relativo ao múltiplo."""
    desired = {"A": 2999.9999999997}  # ruído de ponto flutuante bem perto de 3000
    result = apply_supplier_constraints(
        desired,
        position={"A": 0.0},
        expected_daily_demand={"A": 1.0},
        item_purchase_info={"A": _item(pack_multiple=1000.0)},
        supplier=_supplier(order_days=[D0.isoweekday()]),
        as_of=D0,
        max_additional_packs_for_minimum=0,
    )
    assert result.adjustments == ()
    assert result.order["A"] == pytest.approx(3000.0)


# --------------------------------------------------------------------------
# 3. Calendário -- fora do dia de pedido
# --------------------------------------------------------------------------


def test_dia_fora_do_calendario_pedido_vazio_e_proximo_dia_correto() -> None:
    terca = D0 + timedelta(days=1)
    assert terca.isoweekday() == 2
    quinta_isoweekday = 4

    result = apply_supplier_constraints(
        {"A": 10.0},
        position={"A": 0.0},
        expected_daily_demand={"A": 1.0},
        item_purchase_info={"A": _item(pack_multiple=1.0)},
        supplier=_supplier(order_days=[D0.isoweekday(), quinta_isoweekday]),  # segunda, quinta
        as_of=terca,
        max_additional_packs_for_minimum=0,
    )
    assert result.outcome == OrderOutcome.FORA_DO_CALENDARIO
    assert result.order == {"A": 0.0}
    assert result.adjustments == ()
    assert result.next_order_day == terca + timedelta(days=2)  # próxima quinta
    assert result.deferred is True


def test_next_order_day_e_estritamente_posterior_mesmo_quando_as_of_ja_e_dia_de_pedido() -> None:
    quarta_isoweekday = 3
    result = apply_supplier_constraints(
        {"A": 0.0},
        position={"A": 0.0},
        expected_daily_demand={"A": 1.0},
        item_purchase_info={"A": _item(pack_multiple=1.0)},
        supplier=_supplier(order_days=[D0.isoweekday(), quarta_isoweekday]),  # segunda, quarta
        as_of=D0,  # segunda -- já É dia de pedido
        max_additional_packs_for_minimum=0,
    )
    assert result.outcome == OrderOutcome.PEDIDO_EMITIDO
    # ciclo de revisão real (next_order_day - as_of) = 2 dias (segunda -> quarta),
    # nunca 0 -- é esse valor que a Sprint 11 soma ao lead time
    assert result.next_order_day == D0 + timedelta(days=2)


# --------------------------------------------------------------------------
# 4. Mínimo já atingido -- nenhum preenchimento
# --------------------------------------------------------------------------


def test_minimo_ja_atingido_nao_preenche() -> None:
    desired = {"A": 20.0, "B": 20.0}
    result = apply_supplier_constraints(
        desired,
        position={"A": 0.0, "B": 0.0},
        expected_daily_demand={"A": 1.0, "B": 1.0},
        item_purchase_info={"A": _item(pack_multiple=5.0), "B": _item(pack_multiple=5.0)},
        supplier=_supplier(order_days=[D0.isoweekday()], min_order_units=10.0),
        as_of=D0,
        max_additional_packs_for_minimum=100,
    )
    assert result.outcome == OrderOutcome.PEDIDO_EMITIDO
    assert result.order == {"A": 20.0, "B": 20.0}
    assert all(a.reason != AdjustmentReason.PREENCHIMENTO_DE_MINIMO for a in result.adjustments)


# --------------------------------------------------------------------------
# 5. Preenchimento por menor cobertura, com mudança de ordem no meio do loop
# --------------------------------------------------------------------------


def test_preenchimento_escolhe_menor_cobertura_e_ordem_muda_no_loop() -> None:
    """A: demanda=2, pack=3, posição=0 -> cobertura inicial 0 (menor -> escolhido 1º).
    B: demanda=1, pack=1, posição=1 -> cobertura inicial 1.

    Depois de A ganhar 1 fardo (pedido=3): cobertura A = (0+3)/2 = 1.5,
    cobertura B ainda 1 -- B vira o menor e é escolhido na 2ª rodada.
    min_order_units=4 fecha exatamente com A=3 + B=1.
    """
    result = apply_supplier_constraints(
        {"A": 0.0, "B": 0.0},
        position={"A": 0.0, "B": 1.0},
        expected_daily_demand={"A": 2.0, "B": 1.0},
        item_purchase_info={"A": _item(pack_multiple=3.0), "B": _item(pack_multiple=1.0)},
        supplier=_supplier(order_days=[D0.isoweekday()], min_order_units=4.0),
        as_of=D0,
        max_additional_packs_for_minimum=5,
    )
    assert result.outcome == OrderOutcome.PEDIDO_EMITIDO
    assert result.order == {"A": 3.0, "B": 1.0}

    preenchimentos = [
        a for a in result.adjustments if a.reason == AdjustmentReason.PREENCHIMENTO_DE_MINIMO
    ]
    assert [a.item_id for a in preenchimentos] == ["A", "B"]  # ordem de escolha, não alfabética
    assert preenchimentos[0].delta_units == pytest.approx(3.0)
    assert preenchimentos[1].delta_units == pytest.approx(1.0)


# --------------------------------------------------------------------------
# 6. Mínimo inatingível -- pedido inteiro adiado
# --------------------------------------------------------------------------


def test_minimo_inatingivel_pedido_inteiro_adiado() -> None:
    result = apply_supplier_constraints(
        {"A": 0.0},
        position={"A": 0.0},
        expected_daily_demand={"A": 1.0},
        item_purchase_info={"A": _item(pack_multiple=1.0)},
        supplier=_supplier(order_days=[D0.isoweekday()], min_order_units=100.0),
        as_of=D0,
        max_additional_packs_for_minimum=2,  # nunca chega a 100 com pack=1
    )
    assert result.outcome == OrderOutcome.MINIMO_INATINGIVEL
    assert result.deferred is True
    assert result.order == {"A": 0.0}  # zerado -- nunca parcialmente enviado

    adiamentos = [a for a in result.adjustments if a.reason == AdjustmentReason.PEDIDO_ADIADO]
    assert len(adiamentos) == 1
    assert adiamentos[0].item_id == "A"
    assert adiamentos[0].delta_units == pytest.approx(-2.0)  # zerou os 2 fardos preenchidos
    # o rastro de preenchimento continua no registro, junto com o adiamento
    preenchimentos = [
        a for a in result.adjustments if a.reason == AdjustmentReason.PREENCHIMENTO_DE_MINIMO
    ]
    assert len(preenchimentos) == 2


# --------------------------------------------------------------------------
# detalhe 2: todos os candidatos fora do preenchimento por demanda <= 0
# --------------------------------------------------------------------------


def test_todos_candidatos_fora_por_demanda_zero_minimo_inatingivel_sem_preenchimento() -> None:
    """Fornecedor de cauda: nenhum item tem demanda esperada > 0 -- o loop de
    preenchimento não itera nenhuma vez (nada pra tentar), diferente do caso
    em que se tenta preencher e não alcança."""
    result = apply_supplier_constraints(
        {"A": 0.0, "B": 0.0},
        position={"A": 0.0, "B": 0.0},
        expected_daily_demand={"A": 0.0, "B": 0.0},
        item_purchase_info={"A": _item(pack_multiple=1.0), "B": _item(pack_multiple=1.0)},
        supplier=_supplier(order_days=[D0.isoweekday()], min_order_units=10.0),
        as_of=D0,
        max_additional_packs_for_minimum=50,
    )
    assert result.outcome == OrderOutcome.MINIMO_INATINGIVEL
    assert result.order == {"A": 0.0, "B": 0.0}
    # nada foi tentado -- nem preenchimento, nem adiamento (não havia o que zerar)
    assert result.adjustments == ()


# --------------------------------------------------------------------------
# 7. Determinismo com empate de cobertura
# --------------------------------------------------------------------------


def test_determinismo_com_empate_de_cobertura_desempata_por_item_id() -> None:
    desired = {"I2": 0.0, "I1": 0.0}  # I2 inserido primeiro no dict de propósito
    kwargs = {
        "position": {"I1": 0.0, "I2": 0.0},
        "expected_daily_demand": {"I1": 1.0, "I2": 1.0},  # cobertura empatada (0/1 == 0/1)
        "item_purchase_info": {"I1": _item(pack_multiple=2.0), "I2": _item(pack_multiple=2.0)},
        "supplier": _supplier(order_days=[D0.isoweekday()], min_order_units=2.0),
        "as_of": D0,
        "max_additional_packs_for_minimum": 5,
    }

    result_a = apply_supplier_constraints(desired, **kwargs)
    result_b = apply_supplier_constraints(dict(desired), **kwargs)

    assert result_a.order == result_b.order == {"I1": 2.0, "I2": 0.0}  # I1 vence o empate
    assert result_a.adjustments == result_b.adjustments


# --------------------------------------------------------------------------
# auxiliares
# --------------------------------------------------------------------------


def test_item_ids_desalinhados_levanta_erro() -> None:
    with pytest.raises(ValueError, match="position"):
        apply_supplier_constraints(
            {"A": 1.0},
            position={"B": 0.0},
            expected_daily_demand={"A": 1.0},
            item_purchase_info={"A": _item(pack_multiple=1.0)},
            supplier=_supplier(order_days=[D0.isoweekday()]),
            as_of=D0,
            max_additional_packs_for_minimum=0,
        )


def test_min_order_zero_nunca_bloqueia() -> None:
    result = apply_supplier_constraints(
        {"A": 3.0},
        position={"A": 0.0},
        expected_daily_demand={"A": 1.0},
        item_purchase_info={"A": _item(pack_multiple=1.0)},
        supplier=_supplier(order_days=[D0.isoweekday()], min_order_value=0.0, min_order_units=0.0),
        as_of=D0,
        max_additional_packs_for_minimum=0,
    )
    assert result.outcome == OrderOutcome.PEDIDO_EMITIDO
    assert result.order == {"A": 3.0}
