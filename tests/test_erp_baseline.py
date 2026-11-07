"""Testes de `motor.policy.erp_baseline.ErpBaselinePolicy` (Sprint 7)."""

from datetime import date, timedelta

import polars as pl
import pytest

from motor.policy.base import DecisionContext
from motor.policy.erp_baseline import (
    ErpBaselinePolicy,
    daily_average_from_history,
    moving_average_daily,
)

D0 = date(2026, 1, 1)


def _ctx(*, on_hand: float, in_transit: float, median_value: float) -> DecisionContext:
    return DecisionContext(
        as_of=D0,
        on_hand=on_hand,
        in_transit=in_transit,
        forecast=pl.DataFrame({"quantile": [0.5], "value": [median_value]}),
    )


# mu_daily = 10 unidades/dia (a política recebe a média diária direto; o
# forecast do contexto, qualquer que seja, não entra no pedido)
_MU_DAILY = 10.0
_MEDIAN_VALUE = 100.0  # valor qualquer no forecast: não deve influenciar nada
_MOVING_AVERAGE_WEEKS = 4  # 28 dias
_FACTOR = 1.2
# target = mu_daily x (moving_average_weeks x 7) x factor = 10 x 28 x 1.2 = 336.0
_TARGET = 336.0


def _policy(*, min_order_units: float = 5.0) -> ErpBaselinePolicy:
    return ErpBaselinePolicy(
        daily_average=lambda _as_of: _MU_DAILY,
        moving_average_weeks=_MOVING_AVERAGE_WEEKS,
        factor=_FACTOR,
        min_order_units=min_order_units,
    )


# -- construtor ----------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"moving_average_weeks": 0}, "moving_average_weeks"),
        ({"factor": -0.1}, "factor"),
        ({"min_order_units": -1.0}, "min_order_units"),
    ],
)
def test_construtor_rejeita_parametro_invalido(kwargs: dict[str, float], match: str) -> None:
    base = {
        "daily_average": lambda _as_of: _MU_DAILY,
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


# -- independência do forecast (o ponto central da Sprint 24, 24.5) --------


def test_pedido_nao_muda_quando_o_forecaster_e_trocado() -> None:
    """O pedido vem da média diária, não do forecast: contextos com forecasts
    completamente diferentes (inclusive sem quantil 0,5) pedem a mesma coisa."""
    policy = _policy(min_order_units=0.0)
    posicao = {"on_hand": 20.0, "in_transit": 5.0}
    ctx_naive = _ctx(**posicao, median_value=100.0)
    ctx_outro = DecisionContext(
        as_of=D0,
        **posicao,
        forecast=pl.DataFrame({"quantile": [0.8, 0.9], "value": [999.0, 5000.0]}),
    )

    assert policy.order(ctx_naive) == pytest.approx(_TARGET - 25.0)
    assert policy.order(ctx_outro) == pytest.approx(policy.order(ctx_naive))


def test_daily_average_recebe_a_data_da_decisao() -> None:
    chamadas: list[date] = []

    def daily_average(as_of: date) -> float:
        chamadas.append(as_of)
        return _MU_DAILY

    policy = ErpBaselinePolicy(
        daily_average=daily_average,
        moving_average_weeks=_MOVING_AVERAGE_WEEKS,
        factor=_FACTOR,
        min_order_units=0.0,
    )
    policy.order(_ctx(on_hand=0.0, in_transit=0.0, median_value=1.0))
    assert chamadas == [D0]


# -- moving_average_daily e daily_average_from_history ----------------------


def _demand(units: list[float], start: date = date(2026, 1, 1)) -> pl.DataFrame:
    return pl.DataFrame(
        {"date": [start + timedelta(days=i) for i in range(len(units))], "units_sold": units}
    )


def test_moving_average_daily_bate_com_calculo_a_mao() -> None:
    # 14 dias: 7 de 10 e 7 de 20. as_of = dia 14 (2026-01-15), janela de 1 semana =
    # dias 7..13 = todos 20 -> 20; janela de 2 semanas = média de 10 e 20 = 15.
    history = _demand([10.0] * 7 + [20.0] * 7)
    as_of = date(2026, 1, 15)
    assert moving_average_daily(history, as_of, 1) == pytest.approx(20.0)
    assert moving_average_daily(history, as_of, 2) == pytest.approx(15.0)


def test_moving_average_daily_ignora_dia_ausente_e_historico_vazio() -> None:
    history = _demand([10.0] * 14).filter(pl.col("date") != date(2026, 1, 14))
    assert moving_average_daily(history, date(2026, 1, 15), 2) == pytest.approx(10.0)
    assert moving_average_daily(history.clear(), date(2026, 1, 15), 2) == 0.0


def test_moving_average_daily_nao_olha_para_data_maior_ou_igual_a_as_of() -> None:
    history = _demand([10.0] * 14 + [1000.0] * 3)  # dias 14..16 são futuro de 2026-01-15
    assert moving_average_daily(history, date(2026, 1, 15), 2) == pytest.approx(10.0)


def test_moving_average_daily_rejeita_semanas_nao_positivas() -> None:
    with pytest.raises(ValueError, match="weeks"):
        moving_average_daily(_demand([1.0]), date(2026, 1, 15), 0)


def test_daily_average_from_history_usa_historico_censurado_e_pedido_bate_a_mao() -> None:
    # 14 dias de 10, mas o dia 13 (2026-01-14) vendeu 0 e foi marcado como ruptura.
    units = [10.0] * 13 + [0.0]
    demand = _demand(units)
    flags = pl.DataFrame(
        {"date": [date(2026, 1, 14)], "is_censored": [True]},
    )
    as_of = date(2026, 1, 15)

    bruto = daily_average_from_history(demand, 2)(as_of)
    censurado = daily_average_from_history(demand, 2, flags)(as_of)
    assert bruto == pytest.approx(130.0 / 14)
    assert censurado == pytest.approx(10.0)

    # pedido à mão: mu=10, 2 semanas (14 dias), factor 1,2 -> target 168; posição 18 -> 150.
    policy = ErpBaselinePolicy(
        daily_average=daily_average_from_history(demand, 2, flags),
        moving_average_weeks=2,
        factor=1.2,
        min_order_units=0.0,
    )
    ctx = DecisionContext(
        as_of=as_of,
        on_hand=10.0,
        in_transit=8.0,
        forecast=pl.DataFrame({"quantile": [0.5], "value": [0.0]}),
    )
    assert policy.order(ctx) == pytest.approx(168.0 - 18.0)
