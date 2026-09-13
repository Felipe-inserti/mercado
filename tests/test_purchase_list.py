"""Testes de `motor.reporting.purchase_list` (Sprint 5, Etapas 3.14-3.16).

Só as funções puras/de composição (`_trailing_avg_daily_demand`,
`_coverage_days`, `_build_supplier_list`, `_classify_new_items`,
`_apply_item_level_guardrails`, `_finalize_with_cash_constraint`) --
`generate_purchase_list` roda o pipeline inteiro (subconjunto, forecaster,
simulador por item) e é caro demais para teste automatizado, mesmo
espírito de `tests/test_sensitivity.py` e `tests/test_iso_service.py`.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from motor.config import load_params
from motor.io.contracts import UnitOfSale
from motor.policy.guardrails import CategoryFloorAlert, GuardrailReason
from motor.policy.supplier import ItemPurchaseInfo, OrderOutcome
from motor.reporting.purchase_list import (
    PurchaseListRow,
    SupplierPurchaseList,
    _apply_item_level_guardrails,
    _build_supplier_list,
    _classify_new_items,
    _coverage_days,
    _cycle_budget_rs,
    _finalize_with_cash_constraint,
    _first_sale_and_days_with_sales,
    _ItemDecisions,
    _min_order_value_for,
    _pack_multiple_for,
    _trailing_avg_daily_demand,
)

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"
D0 = date(2024, 1, 1)
assert D0.isoweekday() == 1  # segunda -- premissa de calendário dos testes abaixo


@pytest.fixture(scope="module")
def cell_params():
    return load_params(PARAMS_PATH)


# --------------------------------------------------------------------------
# _trailing_avg_daily_demand
# --------------------------------------------------------------------------


def test_trailing_avg_daily_demand_usa_so_a_janela_antes_de_as_of() -> None:
    # janela de 28 dias antes de D0=2024-01-01 começa em 2023-12-04 --
    # 2023-12-01 fica FORA (antes da janela) e 2024-01-01 fica FORA
    # (é as_of, não antes); só 2023-12-20 conta.
    history = pl.DataFrame(
        {
            "date": [date(2023, 12, 1), date(2023, 12, 20), date(2024, 1, 1)],
            "units_sold": [100.0, 10.0, 999.0],
        }
    )
    resultado = _trailing_avg_daily_demand(history, D0)
    assert resultado == pytest.approx(10.0)


def test_trailing_avg_daily_demand_sem_venda_na_janela_e_zero() -> None:
    history = pl.DataFrame({"date": [date(2020, 1, 1)], "units_sold": [50.0]})
    assert _trailing_avg_daily_demand(history, D0) == 0.0


# --------------------------------------------------------------------------
# premissas de fornecedor realistas (Etapa 3.15)
# --------------------------------------------------------------------------


def test_pack_multiple_for_segue_a_familia_declarada_em_params_yaml(cell_params) -> None:
    # perecível fresco vendido a peça/peso -- sem fardo real
    assert _pack_multiple_for("SEAFOOD", cell_params) == 1.0
    # giro rápido, fardo pequeno
    assert _pack_multiple_for("DAIRY", cell_params) == 6.0
    # mercearia seca, fardo padrão
    assert _pack_multiple_for("GROCERY I", cell_params) == 12.0
    # bebidas, pallet fechado
    assert _pack_multiple_for("BEVERAGES", cell_params) == 24.0


def test_min_order_value_for_e_zero_para_categoria_grande_e_2000_para_pequena(cell_params) -> None:
    # GROCERY I: 1334 itens no canônico -- >= 50, sem mínimo
    assert _min_order_value_for("GROCERY I", cell_params) == 0.0
    # SEAFOOD: 8 itens no canônico -- < 50, mínimo de R$ 2.000
    assert _min_order_value_for("SEAFOOD", cell_params) == 2000.0


# --------------------------------------------------------------------------
# _cycle_budget_rs (Etapa 3.16.3 -- bug de escala corrigido)
# --------------------------------------------------------------------------


def test_cycle_budget_rs_multiplica_pela_razao_do_ciclo_sobre_a_semana() -> None:
    # review_period=14 dias -- ciclo de 2 semanas, orçamento dobra.
    assert _cycle_budget_rs(250_000.0, 14) == pytest.approx(500_000.0)


def test_cycle_budget_rs_com_ciclo_de_uma_semana_nao_altera_o_valor() -> None:
    assert _cycle_budget_rs(250_000.0, 7) == pytest.approx(250_000.0)


# --------------------------------------------------------------------------
# _coverage_days
# --------------------------------------------------------------------------


def test_coverage_days_divide_posicao_pela_demanda_esperada() -> None:
    assert _coverage_days(100.0, 10.0) == pytest.approx(10.0)


def test_coverage_days_none_sem_demanda_esperada() -> None:
    # Sem isso, dividir por zero viraria um número gigante disfarçado de
    # cobertura real -- ausência declarada é melhor que infinito silencioso.
    assert _coverage_days(100.0, 0.0) is None


# --------------------------------------------------------------------------
# _build_supplier_list
# --------------------------------------------------------------------------


def _decisions(
    *,
    desired: dict[str, float],
    on_hand: dict[str, float],
    in_transit: dict[str, float],
    category: str = "GROCERY I",
    category_of: dict[str, str] | None = None,
    recent_average_purchase: dict[str, float] | None = None,
    first_sale_date: dict[str, date | None] | None = None,
    days_with_sales: dict[str, int] | None = None,
    risk_window_days: dict[str, float] | None = None,
) -> _ItemDecisions:
    item_ids = list(desired)
    return _ItemDecisions(
        desired=desired,
        on_hand=on_hand,
        in_transit=in_transit,
        expected_daily_demand=dict.fromkeys(item_ids, 1.0),
        recent_average_purchase=recent_average_purchase or dict.fromkeys(item_ids, 0.0),
        first_sale_date=first_sale_date or dict.fromkeys(item_ids, D0 - timedelta(days=200)),
        days_with_sales=days_with_sales or dict.fromkeys(item_ids, 150),
        margin_pct=dict.fromkeys(item_ids, 0.3),
        # default 0.0 -- sem piso de janela de risco por padrão nos testes que
        # não testam o piso (Etapa 3.16.2); com validade sempre >= 0.0 isso
        # nunca conflita, preservando o comportamento anterior dos testes que
        # não passam este argumento.
        risk_window_days=risk_window_days or dict.fromkeys(item_ids, 0.0),
        item_purchase_info={
            item_id: ItemPurchaseInfo(pack_multiple=1.0, cost=2.0, unit_of_sale=UnitOfSale.UNIDADE)
            for item_id in item_ids
        },
        supplier_of=dict.fromkeys(item_ids, "SUP1"),
        category_of=category_of or dict.fromkeys(item_ids, category),
    )


def _sup_row(*, order_days: list[int]) -> dict[str, object]:
    return {
        "lead_time_days": 3,
        "order_days": order_days,
        "review_period_days": 7,
        "min_order_value": 0.0,
        "min_order_units": 0.0,
    }


def test_build_supplier_list_fora_do_calendario_devolve_none(cell_params) -> None:
    decisions = _decisions(desired={"A": 5.0}, on_hand={"A": 0.0}, in_transit={"A": 0.0})
    resultado = _build_supplier_list(
        "SUP1",
        ["A"],
        sup_row=_sup_row(order_days=[2, 3, 4, 5, 6]),  # não inclui segunda
        decisions=decisions,
        final_desired=decisions.desired,
        guardrail_flags={},
        cell_params=cell_params,
        as_of=D0,
    )
    assert resultado is None


def test_build_supplier_list_sem_ajuste_vai_pra_lista_principal(cell_params) -> None:
    # 5.0 já é múltiplo de pack_multiple=1.0 -- nenhum ajuste, nenhuma exceção.
    decisions = _decisions(desired={"A": 5.0}, on_hand={"A": 0.0}, in_transit={"A": 0.0})
    resultado = _build_supplier_list(
        "SUP1",
        ["A"],
        sup_row=_sup_row(order_days=[1, 2, 3, 4, 5]),
        decisions=decisions,
        final_desired=decisions.desired,
        guardrail_flags={},
        cell_params=cell_params,
        as_of=D0,
    )
    assert resultado is not None
    assert resultado.outcome == OrderOutcome.PEDIDO_EMITIDO
    assert len(resultado.main) == 1
    assert len(resultado.exceptions) == 0
    assert resultado.main[0].quantity_units == 5.0
    assert resultado.main[0].adjustments == ()


def test_build_supplier_list_arredondamento_de_fardo_nao_e_excecao(cell_params) -> None:
    # 5.3 arredonda pra 6.0 (pack_multiple=1.0) -- é ajuste de rotina, não
    # exceção (ver docstring do módulo: listar isso como exceção inflaria a
    # lista sem sinal útil, porque dispara em quase todo item real).
    decisions = _decisions(desired={"A": 5.3}, on_hand={"A": 0.0}, in_transit={"A": 0.0})
    resultado = _build_supplier_list(
        "SUP1",
        ["A"],
        sup_row=_sup_row(order_days=[1, 2, 3, 4, 5]),
        decisions=decisions,
        final_desired=decisions.desired,
        guardrail_flags={},
        cell_params=cell_params,
        as_of=D0,
    )
    assert resultado is not None
    assert len(resultado.main) == 1
    assert len(resultado.exceptions) == 0
    assert resultado.main[0].quantity_units == 6.0
    assert "arredondado" in resultado.main[0].adjustments[0]


def test_build_supplier_list_pedido_adiado_e_excecao(cell_params) -> None:
    # min_order_units=1000 inatingível com um único item de demanda 1.0/dia
    # e max_additional_packs_for_minimum de params.yaml (10, bem menor que
    # o necessário) -- pedido inteiro adiado, PEDIDO_ADIADO é exceção.
    decisions = _decisions(desired={"A": 5.0}, on_hand={"A": 0.0}, in_transit={"A": 0.0})
    sup_row = _sup_row(order_days=[1, 2, 3, 4, 5])
    sup_row["min_order_units"] = 1000.0
    resultado = _build_supplier_list(
        "SUP1",
        ["A"],
        sup_row=sup_row,
        decisions=decisions,
        final_desired=decisions.desired,
        guardrail_flags={},
        cell_params=cell_params,
        as_of=D0,
    )
    assert resultado is not None
    assert resultado.outcome == OrderOutcome.MINIMO_INATINGIVEL
    assert len(resultado.main) == 0
    assert len(resultado.exceptions) == 1
    assert resultado.exceptions[0].quantity_units == 0.0
    assert resultado.exceptions[0].is_exception


def test_build_supplier_list_usa_min_order_value_da_categoria_nao_do_sup_row(cell_params) -> None:
    # SEAFOOD tem min_order_value_by_category=2000,0 (Etapa 3.15) -- sup_row
    # (que simula o canônico) diz 0,0. O valor que vale é o da categoria: um
    # item de R$2,00/unidade e 5 unidades desejadas (R$10) fica muito abaixo
    # de R$2.000 -- ou preenche até o mínimo ou fica inatingível, nunca
    # PEDIDO_EMITIDO puro.
    decisions = _decisions(
        desired={"A": 5.0}, on_hand={"A": 0.0}, in_transit={"A": 0.0}, category="SEAFOOD"
    )
    sup_row = _sup_row(order_days=[1, 2, 3, 4, 5])
    assert sup_row["min_order_value"] == 0.0  # premissa "canônico" -- não é o que deve valer
    resultado = _build_supplier_list(
        "SUP1",
        ["A"],
        sup_row=sup_row,
        decisions=decisions,
        final_desired=decisions.desired,
        guardrail_flags={},
        cell_params=cell_params,
        as_of=D0,
    )
    assert resultado is not None
    assert resultado.min_order_value == 2000.0
    assert resultado.outcome == OrderOutcome.MINIMO_INATINGIVEL


def test_build_supplier_list_rejeita_fornecedor_com_categorias_misturadas(cell_params) -> None:
    decisions = _decisions(
        desired={"A": 5.0, "B": 3.0},
        on_hand={"A": 0.0, "B": 0.0},
        in_transit={"A": 0.0, "B": 0.0},
        category_of={"A": "GROCERY I", "B": "SEAFOOD"},
    )
    with pytest.raises(ValueError, match="categorias diferentes"):
        _build_supplier_list(
            "SUP1",
            ["A", "B"],
            sup_row=_sup_row(order_days=[1, 2, 3, 4, 5]),
            decisions=decisions,
            final_desired=decisions.desired,
            guardrail_flags={},
            cell_params=cell_params,
            as_of=D0,
        )


# --------------------------------------------------------------------------
# _first_sale_and_days_with_sales (Etapa 3.16)
# --------------------------------------------------------------------------


def test_first_sale_and_days_with_sales_ignora_datas_a_partir_de_as_of() -> None:
    demand = pl.DataFrame(
        {
            "date": [date(2023, 1, 1), date(2023, 6, 1), D0, D0 + timedelta(days=1)],
            "units_sold": [5.0, 3.0, 999.0, 999.0],  # os dois últimos são >= as_of -- não contam
        }
    )
    primeira, dias_com_venda = _first_sale_and_days_with_sales(demand, D0)
    assert primeira == date(2023, 1, 1)
    assert dias_com_venda == 2


def test_first_sale_and_days_with_sales_ignora_dias_de_venda_zero() -> None:
    demand = pl.DataFrame({"date": [date(2023, 1, 1), date(2023, 1, 2)], "units_sold": [0.0, 4.0]})
    primeira, dias_com_venda = _first_sale_and_days_with_sales(demand, D0)
    assert primeira == date(2023, 1, 2)
    assert dias_com_venda == 1


def test_first_sale_and_days_with_sales_sem_nenhuma_venda() -> None:
    demand = pl.DataFrame({"date": [date(2023, 1, 1)], "units_sold": [0.0]})
    assert _first_sale_and_days_with_sales(demand, D0) == (None, 0)


# --------------------------------------------------------------------------
# _classify_new_items (Etapa 3.16)
# --------------------------------------------------------------------------


def test_classify_new_items_usa_os_limiares_de_params_yaml(cell_params) -> None:
    # params.yaml: new_item_min_history_days=90, new_item_min_days_with_sales=30
    item_ids = ["VELHO", "NOVO_POR_HISTORICO", "NOVO_POR_DIAS_COM_VENDA", "NUNCA_VENDEU"]
    decisions = _decisions(
        desired=dict.fromkeys(item_ids, 1.0),
        on_hand=dict.fromkeys(item_ids, 0.0),
        in_transit=dict.fromkeys(item_ids, 0.0),
        first_sale_date={
            "VELHO": D0 - timedelta(days=200),
            "NOVO_POR_HISTORICO": D0 - timedelta(days=60),
            "NOVO_POR_DIAS_COM_VENDA": D0 - timedelta(days=200),
            "NUNCA_VENDEU": None,
        },
        days_with_sales={
            "VELHO": 150,
            "NOVO_POR_HISTORICO": 50,
            "NOVO_POR_DIAS_COM_VENDA": 10,
            "NUNCA_VENDEU": 0,
        },
    )
    resultado = _classify_new_items(decisions, cell_params, D0)
    assert resultado == {
        "VELHO": False,
        "NOVO_POR_HISTORICO": True,
        "NOVO_POR_DIAS_COM_VENDA": True,
        "NUNCA_VENDEU": True,
    }


# --------------------------------------------------------------------------
# _apply_item_level_guardrails (Etapa 3.16)
# --------------------------------------------------------------------------


def test_apply_item_level_guardrails_corta_por_teto_de_cobertura(cell_params) -> None:
    # MEATS: perecível fresco, teto de 7 dias (params.yaml). posição=0,
    # demanda=10/dia -> cap=70; pedido de 200 é cortado.
    decisions = _decisions(
        desired={"A": 200.0},
        on_hand={"A": 0.0},
        in_transit={"A": 0.0},
        category="MEATS",
    )
    decisions.expected_daily_demand["A"] = 10.0
    quantidades, flags = _apply_item_level_guardrails(
        decisions, is_new={"A": False}, cell_params=cell_params
    )
    assert quantidades["A"] == 70.0
    assert any(f.reason == GuardrailReason.TETO_DE_COBERTURA for f in flags["A"])


def test_apply_item_level_guardrails_usa_piso_da_janela_de_risco(cell_params) -> None:
    # MEATS: validade de 7 dias (params.yaml), mas com risk_window_days=21
    # (célula lt=7/rp=14, Etapa 3.16.2) o piso vence -- cap efetivo=210, não 70.
    decisions = _decisions(
        desired={"A": 200.0},
        on_hand={"A": 0.0},
        in_transit={"A": 0.0},
        category="MEATS",
        risk_window_days={"A": 21.0},
    )
    decisions.expected_daily_demand["A"] = 10.0
    quantidades, flags = _apply_item_level_guardrails(
        decisions, is_new={"A": False}, cell_params=cell_params
    )
    assert quantidades["A"] == 200.0  # NÃO cortada -- 200 < cap efetivo (210)
    flag = next(f for f in flags["A"] if f.reason == GuardrailReason.TETO_DE_COBERTURA)
    assert "incompatível com a família" in flag.detail


def test_apply_item_level_guardrails_sinaliza_variacao_sem_cortar(cell_params) -> None:
    decisions = _decisions(
        desired={"A": 250.0},
        on_hand={"A": 0.0},
        in_transit={"A": 0.0},
        category="GROCERY I",  # teto de 45 dias -- bem acima, não corta por cobertura
        recent_average_purchase={"A": 100.0},
    )
    # demanda alta o bastante para o teto de cobertura (45 dias x 100 = 4500)
    # não ser o gargalo -- só a variação importa neste teste.
    decisions.expected_daily_demand["A"] = 100.0
    quantidades, flags = _apply_item_level_guardrails(
        decisions, is_new={"A": False}, cell_params=cell_params
    )
    assert quantidades["A"] == 250.0  # NÃO cortada
    assert any(f.reason == GuardrailReason.LIMITE_DE_VARIACAO for f in flags["A"])


def test_apply_item_level_guardrails_item_novo_usa_mediana_da_categoria(cell_params) -> None:
    decisions = _decisions(
        desired={"VELHO1": 10.0, "VELHO2": 30.0, "NOVO": 999.0},
        on_hand=dict.fromkeys(["VELHO1", "VELHO2", "NOVO"], 0.0),
        in_transit=dict.fromkeys(["VELHO1", "VELHO2", "NOVO"], 0.0),
        category="GROCERY I",
    )
    for item_id in ("VELHO1", "VELHO2", "NOVO"):
        decisions.expected_daily_demand[item_id] = 0.0  # sem teto de cobertura no caminho
    quantidades, flags = _apply_item_level_guardrails(
        decisions,
        is_new={"VELHO1": False, "VELHO2": False, "NOVO": True},
        cell_params=cell_params,
    )
    assert quantidades["NOVO"] == 20.0  # mediana de [10.0, 30.0]
    novo_flag = next(f for f in flags["NOVO"] if f.reason == GuardrailReason.ITEM_NOVO)
    assert novo_flag.adjusted_quantity == 20.0
    assert novo_flag.original_quantity == 999.0  # sugestão do modelo, só para auditoria
    assert "NOVO" not in flags or all(
        f.reason == GuardrailReason.ITEM_NOVO for f in flags["NOVO"]
    )  # item novo não passa por 1/2


def test_apply_item_level_guardrails_item_novo_sem_referencia_usa_mediana_global(
    cell_params,
) -> None:
    # categoria inteira composta só de itens novos -- sem mediana própria,
    # cai na mediana global (calculada sobre os não-novos de OUTRA categoria)
    decisions = _decisions(
        desired={"OUTRA_CAT": 40.0, "NOVO1": 5.0, "NOVO2": 5.0},
        on_hand=dict.fromkeys(["OUTRA_CAT", "NOVO1", "NOVO2"], 0.0),
        in_transit=dict.fromkeys(["OUTRA_CAT", "NOVO1", "NOVO2"], 0.0),
        category_of={"OUTRA_CAT": "GROCERY I", "NOVO1": "SEAFOOD", "NOVO2": "SEAFOOD"},
    )
    for item_id in ("OUTRA_CAT", "NOVO1", "NOVO2"):
        decisions.expected_daily_demand[item_id] = 0.0
    quantidades, flags = _apply_item_level_guardrails(
        decisions,
        is_new={"OUTRA_CAT": False, "NOVO1": True, "NOVO2": True},
        cell_params=cell_params,
    )
    assert quantidades["NOVO1"] == 40.0  # mediana global (só há 1 valor não-novo: 40.0)
    flag = next(f for f in flags["NOVO1"] if f.reason == GuardrailReason.ITEM_NOVO)
    assert "mediana global" in flag.detail


# --------------------------------------------------------------------------
# _finalize_with_cash_constraint (Etapa 3.16)
# --------------------------------------------------------------------------


def _row(
    item_id: str,
    *,
    value_rs: float,
    margin_pct: float,
    is_exception: bool = False,
    category: str = "GROCERY I",
) -> PurchaseListRow:
    return PurchaseListRow(
        item_id=item_id,
        category=category,
        unit_of_sale="unidade",
        quantity_units=10.0,
        quantity_packs=10.0,
        on_hand=0.0,
        in_transit=0.0,
        coverage_days_after_order=5.0,
        value_rs=value_rs,
        margin_pct=margin_pct,
        adjustments=(),
        is_exception=is_exception,
    )


# Nos três testes abaixo, `category_floor_fraction=0.0` desliga o piso por
# categoria (Etapa 3.16.4) -- ver a mesma observação em
# `tests/test_guardrails.py`, bloco "4.1 Piso por categoria".


def test_finalize_with_cash_constraint_corta_e_move_para_excecoes() -> None:
    sup_a = SupplierPurchaseList(
        supplier_id="SUP-A",
        category="GROCERY I",
        outcome=OrderOutcome.PEDIDO_EMITIDO,
        min_order_value=0.0,
        main=(
            _row("ALTA_MARGEM", value_rs=800.0, margin_pct=0.5),
            _row("BAIXA_MARGEM", value_rs=300.0, margin_pct=0.1),
        ),
        exceptions=(),
    )
    finalizados, cash_flags, alert = _finalize_with_cash_constraint(
        {"SUP-A": sup_a}, budget_rs=850.0, category_floor_fraction=0.0
    )

    resultado = finalizados["SUP-A"]
    assert len(resultado.main) == 1
    assert resultado.main[0].item_id == "ALTA_MARGEM"
    assert len(resultado.exceptions) == 1
    cortado = resultado.exceptions[0]
    assert cortado.item_id == "BAIXA_MARGEM"
    assert cortado.quantity_units == 0.0
    assert cortado.value_rs == 0.0
    assert cortado.is_exception
    assert len(cash_flags) == 1
    assert cash_flags[0].reason == GuardrailReason.RESTRICAO_DE_CAIXA
    assert alert is None


def test_finalize_with_cash_constraint_dentro_do_orcamento_nao_move_nada() -> None:
    sup_a = SupplierPurchaseList(
        supplier_id="SUP-A",
        category="GROCERY I",
        outcome=OrderOutcome.PEDIDO_EMITIDO,
        min_order_value=0.0,
        main=(_row("A", value_rs=100.0, margin_pct=0.3),),
        exceptions=(),
    )
    finalizados, cash_flags, alert = _finalize_with_cash_constraint(
        {"SUP-A": sup_a}, budget_rs=1000.0, category_floor_fraction=0.0
    )
    assert finalizados["SUP-A"].main == sup_a.main
    assert finalizados["SUP-A"].exceptions == ()
    assert cash_flags == ()
    assert alert is None


def test_finalize_with_cash_constraint_preserva_excecao_ja_existente() -> None:
    # item já em exceções por outro motivo (ex.: item novo) continua lá,
    # mesmo cabendo tranquilamente no orçamento.
    ja_excecao = _row("JA_EXCECAO", value_rs=1.0, margin_pct=0.9, is_exception=True)
    sup_a = SupplierPurchaseList(
        supplier_id="SUP-A",
        category="GROCERY I",
        outcome=OrderOutcome.PEDIDO_EMITIDO,
        min_order_value=0.0,
        main=(),
        exceptions=(ja_excecao,),
    )
    finalizados, _flags, _alert = _finalize_with_cash_constraint(
        {"SUP-A": sup_a}, budget_rs=1000.0, category_floor_fraction=0.0
    )
    assert finalizados["SUP-A"].exceptions == (ja_excecao,)
    assert finalizados["SUP-A"].main == ()


def test_finalize_with_cash_constraint_piso_protege_e_marca_como_excecao() -> None:
    # SUP-A (MEATS): M_LO pior margem (.05, R$100), M_HI melhor margem
    # entre os dois (.10, R$300) -- piso 60% de R$400 = R$240; M_HI
    # sozinho (R$300) já garante isso, M_LO vira excedente. SUP-B
    # (BEVERAGES): mesma forma, mas com margens muito mais altas -- no
    # corte por margem GLOBAL puro (sem piso), M_HI perderia para
    # BEV_HI e BEV_LO (que juntos já ocupam o orçamento) -- com o piso,
    # M_HI é garantido mesmo assim, e é BEV_LO quem paga o custo.
    sup_a = SupplierPurchaseList(
        supplier_id="SUP-A",
        category="MEATS",
        outcome=OrderOutcome.PEDIDO_EMITIDO,
        min_order_value=0.0,
        main=(
            _row("M_LO", value_rs=100.0, margin_pct=0.05, category="MEATS"),
            _row("M_HI", value_rs=300.0, margin_pct=0.10, category="MEATS"),
        ),
        exceptions=(),
    )
    sup_b = SupplierPurchaseList(
        supplier_id="SUP-B",
        category="BEVERAGES",
        outcome=OrderOutcome.PEDIDO_EMITIDO,
        min_order_value=0.0,
        main=(
            _row("BEV_LO", value_rs=100.0, margin_pct=0.30, category="BEVERAGES"),
            _row("BEV_HI", value_rs=300.0, margin_pct=0.95, category="BEVERAGES"),
        ),
        exceptions=(),
    )
    finalizados, cash_flags, alert = _finalize_with_cash_constraint(
        {"SUP-A": sup_a, "SUP-B": sup_b}, budget_rs=650.0, category_floor_fraction=0.6
    )
    assert alert is None

    ids_principal_a = {r.item_id for r in finalizados["SUP-A"].main}
    ids_excecao_a = {r.item_id for r in finalizados["SUP-A"].exceptions}
    assert "M_HI" in ids_excecao_a  # protegido -- ainda vira exceção (visibilidade)
    protegido = next(r for r in finalizados["SUP-A"].exceptions if r.item_id == "M_HI")
    assert protegido.quantity_units == 10.0  # protegido preserva a quantidade original
    assert protegido.value_rs == 300.0
    assert any("protegido pelo piso de categoria" in a for a in protegido.adjustments)
    assert "M_LO" in ids_excecao_a
    cortado = next(r for r in finalizados["SUP-A"].exceptions if r.item_id == "M_LO")
    assert cortado.quantity_units == 0.0
    assert "M_HI" not in ids_principal_a
    # BEV_HI sobrevive por mérito próprio -- sem flag de "protegido"
    assert "BEV_HI" in {r.item_id for r in finalizados["SUP-B"].main}

    motivos = {f.item_id: f for f in cash_flags}
    assert "protegido pelo piso de categoria" in motivos["M_HI"].detail
    assert "reduzido por restrição de caixa" in motivos["M_LO"].detail
    assert "reduzido por restrição de caixa" in motivos["BEV_LO"].detail
    assert "BEV_HI" not in motivos


def test_finalize_with_cash_constraint_piso_estoura_orcamento_gera_alerta() -> None:
    sup_a = SupplierPurchaseList(
        supplier_id="SUP-A",
        category="MEATS",
        outcome=OrderOutcome.PEDIDO_EMITIDO,
        min_order_value=0.0,
        main=(_row("M", value_rs=600.0, margin_pct=0.20, category="MEATS"),),
        exceptions=(),
    )
    sup_b = SupplierPurchaseList(
        supplier_id="SUP-B",
        category="SEAFOOD",
        outcome=OrderOutcome.PEDIDO_EMITIDO,
        min_order_value=0.0,
        main=(_row("S", value_rs=500.0, margin_pct=0.10, category="SEAFOOD"),),
        exceptions=(),
    )
    _finalizados, _cash_flags, alert = _finalize_with_cash_constraint(
        {"SUP-A": sup_a, "SUP-B": sup_b}, budget_rs=800.0, category_floor_fraction=0.6
    )
    assert isinstance(alert, CategoryFloorAlert)
    assert alert.total_floor_rs == 1100.0
    assert alert.budget_rs == 800.0
    assert alert.shortfall_rs == 300.0
