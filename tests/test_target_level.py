"""Testes de `motor.policy.target_level` (Sprint 11).

Lógica pura, sem estatística real -- toda previsão é injetada
(`WindowQuantileForecast` construído à mão). Nenhum teste aqui compõe com
`motor.policy.supplier.apply_supplier_constraints` (Sprint 12, fecha o braço
2) nem usa previsão real (Sprint 4/7).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from motor.inventory import InventoryState
from motor.policy.target_level import (
    TargetLevelDecision,
    WindowQuantileForecast,
    compute_order_quantity,
)

# --------------------------------------------------------------------------
# 1. Quantil exato de distribuição analiticamente conhecida
# --------------------------------------------------------------------------


def test_target_level_e_exatamente_o_quantil_da_distribuicao_conhecida() -> None:
    """Demanda acumulada na janela segue Uniform(50, 250) -- distribuição
    analítica conhecida, como no teste de estado estacionário da Sprint 6.

    O quantil alpha de uma Uniform(a, b) é `a + alpha * (b - a)` (CDF
    linear, F(x) = (x-a)/(b-a), inversa direta). Para alpha=0.90:
    50 + 0.90 * 200 = 230.0 -- valor derivado, não escolhido a dedo.
    """
    alpha = 0.90
    target_level_esperado = 50.0 + alpha * 200.0  # = 230.0
    forecast = WindowQuantileForecast(window_days=10, quantiles={alpha: target_level_esperado})

    decision = compute_order_quantity(forecast, position=0.0, alpha=alpha, expected_window_days=10)

    assert decision.target_level == pytest.approx(230.0)
    assert decision.raw_quantity == pytest.approx(230.0)
    assert decision.position_used == pytest.approx(0.0)
    assert decision.surplus == pytest.approx(0.0)
    assert decision.alpha == alpha


# --------------------------------------------------------------------------
# 2-3. Em trânsito dentro e fora da janela -- fixam a decisão documentada
# --------------------------------------------------------------------------
#
# `compute_order_quantity` recebe `position` já pronta de
# `InventoryState.posicao()` (regra 2 do enunciado) -- por isso os dois
# testes abaixo usam `InventoryState` de verdade, não um float construído à
# mão, para deixar inequívoco que `posicao()` não sabe nem deveria saber a
# data de chegada de cada lote em trânsito. É essa ignorância estrutural que
# implementa a decisão de revisão periódica (order-up-to sobre posição
# total): pedido em trânsito com chegada POSTERIOR ao fim da janela de risco
# ainda conta integralmente na posição -- excluí-lo geraria pedido duplicado
# na revisão seguinte, porque aquele lote de qualquer forma vai chegar e
# reduzir a necessidade futura. Os dois testes usam a mesma quantidade em
# trânsito (40.0) e a mesma previsão (target_level=100.0) só variando a data
# de chegada, e esperam o MESMO resultado -- é essa igualdade que fixa a
# decisão.

_AS_OF = date(2024, 1, 1)
_WINDOW_DAYS = 10


def test_em_transito_chegando_dentro_da_janela_reduz_o_pedido_pela_quantidade() -> None:
    """on_hand=0, in_transit=40 chegando dentro da janela (as_of + 5 dias,
    window_days=10): o pedido cai em 40 -- target_level(100) - position(40)
    = 60."""
    estado = InventoryState(data_inicial=_AS_OF)
    estado.agendar_pedido(quantidade=40.0, data_chegada=_AS_OF + timedelta(days=5), validade=None)
    position = estado.posicao()
    assert position == pytest.approx(40.0)

    forecast = WindowQuantileForecast(window_days=_WINDOW_DAYS, quantiles={0.90: 100.0})
    decision = compute_order_quantity(
        forecast, position, alpha=0.90, expected_window_days=_WINDOW_DAYS
    )

    assert decision.raw_quantity == pytest.approx(60.0)  # 100 - 40
    assert decision.surplus == pytest.approx(0.0)


def test_em_transito_chegando_fora_da_janela_ainda_conta_na_posicao() -> None:
    """Mesmo cenário do teste acima, mas o pedido em trânsito chega bem
    DEPOIS do fim da janela de risco (as_of + 30 dias, window_days=10). O
    resultado é IDÊNTICO ao caso "dentro da janela": `compute_order_quantity`
    não distingue os dois casos, porque não recebe (nem deveria receber)
    data de chegada -- só `position`, já agregada. Ver docstring do módulo
    para o racional completo da decisão.
    """
    estado = InventoryState(data_inicial=_AS_OF)
    estado.agendar_pedido(quantidade=40.0, data_chegada=_AS_OF + timedelta(days=30), validade=None)
    position = estado.posicao()
    assert position == pytest.approx(40.0)

    forecast = WindowQuantileForecast(window_days=_WINDOW_DAYS, quantiles={0.90: 100.0})
    decision = compute_order_quantity(
        forecast, position, alpha=0.90, expected_window_days=_WINDOW_DAYS
    )

    assert decision.raw_quantity == pytest.approx(60.0)  # 100 - 40, igual ao teste anterior
    assert decision.surplus == pytest.approx(0.0)


# --------------------------------------------------------------------------
# 4. Posição acima do alvo -- raw_quantity=0, surplus preservado (não descartado)
# --------------------------------------------------------------------------


def test_posicao_acima_do_alvo_zera_raw_quantity_e_preserva_surplus() -> None:
    forecast = WindowQuantileForecast(window_days=_WINDOW_DAYS, quantiles={0.90: 100.0})

    decision = compute_order_quantity(
        forecast, position=150.0, alpha=0.90, expected_window_days=_WINDOW_DAYS
    )

    assert decision.raw_quantity == pytest.approx(0.0)
    assert decision.surplus == pytest.approx(-50.0)  # 100 - 150 -- sinal negativo preservado
    assert decision.target_level == pytest.approx(100.0)
    assert decision.position_used == pytest.approx(150.0)


# --------------------------------------------------------------------------
# 5. Monotonicidade em alpha
# --------------------------------------------------------------------------


def test_monotonicidade_alpha_maior_nunca_produz_pedido_menor() -> None:
    forecast = WindowQuantileForecast(
        window_days=_WINDOW_DAYS, quantiles={0.70: 80.0, 0.90: 100.0, 0.97: 130.0}
    )
    position = 20.0

    ordens = [
        compute_order_quantity(
            forecast, position, alpha=alpha, expected_window_days=_WINDOW_DAYS
        ).raw_quantity
        for alpha in (0.70, 0.90, 0.97)
    ]

    assert ordens == sorted(ordens)  # não-decrescente em alpha
    assert ordens[0] < ordens[-1]  # e de fato varia, não é um empate degenerado


# --------------------------------------------------------------------------
# 6. Pontas válidas da tabela (0,70 e 0,97) rodam sem estourar
# --------------------------------------------------------------------------


@pytest.mark.parametrize("alpha", [0.70, 0.97])
def test_alpha_nas_pontas_validas_roda_sem_estourar(alpha: float) -> None:
    forecast = WindowQuantileForecast(window_days=_WINDOW_DAYS, quantiles={alpha: 90.0})

    decision = compute_order_quantity(
        forecast, position=0.0, alpha=alpha, expected_window_days=_WINDOW_DAYS
    )

    assert decision.target_level == pytest.approx(90.0)
    assert isinstance(decision, TargetLevelDecision)


# --------------------------------------------------------------------------
# 7. Erros claros: alpha=1.0, alpha=0, janela incompatível
# --------------------------------------------------------------------------


def test_alpha_igual_a_1_e_rejeitado_explicitamente() -> None:
    forecast = WindowQuantileForecast(window_days=_WINDOW_DAYS, quantiles={0.90: 100.0})
    with pytest.raises(ValueError, match=r"alpha=1\.0"):
        compute_order_quantity(forecast, position=0.0, alpha=1.0, expected_window_days=_WINDOW_DAYS)


def test_alpha_igual_a_0_e_rejeitado() -> None:
    forecast = WindowQuantileForecast(window_days=_WINDOW_DAYS, quantiles={0.5: 100.0})
    with pytest.raises(ValueError, match="alpha"):
        compute_order_quantity(forecast, position=0.0, alpha=0.0, expected_window_days=_WINDOW_DAYS)


def test_janela_incompativel_com_o_horizonte_esperado_levanta_erro_claro() -> None:
    forecast = WindowQuantileForecast(window_days=10, quantiles={0.90: 100.0})
    with pytest.raises(ValueError, match="window_days"):
        compute_order_quantity(forecast, position=0.0, alpha=0.90, expected_window_days=11)


def test_alpha_ausente_no_mapeamento_de_quantis_levanta_erro_claro() -> None:
    forecast = WindowQuantileForecast(window_days=_WINDOW_DAYS, quantiles={0.90: 100.0})
    with pytest.raises(ValueError, match=r"alpha=0\.95"):
        compute_order_quantity(
            forecast, position=0.0, alpha=0.95, expected_window_days=_WINDOW_DAYS
        )


# --------------------------------------------------------------------------
# 8. WindowQuantileForecast -- o tipo torna previsão diária/quantis somados
#    estruturalmente difíceis de passar por engano
# --------------------------------------------------------------------------


def test_window_quantile_forecast_rejeita_window_days_nao_positivo() -> None:
    with pytest.raises(ValueError, match="window_days"):
        WindowQuantileForecast(window_days=0, quantiles={0.90: 100.0})


def test_window_quantile_forecast_rejeita_mapeamento_vazio() -> None:
    with pytest.raises(ValueError, match="quantiles"):
        WindowQuantileForecast(window_days=10, quantiles={})


def test_window_quantile_forecast_rejeita_quantil_fora_de_0_1() -> None:
    with pytest.raises(ValueError, match="quantil"):
        WindowQuantileForecast(window_days=10, quantiles={1.5: 100.0})


def test_window_quantile_forecast_rejeita_valores_nao_monotonicos() -> None:
    """Quantis não se somam nem podem ser desordenados: um q90 menor que o
    q70 é, por construção, uma previsão inconsistente -- pega o tipo de erro
    que apareceria se alguém acidentalmente montasse o mapeamento a partir
    de previsões DIÁRIAS não acumuladas."""
    with pytest.raises(ValueError, match="não-decrescent"):
        WindowQuantileForecast(window_days=10, quantiles={0.70: 100.0, 0.90: 80.0})


def test_window_quantile_forecast_quantiles_e_imutavel_apos_construcao() -> None:
    forecast = WindowQuantileForecast(window_days=10, quantiles={0.90: 100.0})
    with pytest.raises(TypeError):
        forecast.quantiles[0.90] = 999.0  # type: ignore[index]
