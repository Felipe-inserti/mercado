"""Testes de `motor.experiments.shared` (premissas compartilhadas, Sprint 7)."""

from datetime import date, timedelta

import polars as pl

from motor.experiments.shared import build_simulator_for_pair, initial_stock_units
from tests.fakes import ConstantForecaster, OrderUpToPolicy

D0 = date(2026, 1, 1)


def _demand_constante(*, dias: int, valor: float, start: date = D0) -> pl.DataFrame:
    dates = [start + timedelta(days=i) for i in range(dias)]
    return pl.DataFrame({"date": dates, "units_sold": [valor] * dias})


# -- initial_stock_units -------------------------------------------------


def test_initial_stock_units_e_a_demanda_media_do_warmup_vezes_lead_time_mais_review_period() -> (
    None
):
    demand = _demand_constante(dias=20, valor=10.0)
    resultado = initial_stock_units(
        demand, warmup_days=5, lead_time_days=3, review_period_days=7, start=D0
    )
    # média(10) x (3+7) = 100
    assert resultado == 100.0


def test_initial_stock_units_usa_so_os_dias_do_warmup_nao_o_historico_inteiro() -> None:
    # 5 dias a 10 unidades, depois um salto pra 1000 -- se o cálculo vazasse
    # pro resto da série, o resultado explodiria.
    dates = [D0 + timedelta(days=i) for i in range(20)]
    units = [10.0] * 5 + [1000.0] * 15
    demand = pl.DataFrame({"date": dates, "units_sold": units})

    resultado = initial_stock_units(
        demand, warmup_days=5, lead_time_days=3, review_period_days=7, start=D0
    )
    assert resultado == 100.0  # só os 5 primeiros dias (10.0) entram na média


def test_initial_stock_units_sem_dado_no_warmup_devolve_zero() -> None:
    demand = _demand_constante(dias=5, valor=10.0, start=D0 + timedelta(days=100))
    resultado = initial_stock_units(
        demand, warmup_days=5, lead_time_days=3, review_period_days=7, start=D0
    )
    assert resultado == 0.0


# -- build_simulator_for_pair ---------------------------------------------


def test_build_simulator_for_pair_comeca_com_o_estoque_inicial_calculado() -> None:
    demand = _demand_constante(dias=30, valor=10.0)
    simulator = build_simulator_for_pair(
        demand=demand,
        forecaster=ConstantForecaster(10.0),
        policy=OrderUpToPolicy(target_level=1_000_000.0),  # nunca dispara ruptura
        lead_time_days=3,
        review_period_days=7,
        start=D0,
        warmup_days=5,
        quantiles=[0.5],
    )
    eventos = simulator.run(D0, D0)
    # média(10) x (3+7) = 100, presente já no primeiro dia (antes de qualquer pedido novo chegar)
    assert eventos[0].on_hand_start == 100.0


def test_build_simulator_for_pair_horizonte_e_lead_time_mais_review_period() -> None:
    class HorizonteEspiao:
        def __init__(self) -> None:
            self.horizontes_vistos: list[int] = []

        def fit(self, history: pl.DataFrame, as_of: date) -> None:
            del history, as_of

        def predict_quantiles(
            self, as_of: date, horizon: int, quantiles: list[float]
        ) -> pl.DataFrame:
            del as_of
            self.horizontes_vistos.append(horizon)
            return pl.DataFrame({"quantile": quantiles, "value": [0.0] * len(quantiles)})

    demand = _demand_constante(dias=15, valor=10.0)
    espiao = HorizonteEspiao()
    simulator = build_simulator_for_pair(
        demand=demand,
        forecaster=espiao,
        policy=OrderUpToPolicy(target_level=0.0),
        lead_time_days=3,
        review_period_days=7,
        start=D0,
        warmup_days=0,
        quantiles=[0.5],
    )
    simulator.run(D0, D0)  # D0 é dia de revisão (review_every_n_days com reference=D0)

    assert espiao.horizontes_vistos == [10]  # lead_time_days(3) + review_period_days(7)


def test_build_simulator_for_pair_revisa_a_cada_review_period_days() -> None:
    demand = _demand_constante(dias=15, valor=10.0)
    simulator = build_simulator_for_pair(
        demand=demand,
        forecaster=ConstantForecaster(10.0),
        policy=OrderUpToPolicy(target_level=100.0),
        lead_time_days=3,
        review_period_days=7,
        start=D0,
        warmup_days=0,
        quantiles=[0.5],
    )
    eventos = simulator.run(D0, D0 + timedelta(days=13))
    dias_com_revisao = [e.day for e in eventos if e.order_placed is not None]
    assert dias_com_revisao == [D0, D0 + timedelta(days=7)]


def test_build_simulator_for_pair_nao_perece_nenhum_item() -> None:
    # shelf_life_from_arrival_days=None para todo item -- premissa declarada
    # da Sprint 7 (ver docstring de motor.experiments.shared).
    demand = _demand_constante(dias=40, valor=10.0)
    simulator = build_simulator_for_pair(
        demand=demand,
        forecaster=ConstantForecaster(10.0),
        policy=OrderUpToPolicy(target_level=100.0),
        lead_time_days=3,
        review_period_days=7,
        start=D0,
        warmup_days=0,
        quantiles=[0.5],
    )
    eventos = simulator.run(D0, D0 + timedelta(days=39))
    assert all(e.expired == 0.0 for e in eventos)
