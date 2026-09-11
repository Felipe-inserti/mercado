"""Testes de `motor.features.calendar` (Sprint 14)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from motor.config import FeatureCalendarParams
from motor.features.calendar import (
    StoreLocale,
    build_calendar_features,
    load_holidays,
    load_store_locale,
)

_LOCALE = StoreLocale(city="Quito", state="Pichincha")

_PARAMS = FeatureCalendarParams(
    month_start_max_day=3,
    quinzena_split_day=15,
    payday_days_of_month=[15, -1],
)


def _holiday_row(
    d: date,
    *,
    type_: str,
    locale: str,
    locale_name: str,
    transferred: bool = False,
    description: str = "",
) -> dict[str, object]:
    return {
        "date": d,
        "type": type_,
        "locale": locale,
        "locale_name": locale_name,
        "description": description,
        "transferred": transferred,
    }


def _holidays(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(
        list(rows),
        schema={
            "date": pl.Date,
            "type": pl.String,
            "locale": pl.String,
            "locale_name": pl.String,
            "description": pl.String,
            "transferred": pl.Boolean,
        },
    )


def _features(dates: list[date], holidays: pl.DataFrame) -> pl.DataFrame:
    return build_calendar_features(dates, locale=_LOCALE, holidays=holidays, params=_PARAMS)


# -- feriado efetivo: as seis semânticas de `type`/`transferred` -------------


def test_feriado_nacional_aplica_independente_de_locale_name() -> None:
    """National aplica a toda loja -- não filtra por `locale_name` (só há um país)."""
    d = date(2016, 8, 10)
    holidays = _holidays(
        _holiday_row(d, type_="Holiday", locale="National", locale_name="Ecuador")
    )
    out = _features([d], holidays)
    assert out["is_holiday_national"][0] is True
    assert out["is_holiday_regional"][0] is False
    assert out["is_holiday_local"][0] is False


def test_feriado_regional_so_aplica_ao_estado_da_loja() -> None:
    d = date(2016, 8, 10)
    holidays = _holidays(
        _holiday_row(d, type_="Holiday", locale="Regional", locale_name="Pichincha"),
        _holiday_row(d, type_="Holiday", locale="Regional", locale_name="Manabi"),
    )
    out = _features([d], holidays)
    assert out["is_holiday_regional"][0] is True  # Pichincha bate
    assert out["is_holiday_national"][0] is False
    assert out["is_holiday_local"][0] is False


def test_feriado_local_so_aplica_a_cidade_da_loja() -> None:
    d = date(2016, 8, 10)
    holidays = _holidays(
        _holiday_row(d, type_="Holiday", locale="Local", locale_name="Cuenca"),
    )
    out = _features([d], holidays)
    assert out["is_holiday_local"][0] is False  # loja é Quito, não Cuenca


def test_holiday_transferred_true_nao_conta_na_data_original() -> None:
    """Feriado transferido some da data original -- ele é observado noutro
    dia, carregado por uma linha `type=Transfer` separada (ver teste seguinte)."""
    d = date(2016, 8, 10)
    holidays = _holidays(
        _holiday_row(
            d, type_="Holiday", locale="National", locale_name="Ecuador", transferred=True
        )
    )
    out = _features([d], holidays)
    assert out["is_holiday_national"][0] is False


def test_type_transfer_conta_como_feriado_na_propria_data() -> None:
    """A linha `Transfer` já carrega a data em que o feriado é DE FATO observado."""
    original = date(2016, 8, 10)
    observado = date(2016, 8, 12)
    holidays = _holidays(
        _holiday_row(
            original, type_="Holiday", locale="National", locale_name="Ecuador", transferred=True
        ),
        _holiday_row(observado, type_="Transfer", locale="National", locale_name="Ecuador"),
    )
    out = _features([original, observado], holidays)
    por_data = dict(zip(out["date"].to_list(), out["is_holiday_national"].to_list(), strict=True))
    assert por_data[original] is False
    assert por_data[observado] is True


def test_type_bridge_conta_como_feriado_extra() -> None:
    d = date(2016, 8, 11)
    holidays = _holidays(_holiday_row(d, type_="Bridge", locale="National", locale_name="Ecuador"))
    out = _features([d], holidays)
    assert out["is_holiday_national"][0] is True


def test_type_additional_conta_como_feriado() -> None:
    d = date(2016, 8, 13)
    holidays = _holidays(
        _holiday_row(d, type_="Additional", locale="National", locale_name="Ecuador")
    )
    out = _features([d], holidays)
    assert out["is_holiday_national"][0] is True


@pytest.mark.parametrize("type_", ["Event", "Work Day"])
def test_type_event_e_work_day_nunca_contam_como_feriado(type_: str) -> None:
    d = date(2016, 8, 14)
    holidays = _holidays(_holiday_row(d, type_=type_, locale="National", locale_name="Ecuador"))
    out = _features([d], holidays)
    assert out["is_holiday_national"][0] is False


# -- calendário simples -------------------------------------------------


def test_weekday_e_month_start_e_quinzena() -> None:
    holidays = _holidays()
    dates = [
        date(2016, 8, 1),
        date(2016, 8, 3),
        date(2016, 8, 4),
        date(2016, 8, 16),
        date(2016, 8, 31),
    ]
    out = _features(dates, holidays)
    by_date = {row["date"]: row for row in out.to_dicts()}

    assert by_date[date(2016, 8, 1)]["weekday"] == 1  # segunda
    assert by_date[date(2016, 8, 1)]["is_month_start"] is True
    assert by_date[date(2016, 8, 3)]["is_month_start"] is True  # limite (month_start_max_day=3)
    assert by_date[date(2016, 8, 4)]["is_month_start"] is False
    assert by_date[date(2016, 8, 16)]["quinzena"] == 2
    assert by_date[date(2016, 8, 1)]["quinzena"] == 1


def test_days_to_payday_dentro_do_mes_e_atravessando_virada() -> None:
    holidays = _holidays()
    dates = [
        date(2016, 8, 10),
        date(2016, 8, 15),
        date(2016, 8, 16),
        date(2016, 8, 31),
        date(2016, 2, 29),
    ]
    out = _features(dates, holidays)
    by_date = {row["date"]: row for row in out.to_dicts()}

    assert by_date[date(2016, 8, 10)]["days_to_payday"] == 5  # até dia 15
    assert by_date[date(2016, 8, 15)]["days_to_payday"] == 0  # o próprio dia é payday
    assert by_date[date(2016, 8, 16)]["days_to_payday"] == 15  # até 31/08 (último dia)
    assert by_date[date(2016, 8, 31)]["days_to_payday"] == 0  # último dia do mês é payday
    # fevereiro bissexto: -1 resolve para 29, não 28 nem 31 fixo
    assert by_date[date(2016, 2, 29)]["days_to_payday"] == 0


# -- I/O: carregamento de stores/holidays a partir do raw parquet -----------


def test_load_store_locale_le_cidade_e_estado(tmp_path: Path) -> None:
    stores = pl.DataFrame(
        {
            "store_nbr": [44, 45],
            "city": ["Quito", "Guayaquil"],
            "state": ["Pichincha", "Guayas"],
            "type": ["A", "B"],
            "cluster": [5, 3],
        }
    )
    stores.write_parquet(tmp_path / "stores.parquet")

    locale = load_store_locale("44", tmp_path)
    assert locale == StoreLocale(city="Quito", state="Pichincha")


def test_load_store_locale_rejeita_store_id_desconhecido(tmp_path: Path) -> None:
    stores = pl.DataFrame(
        {
            "store_nbr": [44],
            "city": ["Quito"],
            "state": ["Pichincha"],
            "type": ["A"],
            "cluster": [5],
        }
    )
    stores.write_parquet(tmp_path / "stores.parquet")

    with pytest.raises(ValueError, match="99"):
        load_store_locale("99", tmp_path)


def test_load_holidays_le_arquivo_bruto_por_inteiro(tmp_path: Path) -> None:
    holidays = _holidays(
        _holiday_row(date(2016, 8, 10), type_="Holiday", locale="National", locale_name="Ecuador")
    )
    holidays.write_parquet(tmp_path / "holidays_events.parquet")

    out = load_holidays(tmp_path)
    assert out.height == 1
