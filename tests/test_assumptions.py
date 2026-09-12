"""Testes de `motor.assumptions` (Sprint 16.5, Etapa 3.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from motor.assumptions import AssumptionOrigin, build_assumptions_registry
from motor.config import load_params

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"


def test_build_assumptions_registry_cobre_os_oito_itens_exigidos() -> None:
    params = load_params(PARAMS_PATH)
    registry = build_assumptions_registry(params)

    sa = params.supplier_assumptions
    assert registry.lead_time_days.valor == sa.default_lead_time_days
    assert registry.review_period_days.valor == sa.default_review_period_days
    assert registry.min_order_value.valor == params.supplier_assumptions.default_min_order_value
    assert registry.min_order_units.valor == params.supplier_assumptions.default_min_order_units
    assert registry.pack_multiple.valor == params.supplier_assumptions.default_pack_multiple
    assert set(registry.category_margin_pct) == set(params.economics.category_margin_pct)
    assert registry.capital_cost_annual.valor == params.economics.capital_cost_annual
    assert registry.default_alpha.valor == params.economics.default_alpha
    assert registry.category_alpha.valor == dict(params.economics.category_alpha)
    assert "avg_daily_demand" in str(registry.estoque_inicial.valor)


def test_todas_as_premissas_do_repositorio_sao_arbitradas_nenhuma_medida_do_dataset() -> None:
    """Achado da Etapa 3.2: nenhuma das 8 premissas exigidas tem contraparte
    no dado bruto (Favorita não tem fornecedor/prazo/custo/preço) -- então
    nenhuma delas pode ser DEFAULT_DATASET hoje. GROCERY I/II em
    category_margin_pct são MEDIDO (documento de negócio); o resto é
    ARBITRADO."""
    params = load_params(PARAMS_PATH)
    registry = build_assumptions_registry(params)

    escalares = [
        registry.lead_time_days,
        registry.review_period_days,
        registry.min_order_value,
        registry.min_order_units,
        registry.pack_multiple,
        registry.capital_cost_annual,
        registry.estoque_inicial,
        registry.default_alpha,
        registry.category_alpha,
    ]
    assert all(a.origem == AssumptionOrigin.ARBITRADO for a in escalares)
    assert all(a.origem != AssumptionOrigin.DEFAULT_DATASET for a in escalares)

    for categoria, assumption in registry.category_margin_pct.items():
        if categoria in ("GROCERY I", "GROCERY II"):
            assert assumption.origem == AssumptionOrigin.MEDIDO
            assert assumption.fonte is not None
        else:
            assert assumption.origem == AssumptionOrigin.ARBITRADO
            assert assumption.fonte is None


def test_assumption_medida_sem_fonte_e_erro_de_dado_nao_e_validado_aqui() -> None:
    """`fonte=None` é o esperado para ARBITRADO (chute não tem fonte por
    definição) -- só documentando o contrato, não uma regra de validação
    (Assumption não impede origem=MEDIDO com fonte=None; a disciplina de
    sempre citar fonte quando MEDIDO é de quem escreve build_assumptions_registry,
    verificada no teste acima célula a célula, não pelo tipo)."""
    params = load_params(PARAMS_PATH)
    registry = build_assumptions_registry(params)
    with pytest.raises(ValidationError):
        registry.lead_time_days.valor = 999  # type: ignore[misc]  # frozen
