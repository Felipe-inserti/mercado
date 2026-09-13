"""Testes de `motor.policy.guardrails` (Sprint 13, Etapa 3.16) -- lógica
pura, sem simulador, sem `Params`, mesma disciplina de
`tests/test_supplier.py`. Cada regra tem seu próprio bloco, incluindo o
caso de NÃO-disparo -- pedido do enunciado da etapa, e é o que distingue
"a regra não achou nada" de "a regra não foi checada".
"""

from __future__ import annotations

from datetime import date, timedelta

from motor.policy.guardrails import (
    NOT_IMPLEMENTED_GUARDRAILS,
    CashConstraintCandidate,
    CategoryFloorAlert,
    GuardrailReason,
    apply_cash_constraint,
    apply_coverage_cap,
    check_order_variation,
    is_new_item,
    new_item_quantity,
)

D0 = date(2024, 1, 1)


# --------------------------------------------------------------------------
# 1. Teto de cobertura
# --------------------------------------------------------------------------


def test_apply_coverage_cap_corta_sem_conflito_quando_validade_cobre_a_janela() -> None:
    # validade=45, janela=21 -- validade vence, sem conflito. posição=0,
    # demanda=10/dia -> cap efetivo=450; pedido de 1000 corta pra 450.
    quantidade, flag = apply_coverage_cap(
        "A",
        1000.0,
        position=0.0,
        expected_daily_demand=10.0,
        shelf_life_days=45.0,
        risk_window_days=21.0,
    )
    assert quantidade == 450.0
    assert flag is not None
    assert flag.reason == GuardrailReason.TETO_DE_COBERTURA
    assert flag.original_quantity == 1000.0
    assert flag.adjusted_quantity == 450.0
    assert "450.00" in flag.detail
    assert "incompatível" not in flag.detail  # sem conflito -- validade já cobre a janela


def test_apply_coverage_cap_nao_dispara_dentro_do_teto_efetivo() -> None:
    quantidade, flag = apply_coverage_cap(
        "A",
        50.0,
        position=0.0,
        expected_daily_demand=10.0,
        shelf_life_days=45.0,
        risk_window_days=21.0,
    )
    assert quantidade == 50.0
    assert flag is None


def test_apply_coverage_cap_considera_posicao_existente() -> None:
    # validade=45, janela=21 -- cap efetivo=450; posição já em 400 -> só cabe mais 50
    quantidade, flag = apply_coverage_cap(
        "A",
        100.0,
        position=400.0,
        expected_daily_demand=10.0,
        shelf_life_days=45.0,
        risk_window_days=21.0,
    )
    assert quantidade == 50.0
    assert flag is not None


def test_apply_coverage_cap_nao_dispara_sem_demanda_esperada() -> None:
    # sem demanda, "dias de cobertura" não tem denominador -- não corta,
    # não é assunto desta regra (é assunto de is_new_item)
    quantidade, flag = apply_coverage_cap(
        "A",
        100.0,
        position=0.0,
        expected_daily_demand=0.0,
        shelf_life_days=7.0,
        risk_window_days=21.0,
    )
    assert quantidade == 100.0
    assert flag is None


def test_apply_coverage_cap_nao_dispara_com_quantidade_zero() -> None:
    quantidade, flag = apply_coverage_cap(
        "A",
        0.0,
        position=0.0,
        expected_daily_demand=10.0,
        shelf_life_days=7.0,
        risk_window_days=21.0,
    )
    assert quantidade == 0.0
    assert flag is None


# -- piso da janela de risco (Etapa 3.16.2) --------------------------------


def test_apply_coverage_cap_registra_conflito_e_corta_quando_janela_vence_validade() -> None:
    # validade=7, janela=21 -- janela vence (piso). demanda=10/dia, posição=0:
    # shelf_life_cap=70, cap_efetivo=210. pedido de 300 excede os dois.
    quantidade, flag = apply_coverage_cap(
        "A",
        300.0,
        position=0.0,
        expected_daily_demand=10.0,
        shelf_life_days=7.0,
        risk_window_days=21.0,
    )
    assert quantidade == 210.0  # cortado pelo PISO (janela), não pela validade (70)
    assert flag is not None
    assert "incompatível com a família" in flag.detail
    assert "7d" in flag.detail and "21d" in flag.detail
    assert "cortado de 300.00 para 210.00" in flag.detail


def test_apply_coverage_cap_registra_conflito_sem_cortar_quando_cabe_no_piso() -> None:
    # mesma validade/janela incompatíveis, mas o pedido (150) excede o teto de
    # validade (70) -- por isso o conflito importa para este item -- e ainda
    # assim cabe dentro do piso (210) -- não corta, só registra o conflito.
    quantidade, flag = apply_coverage_cap(
        "A",
        150.0,
        position=0.0,
        expected_daily_demand=10.0,
        shelf_life_days=7.0,
        risk_window_days=21.0,
    )
    assert quantidade == 150.0  # NÃO cortada
    assert flag is not None
    assert flag.original_quantity == 150.0
    assert flag.adjusted_quantity == 150.0
    assert "incompatível com a família" in flag.detail
    assert "cortado" not in flag.detail  # só o registro do conflito, sem corte


def test_apply_coverage_cap_nao_registra_conflito_se_nao_importaria_para_o_item() -> None:
    # validade/janela incompatíveis (7 < 21), mas o pedido (50) nem chega a
    # exceder o teto de validade sozinho (70) -- o conflito nunca teria
    # importado para ESTE item, então não registra nada.
    quantidade, flag = apply_coverage_cap(
        "A",
        50.0,
        position=0.0,
        expected_daily_demand=10.0,
        shelf_life_days=7.0,
        risk_window_days=21.0,
    )
    assert quantidade == 50.0
    assert flag is None


# --------------------------------------------------------------------------
# 2. Limite de variação
# --------------------------------------------------------------------------


def test_check_order_variation_sinaliza_acima_do_limite_sem_alterar_quantidade() -> None:
    flag = check_order_variation("A", 250.0, recent_average_purchase=100.0, limit_multiple=2.0)
    assert flag is not None
    assert flag.reason == GuardrailReason.LIMITE_DE_VARIACAO
    assert flag.original_quantity == 250.0
    assert flag.adjusted_quantity == 250.0  # sinaliza, NÃO corta
    assert "2.5x" in flag.detail


def test_check_order_variation_nao_dispara_dentro_do_limite() -> None:
    flag = check_order_variation("A", 200.0, recent_average_purchase=100.0, limit_multiple=2.0)
    assert flag is None  # exatamente 2x -- limite é "acima de", não "a partir de"


def test_check_order_variation_nao_dispara_sem_historico_de_compra() -> None:
    # média <= 0 -- item sem histórico de compra suficiente (item novo, ou
    # nenhum ciclo de revisão ainda passou) cai na regra 4, não nesta
    flag = check_order_variation("A", 250.0, recent_average_purchase=0.0, limit_multiple=2.0)
    assert flag is None


# --------------------------------------------------------------------------
# 3. Item novo
# --------------------------------------------------------------------------


def test_is_new_item_true_sem_nenhuma_venda_registrada() -> None:
    assert is_new_item(
        first_sale_date=None,
        days_with_sales=0,
        as_of=D0,
        min_history_days=90,
        min_days_with_sales=30,
    )


def test_is_new_item_true_com_historico_curto() -> None:
    assert is_new_item(
        first_sale_date=D0 - timedelta(days=60),  # < 90 dias de histórico
        days_with_sales=40,
        as_of=D0,
        min_history_days=90,
        min_days_with_sales=30,
    )


def test_is_new_item_true_com_poucos_dias_de_venda_mesmo_com_historico_longo() -> None:
    assert is_new_item(
        first_sale_date=D0 - timedelta(days=200),  # histórico longo
        days_with_sales=10,  # mas poucos dias com venda de fato (item de cauda)
        as_of=D0,
        min_history_days=90,
        min_days_with_sales=30,
    )


def test_is_new_item_false_com_historico_e_vendas_suficientes() -> None:
    assert not is_new_item(
        first_sale_date=D0 - timedelta(days=200),
        days_with_sales=150,
        as_of=D0,
        min_history_days=90,
        min_days_with_sales=30,
    )


def test_new_item_quantity_usa_mediana_da_categoria_nao_o_modelo() -> None:
    flag = new_item_quantity(
        "A",
        model_suggested_quantity=999.0,
        category_median_quantity=12.0,
        used_global_fallback=False,
    )
    assert flag.reason == GuardrailReason.ITEM_NOVO
    assert flag.adjusted_quantity == 12.0  # nunca o que o modelo sugeriu
    assert flag.original_quantity == 999.0  # guardado só para auditoria
    assert "mediana global" not in flag.detail


def test_new_item_quantity_declara_fallback_global_no_detail() -> None:
    flag = new_item_quantity(
        "A", model_suggested_quantity=5.0, category_median_quantity=8.0, used_global_fallback=True
    )
    assert "mediana global" in flag.detail


# --------------------------------------------------------------------------
# 4. Restrição de caixa
# --------------------------------------------------------------------------


# Nos quatro testes abaixo, `category_floor_fraction=0.0` desliga o piso
# por categoria (Etapa 3.16.4) -- com piso zero, todo item vira "excedente"
# (ver `_split_floor_and_headroom`) e o comportamento se reduz exatamente
# ao "corte do fim" puro por margem, de antes da Etapa 3.16.4. A categoria
# em si é irrelevante para esses quatro testes; usamos uma única categoria
# "CAT" para todos os candidatos.


def test_apply_cash_constraint_mantem_tudo_dentro_do_orcamento() -> None:
    candidatos = [
        CashConstraintCandidate("A", category="CAT", quantity=10.0, value_rs=100.0, margin_pct=0.3),
        CashConstraintCandidate("B", category="CAT", quantity=5.0, value_rs=50.0, margin_pct=0.2),
    ]
    mantidos, flags, alert = apply_cash_constraint(
        candidatos, budget_rs=1000.0, category_floor_fraction=0.0
    )
    assert mantidos == {"A": 10.0, "B": 5.0}
    assert flags == ()
    assert alert is None


def test_apply_cash_constraint_corta_do_fim_por_margem_nao_proporcionalmente() -> None:
    # orçamento cabe só o de maior margem (A); B e C ficam de fora, mesmo
    # que C sozinho coubesse no espaço que sobrou -- "corte do fim", não
    # encaixe guloso.
    candidatos = [
        CashConstraintCandidate("A", category="CAT", quantity=10.0, value_rs=800.0, margin_pct=0.5),
        CashConstraintCandidate("B", category="CAT", quantity=5.0, value_rs=300.0, margin_pct=0.3),
        CashConstraintCandidate("C", category="CAT", quantity=1.0, value_rs=10.0, margin_pct=0.1),
    ]
    mantidos, flags, alert = apply_cash_constraint(
        candidatos, budget_rs=850.0, category_floor_fraction=0.0
    )
    assert mantidos == {"A": 10.0, "B": 0.0, "C": 0.0}
    motivos = {f.item_id: f for f in flags}
    assert set(motivos) == {"B", "C"}
    assert motivos["B"].reason == GuardrailReason.RESTRICAO_DE_CAIXA
    assert motivos["B"].original_quantity == 5.0
    assert motivos["B"].adjusted_quantity == 0.0
    # nenhum item desaparece -- todo candidato aparece em mantidos OU em flags
    assert set(mantidos) == {"A", "B", "C"}
    assert alert is None


def test_apply_cash_constraint_desempata_por_item_id_em_margem_igual() -> None:
    candidatos = [
        CashConstraintCandidate("Z", category="CAT", quantity=1.0, value_rs=600.0, margin_pct=0.4),
        CashConstraintCandidate("A", category="CAT", quantity=1.0, value_rs=600.0, margin_pct=0.4),
    ]
    mantidos, flags, _alert = apply_cash_constraint(
        candidatos, budget_rs=600.0, category_floor_fraction=0.0
    )
    # empate em margem -- item_id ascendente vence (A antes de Z)
    assert mantidos == {"A": 1.0, "Z": 0.0}
    assert flags[0].item_id == "Z"


def test_apply_cash_constraint_sem_orcamento_zero_corta_tudo() -> None:
    candidatos = [
        CashConstraintCandidate("A", category="CAT", quantity=1.0, value_rs=1.0, margin_pct=0.5)
    ]
    mantidos, flags, alert = apply_cash_constraint(
        candidatos, budget_rs=0.0, category_floor_fraction=0.0
    )
    assert mantidos == {"A": 0.0}
    assert len(flags) == 1
    assert alert is None


# --------------------------------------------------------------------------
# 4.1 Piso por categoria (Etapa 3.16.4)
# --------------------------------------------------------------------------


def test_apply_cash_constraint_piso_protege_item_de_pior_margem() -> None:
    # MEATS: M1 pior margem (.05, R$200), M2 (.08, R$200), M3 melhor
    # margem (.12, R$100) -- valor da categoria R$500, piso 60% = R$300.
    # Sem piso, o corte do fim (por margem, orçamento curto) cortaria os
    # três piores da lista inteira; com piso, M2 e M3 (os R$300 de melhor
    # margem da própria categoria) ficam garantidos mesmo que a margem
    # deles, sozinha, não bastasse para sobreviver ao corte global.
    candidatos = [
        CashConstraintCandidate(
            "M1", category="MEATS", quantity=2.0, value_rs=200.0, margin_pct=0.05
        ),
        CashConstraintCandidate(
            "M2", category="MEATS", quantity=2.0, value_rs=200.0, margin_pct=0.08
        ),
        CashConstraintCandidate(
            "M3", category="MEATS", quantity=1.0, value_rs=100.0, margin_pct=0.12
        ),
        CashConstraintCandidate(
            "B1", category="BEVERAGES", quantity=3.0, value_rs=300.0, margin_pct=0.90
        ),
        CashConstraintCandidate(
            "B2", category="BEVERAGES", quantity=3.0, value_rs=300.0, margin_pct=0.85
        ),
        CashConstraintCandidate(
            "B3", category="BEVERAGES", quantity=3.0, value_rs=300.0, margin_pct=0.80
        ),
    ]
    mantidos, flags, alert = apply_cash_constraint(
        candidatos, budget_rs=950.0, category_floor_fraction=0.6
    )
    assert alert is None
    # sem piso, M2 e M3 perderiam para B1/B2/B3 no corte por margem global
    # -- com piso, sobrevivem inteiros.
    assert mantidos["M2"] == 2.0
    assert mantidos["M3"] == 1.0
    motivos = {f.item_id: f for f in flags}
    assert "protegido pelo piso de categoria" in motivos["M2"].detail
    assert "protegido pelo piso de categoria" in motivos["M3"].detail
    assert motivos["M2"].adjusted_quantity == 2.0  # protegido preserva a quantidade
    # M1 é o pior item da própria categoria -- fica de fora do piso
    # (é o "excedente" de MEATS) e compete pelo que sobra do orçamento.
    assert "M1" not in motivos or motivos["M1"].reason == GuardrailReason.RESTRICAO_DE_CAIXA


def test_apply_cash_constraint_piso_nao_gera_flag_quando_merito_proprio_basta() -> None:
    # Orçamento folgado -- nenhum item precisa do piso pra sobreviver.
    # Nenhum flag de "protegido" deve ser emitido: sobreviver por mérito
    # próprio não é o mesmo que ser protegido pelo piso.
    candidatos = [
        CashConstraintCandidate("A", category="CAT", quantity=1.0, value_rs=100.0, margin_pct=0.5),
        CashConstraintCandidate("B", category="CAT", quantity=1.0, value_rs=100.0, margin_pct=0.4),
    ]
    mantidos, flags, alert = apply_cash_constraint(
        candidatos, budget_rs=1000.0, category_floor_fraction=0.6
    )
    assert mantidos == {"A": 100.0 / 100.0, "B": 100.0 / 100.0}  # ambos mantidos por inteiro
    assert flags == ()
    assert alert is None


def test_apply_cash_constraint_piso_estoura_orcamento_gera_alerta() -> None:
    # Duas categorias de uma unidade cada -- item único é sempre
    # integralmente protegido (não dá para proteger "60% de um item"), e
    # a soma dos dois pisos (R$600 + R$500 = R$1100) já excede o
    # orçamento (R$800): nenhuma combinação de cortes no excedente
    # resolveria isso -- é o caso de escassez, não o caso normal.
    candidatos = [
        CashConstraintCandidate(
            "A", category="CAT-A", quantity=1.0, value_rs=600.0, margin_pct=0.20
        ),
        CashConstraintCandidate(
            "B", category="CAT-B", quantity=1.0, value_rs=500.0, margin_pct=0.10
        ),
    ]
    mantidos, flags, alert = apply_cash_constraint(
        candidatos, budget_rs=800.0, category_floor_fraction=0.6
    )
    assert alert is not None
    assert isinstance(alert, CategoryFloorAlert)
    assert alert.total_floor_rs == 1100.0
    assert alert.budget_rs == 800.0
    assert alert.shortfall_rs == 300.0
    # CAT-A tem margem maior -- é concedida inteira; CAT-B fica sem nada.
    assert mantidos["A"] == 1.0
    assert mantidos["B"] == 0.0
    motivos = {f.item_id: f for f in flags}
    assert "orçamento não cobre nem o piso desta categoria" in motivos["B"].detail


def test_apply_cash_constraint_headroom_compete_entre_categorias() -> None:
    # Combinação MEATS+BEVERAGES do exemplo acima, mas com orçamento tão
    # curto que nem o excedente de BEVERAGES (a melhor margem de todas)
    # cabe depois de reservar os pisos -- o excedente de toda categoria
    # compete junto, e quem perde é sempre o de pior margem do excedente
    # combinado, não do excedente da própria categoria.
    candidatos = [
        CashConstraintCandidate(
            "M1", category="MEATS", quantity=2.0, value_rs=200.0, margin_pct=0.05
        ),
        CashConstraintCandidate(
            "M2", category="MEATS", quantity=2.0, value_rs=200.0, margin_pct=0.08
        ),
        CashConstraintCandidate(
            "M3", category="MEATS", quantity=1.0, value_rs=100.0, margin_pct=0.12
        ),
        CashConstraintCandidate(
            "B1", category="BEVERAGES", quantity=3.0, value_rs=300.0, margin_pct=0.90
        ),
        CashConstraintCandidate(
            "B2", category="BEVERAGES", quantity=3.0, value_rs=300.0, margin_pct=0.85
        ),
        CashConstraintCandidate(
            "B3", category="BEVERAGES", quantity=3.0, value_rs=300.0, margin_pct=0.80
        ),
    ]
    # protegido: MEATS (M2+M3=300) + BEVERAGES (B1+B2=600) = 900 <= 950 --
    # ainda é o caso "cabe", com só R$50 de excedente pra M1 (R$200) e B3
    # (R$300) disputarem -- nenhum dos dois cabe inteiro.
    mantidos, flags, alert = apply_cash_constraint(
        candidatos, budget_rs=950.0, category_floor_fraction=0.6
    )
    assert alert is None
    assert mantidos["M1"] == 0.0
    assert mantidos["B3"] == 0.0
    motivos = {f.item_id: f for f in flags}
    assert motivos["M1"].reason == GuardrailReason.RESTRICAO_DE_CAIXA
    assert "reduzido por restrição de caixa" in motivos["M1"].detail
    assert "reduzido por restrição de caixa" in motivos["B3"].detail


# --------------------------------------------------------------------------
# Regras não implementadas -- declaradas, não escondidas
# --------------------------------------------------------------------------


def test_not_implemented_guardrails_declara_as_duas_regras_restantes() -> None:
    assert len(NOT_IMPLEMENTED_GUARDRAILS) == 2
    texto = " ".join(NOT_IMPLEMENTED_GUARDRAILS)
    assert "promocao_prevista" in texto
    assert "item_ancora" in texto
