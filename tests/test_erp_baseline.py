"""Testes de `motor.policy.erp_baseline.ErpBaselinePolicy` (Sprint 7)."""

from datetime import date

import polars as pl
import pytest

from motor.policy.base import DecisionContext
from motor.policy.erp_baseline import ErpBaselinePolicy

D0 = date(2026, 1, 1)


def _ctx(*, on_hand: float, in_transit: float, median_value: float) -> DecisionContext:
    return DecisionContext(
        as_of=D0,
        on_hand=on_hand,
        in_transit=in_transit,
        forecast=pl.DataFrame({"quantile": [0.5], "value": [median_value]}),
    )


# mu_daily = 10 unidades/dia; horizon_days=10 -> mediana do forecast = 100
_HORIZON_DAYS = 10
_MU_DAILY = 10.0
_MEDIAN_VALUE = _MU_DAILY * _HORIZON_DAYS  # 100.0
_MOVING_AVERAGE_WEEKS = 4  # 28 dias
_FACTOR = 1.2
# target = mu_daily x (moving_average_weeks x 7) x factor = 10 x 28 x 1.2 = 336.0
_TARGET = 336.0


def _policy(*, min_order_units: float = 5.0) -> ErpBaselinePolicy:
    return ErpBaselinePolicy(
        horizon_days=_HORIZON_DAYS,
        moving_average_weeks=_MOVING_AVERAGE_WEEKS,
        factor=_FACTOR,
        min_order_units=min_order_units,
    )


# -- construtor ----------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"horizon_days": 0}, "horizon_days"),
        ({"horizon_days": -1}, "horizon_days"),
        ({"moving_average_weeks": 0}, "moving_average_weeks"),
        ({"factor": -0.1}, "factor"),
        ({"min_order_units": -1.0}, "min_order_units"),
    ],
)
def test_construtor_rejeita_parametro_invalido(kwargs: dict[str, float], match: str) -> None:
    base = {
        "horizon_days": _HORIZON_DAYS,
        "moving_average_weeks": _MOVING_AVERAGE_WEEKS,
        "factor": _FACTOR,
        "min_order_units": 5.0,
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        ErpBaselinePolicy(**base)  # type: ignore[arg-type]


# -- desconto de posição (on_hand + in_transit) ---------------------------


def test_order_desconta_on_hand_e_in_transit_da_posicao() -> None:
    policy = _policy(min_order_units=5.0)
    ctx = _ctx(on_hand=100.0, in_transit=50.0, median_value=_MEDIAN_VALUE)

    pedido = policy.order(ctx)

    # target(336) - posicao(150) = 186
    assert pedido == pytest.approx(186.0)


def test_order_com_apenas_in_transit_ja_desconta_posicao_inteira() -> None:
    """Ignorar `in_transit` é o bug clássico (CLAUDE.md, seção 5) -- este teste
    falha se `order` esquecer de somar `in_transit` à posição."""
    policy = _policy(min_order_units=0.0)
    com_pipeline = policy.order(_ctx(on_hand=0.0, in_transit=_TARGET, median_value=_MEDIAN_VALUE))
    sem_pipeline = policy.order(_ctx(on_hand=0.0, in_transit=0.0, median_value=_MEDIAN_VALUE))

    assert com_pipeline == pytest.approx(0.0)  # posição já cobre o alvo -- não pede de novo
    assert sem_pipeline == pytest.approx(_TARGET)


# -- piso em min_order_units ----------------------------------------------


def test_pedido_bruto_positivo_e_menor_que_o_minimo_sobe_ate_o_minimo() -> None:
    policy = _policy(min_order_units=10.0)
    # posicao = target - 3 -> pedido bruto = 3, menor que o piso de 10
    ctx = _ctx(on_hand=_TARGET - 3.0, in_transit=0.0, median_value=_MEDIAN_VALUE)

    assert policy.order(ctx) == pytest.approx(10.0)


def test_pedido_bruto_maior_que_o_minimo_nao_e_alterado() -> None:
    policy = _policy(min_order_units=5.0)
    ctx = _ctx(on_hand=_TARGET - 186.0, in_transit=0.0, median_value=_MEDIAN_VALUE)

    assert policy.order(ctx) == pytest.approx(186.0)


def test_pedido_bruto_nao_positivo_nunca_sobe_para_o_minimo() -> None:
    """O piso só se aplica quando HÁ pedido -- nunca é gatilho pra pedir sem
    necessidade (posição já >= alvo)."""
    policy = _policy(min_order_units=999.0)
    ctx = _ctx(on_hand=_TARGET, in_transit=0.0, median_value=_MEDIAN_VALUE)  # posição == alvo

    assert policy.order(ctx) == pytest.approx(0.0)

    ctx_acima = _ctx(on_hand=_TARGET + 50.0, in_transit=0.0, median_value=_MEDIAN_VALUE)
    assert policy.order(ctx_acima) == pytest.approx(0.0)


# -- independência de horizon_days (o ponto central da sprint) ------------


def test_pedido_independe_de_horizon_days_dado_o_mesmo_mu_daily() -> None:
    """Duas políticas com `horizon_days` diferentes, mas cuja mediana do
    forecast representa o MESMO `mu_daily`, devem pedir exatamente o mesmo --
    a política não deriva nada da janela de risco (lead_time + review_period).
    """
    posicao = {"on_hand": 20.0, "in_transit": 5.0}

    policy_10d = ErpBaselinePolicy(
        horizon_days=10,
        moving_average_weeks=_MOVING_AVERAGE_WEEKS,
        factor=_FACTOR,
        min_order_units=0.0,
    )
    policy_20d = ErpBaselinePolicy(
        horizon_days=20,
        moving_average_weeks=_MOVING_AVERAGE_WEEKS,
        factor=_FACTOR,
        min_order_units=0.0,
    )

    pedido_10d = policy_10d.order(_ctx(**posicao, median_value=_MU_DAILY * 10))
    pedido_20d = policy_20d.order(_ctx(**posicao, median_value=_MU_DAILY * 20))

    assert pedido_10d == pytest.approx(pedido_20d)
    assert pedido_10d == pytest.approx(_TARGET - 25.0)


# -- forecast sem mediana ---------------------------------------------------


def test_forecast_sem_quantile_0_5_levanta_value_error() -> None:
    policy = _policy()
    ctx = DecisionContext(
        as_of=D0,
        on_hand=0.0,
        in_transit=0.0,
        forecast=pl.DataFrame({"quantile": [0.8, 0.9], "value": [120.0, 140.0]}),
    )
    with pytest.raises(ValueError, match=r"quantile==0\.5"):
        policy.order(ctx)
