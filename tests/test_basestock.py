"""Testes de `motor.policy.basestock.BasestockPolicy` (Sprint 12).

`BasestockPolicy` não tem lógica própria de decisão -- é o adaptador entre
`DecisionContext` (grão do simulador) e `compute_order_quantity` (lógica pura
da Sprint 11, já testada em `tests/test_target_level.py`). Os testes aqui
confirmam a CONVERSÃO (posição, tabela de quantis -> `WindowQuantileForecast`),
não redundam com os testes de `compute_order_quantity` em si.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from motor.policy.base import DecisionContext
from motor.policy.basestock import BasestockPolicy

_AS_OF = date(2024, 1, 1)


def _ctx(*, on_hand: float, in_transit: float, forecast: pl.DataFrame) -> DecisionContext:
    return DecisionContext(as_of=_AS_OF, on_hand=on_hand, in_transit=in_transit, forecast=forecast)


def test_order_delega_a_compute_order_quantity_com_a_posicao_somada() -> None:
    forecast = pl.DataFrame({"quantile": [0.5, 0.9], "value": [50.0, 100.0]})
    policy = BasestockPolicy(alpha=0.9, expected_window_days=10)

    quantidade = policy.order(_ctx(on_hand=10.0, in_transit=20.0, forecast=forecast))

    # target_level = quantil 0.9 = 100.0; posição = 10+20 = 30 -> pedido = 70
    assert quantidade == pytest.approx(70.0)


def test_order_devolve_zero_quando_posicao_ja_cobre_o_alvo() -> None:
    forecast = pl.DataFrame({"quantile": [0.9], "value": [100.0]})
    policy = BasestockPolicy(alpha=0.9, expected_window_days=10)

    quantidade = policy.order(_ctx(on_hand=80.0, in_transit=40.0, forecast=forecast))

    assert quantidade == pytest.approx(0.0)


def test_order_com_alpha_ausente_no_forecast_levanta_erro_claro() -> None:
    """Propaga o erro de `compute_order_quantity` (Sprint 11) sem mascarar --
    `BasestockPolicy` não interpola nem escolhe um quantil vizinho."""
    forecast = pl.DataFrame({"quantile": [0.5, 0.8], "value": [50.0, 80.0]})
    policy = BasestockPolicy(alpha=0.9, expected_window_days=10)

    with pytest.raises(ValueError, match=r"alpha=0\.9"):
        policy.order(_ctx(on_hand=0.0, in_transit=0.0, forecast=forecast))


def test_order_usa_expected_window_days_tanto_no_forecast_quanto_na_conferencia() -> None:
    """Documenta a limitação conhecida (ver docstring de `BasestockPolicy`):
    `ctx.forecast` não carrega metadado de janela, então `order()` sempre
    constrói `WindowQuantileForecast.window_days` == `expected_window_days`
    -- a regra 1 de `compute_order_quantity` nunca dispara através deste
    adaptador, para qualquer `expected_window_days` positivo. Roda sem
    estourar para confirmar isso, em vez de deixar como intenção não testada.
    """
    forecast = pl.DataFrame({"quantile": [0.9], "value": [100.0]})
    policy = BasestockPolicy(alpha=0.9, expected_window_days=11)

    quantidade = policy.order(_ctx(on_hand=0.0, in_transit=0.0, forecast=forecast))
    assert quantidade == pytest.approx(100.0)
