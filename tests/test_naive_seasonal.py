"""Testes de `motor.forecast.naive_seasonal.NaiveSeasonalForecaster` (Sprint 24, 24.3).

Série de referência: 3 semanas conhecidas, D0 = 2026-01-05 (segunda-feira) até
D20 (domingo). `as_of` = D21 = 2026-01-26 (segunda). Vendas por dia da semana:

    semana 1 (D0..D6):   1  2  3  4  5  6  7
    semana 2 (D7..D13): 10 20 30 40 50 60 70
    semana 3 (D14..D20): 100 200 300 400 500 600 700

Última semana antes de `as_of` = semana 3, soma = 2800.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from motor.forecast.naive_seasonal import NaiveSeasonalForecaster
from motor.inventory import InventoryState
from motor.simulator.engine import Simulator, review_every_n_days
from tests.fakes import OrderUpToPolicy, SpyForecaster

D0 = date(2026, 1, 5)  # segunda-feira
AS_OF = D0 + timedelta(days=21)

_UNITS = [1, 2, 3, 4, 5, 6, 7, 10, 20, 30, 40, 50, 60, 70, 100, 200, 300, 400, 500, 600, 700]


def _history(units: list[int] = _UNITS, skip: set[int] | None = None) -> pl.DataFrame:
    skip = skip or set()
    days = [i for i in range(len(units)) if i not in skip]
    return pl.DataFrame(
        {
            "date": [D0 + timedelta(days=i) for i in days],
            "units_sold": [float(units[i]) for i in days],
        }
    )


def _value(forecaster: NaiveSeasonalForecaster, horizon: int) -> float | None:
    result = forecaster.predict_quantiles(AS_OF, horizon, [0.5])
    assert result.columns == ["quantile", "value"]
    assert result["quantile"].to_list() == [0.5]
    value = result["value"][0]
    assert value is None or isinstance(value, float)
    return value


def test_horizonte_7_soma_a_ultima_semana() -> None:
    # D21..D27 (seg..dom) -> referências D14..D20 = 100+200+300+400+500+600+700 = 2800
    forecaster = NaiveSeasonalForecaster()
    forecaster.fit(_history(), AS_OF)
    assert _value(forecaster, 7) == 2800.0


def test_horizonte_menor_que_7_soma_so_os_dias_pedidos() -> None:
    # D21, D22, D23 (seg, ter, qua) -> D14, D15, D16 = 100 + 200 + 300 = 600
    forecaster = NaiveSeasonalForecaster()
    forecaster.fit(_history(), AS_OF)
    assert _value(forecaster, 3) == 600.0


def test_horizonte_14_reusa_a_ultima_semana_duas_vezes() -> None:
    # D28..D34 também apontam para D14..D20 (e NÃO para D21..D27, que são futuro).
    # Total = 2 x 2800 = 5600. Se usasse d - 7 literal, D28 -> D21 (ausente) -> None.
    forecaster = NaiveSeasonalForecaster()
    forecaster.fit(_history(), AS_OF)
    assert _value(forecaster, 14) == 5600.0


def test_dia_de_referencia_faltando_devolve_none() -> None:
    # Sem D16 (quarta da semana 3): horizonte 7 precisa dele -> None, não 2800 - 300.
    forecaster = NaiveSeasonalForecaster()
    forecaster.fit(_history(skip={16}), AS_OF)
    assert _value(forecaster, 7) is None


def test_dia_faltando_fora_dos_dias_usados_nao_afeta() -> None:
    # Horizonte 3 usa só D14, D15, D16; faltar D19 não importa.
    forecaster = NaiveSeasonalForecaster()
    forecaster.fit(_history(skip={19}), AS_OF)
    assert _value(forecaster, 3) == 600.0


def test_historico_vazio_devolve_none() -> None:
    forecaster = NaiveSeasonalForecaster()
    forecaster.fit(
        pl.DataFrame(
            {"date": [], "units_sold": []}, schema={"date": pl.Date, "units_sold": pl.Float64}
        ),
        AS_OF,
    )
    assert _value(forecaster, 7) is None


@pytest.mark.parametrize("quantiles", [[0.9], [0.5, 0.9]])
def test_quantil_diferente_de_mediana_levanta_erro(quantiles: list[float]) -> None:
    forecaster = NaiveSeasonalForecaster()
    forecaster.fit(_history(), AS_OF)
    with pytest.raises(ValueError, match=r"quantil 0\.5"):
        forecaster.predict_quantiles(AS_OF, 7, quantiles)


def test_fit_com_data_igual_ou_posterior_a_as_of_levanta_assertion_error() -> None:
    forecaster = NaiveSeasonalForecaster()
    with pytest.raises(AssertionError, match="history contém data >= as_of"):
        forecaster.fit(_history(), AS_OF - timedelta(days=1))


class _TeeForecaster:
    """Alimenta o `SpyForecaster` com exatamente o mesmo `fit` que o naive
    sazonal recebe, e guarda a previsão de cada decisão."""

    def __init__(self, spy: SpyForecaster) -> None:
        self.spy = spy
        self.naive = NaiveSeasonalForecaster()
        self.predictions: dict[date, float | None] = {}

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        self.spy.fit(history, as_of)
        self.naive.fit(history, as_of)

    def predict_quantiles(self, as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        result = self.naive.predict_quantiles(as_of, horizon, quantiles)
        self.predictions[as_of] = result["value"][0]
        return result


def test_horizonte_14_no_simulador_nunca_ve_dado_posterior_a_as_of() -> None:
    # Demanda de D0 a D34 vinda da série acima (3 semanas) repetida com +1000 depois,
    # para que qualquer vazamento de D21+ mude o número. O simulador filtra o
    # histórico (`date < as_of`); o espião confere o corte a cada decisão.
    total_days = 35
    units = [float(_UNITS[i]) if i < 21 else 1000.0 + i for i in range(total_days)]
    demand = pl.DataFrame(
        {"date": [D0 + timedelta(days=i) for i in range(total_days)], "units_sold": units}
    )
    spy = SpyForecaster(demand_per_day=0.0)
    tee = _TeeForecaster(spy)
    simulator = Simulator(
        InventoryState(data_inicial=D0 - timedelta(days=1)),
        tee,
        OrderUpToPolicy(target_level=0.0),
        demand,
        lead_time_days=1,
        horizon_days=14,
        quantiles=[0.5],
        is_review_day=review_every_n_days(reference=AS_OF, period_days=7),
        shelf_life_from_arrival_days=None,
    )
    simulator.run(D0, D0 + timedelta(days=total_days - 1))

    assert spy.as_of_calls == [AS_OF + timedelta(days=7 * k) for k in range(-3, 2)]
    assert spy.max_history_date_seen is not None
    assert spy.max_history_date_seen < max(spy.as_of_calls)

    # Decisão em AS_OF: history só até D20 -> semana 3 duas vezes = 5600, sem tocar em D21+.
    assert tee.predictions[AS_OF] == 5600.0
    # Decisão uma semana antes (history até D13): semana 2 duas vezes = 2 x 280.
    assert tee.predictions[AS_OF - timedelta(days=7)] == 560.0
