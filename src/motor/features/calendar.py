"""Calendário (Sprint 14): dia da semana, feriado nacional/estadual/municipal,
início de mês, quinzena e dia de pagamento -- tudo em função só da DATA (e da
cidade/estado da loja), nunca da série de vendas.

Segunda porta de I/O do projeto -- ver CLAUDE.md, seção 4 (emenda Sprint 14):
`holidays_events` e `stores` não têm onde morar nas quatro tabelas canônicas
(sales/items/suppliers/stock), então este módulo lê os dois DIRETO do parquet
bruto já convertido (`motor.io.raw.scan_raw`, Sprint 2), fora do canônico.
`load_store_locale`/`load_holidays` são a única fronteira de I/O deste
módulo; `build_calendar_features` é pura.

Calendário nunca vaza futuro por definição -- feriado de qualquer data é
conhecido de antemão, ao contrário de venda. A regra de vazamento (CLAUDE.md,
seção 8) se aplica a `motor.features.build`, não a este módulo.

REGRA DE FERIADO EFETIVO -- `holidays_events.type` tem seis valores; só
quatro definem um dia sem expediente, e um deles muda em que DATA o feriado
conta:

- `Holiday`/`Additional` com `transferred=False` -> feriado na própria `date`.
- `Holiday` com `transferred=True` -> NÃO conta na própria `date` -- o
  feriado foi movido para outro dia, que aparece como uma linha `Transfer`
  separada (mesma `locale`/`locale_name`, `date` diferente).
- `Transfer` -> feriado na própria `date` -- é exatamente a data para onde o
  feriado transferido foi movido; a linha correspondente `Holiday
  transferred=True` na data original é ignorada de propósito.
- `Bridge` -> dia de ponte, tratado como feriado extra na própria `date`.
- `Event`/`Work Day` -> NUNCA contam como feriado. `Event` não é dia sem
  expediente (ex.: evento esportivo, terremoto -- o terremoto de 2016 já é
  tratado à parte por `canonical.anomalies`, não deveria duplicar aqui).
  `Work Day` é uma compensação de ponte (dia que seria de folga e passa a
  ser útil) -- o oposto semântico de um feriado.

`locale=National` aplica a toda loja independente de `locale_name` (só existe
um país no dataset) -- não filtramos por `locale_name=="Ecuador"` para não
depender de um literal específico do dado. `Regional`/`Local` filtram por
`locale_name` igual ao `state`/`city` da loja (`StoreLocale`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from motor.config import FeatureCalendarParams
from motor.io.raw import scan_raw

_EFFECTIVE_HOLIDAY_TYPES = frozenset({"Holiday", "Additional", "Transfer", "Bridge"})


@dataclass(frozen=True)
class StoreLocale:
    """Cidade e estado de uma loja -- resolve feriado regional/local."""

    city: str
    state: str


def load_store_locale(store_id: str, raw_parquet_dir: Path) -> StoreLocale:
    """Lê `stores.parquet` (bruto, Sprint 2) e devolve cidade/estado de `store_id`."""
    stores = scan_raw("stores", raw_parquet_dir).collect()
    row = stores.filter(pl.col("store_nbr") == int(store_id))
    if row.height != 1:
        msg = (
            f"store_id {store_id!r} não encontrado (ou duplicado) em stores.parquet -- "
            f"esperava exatamente 1 linha, encontrou {row.height}"
        )
        raise ValueError(msg)
    return StoreLocale(city=str(row["city"][0]), state=str(row["state"][0]))


def load_holidays(raw_parquet_dir: Path) -> pl.DataFrame:
    """Lê `holidays_events.parquet` (bruto, Sprint 2) por inteiro.

    Sem corte por data: calendário de feriado é conhecido de antemão para
    qualquer ano coberto pelo dataset -- ler o arquivo inteiro aqui não é o
    vazamento que `motor.features.build` precisa evitar (esse é sobre venda,
    não sobre calendário público).
    """
    return scan_raw("holidays_events", raw_parquet_dir).collect()


def _effective_holiday_dates(
    holidays: pl.DataFrame, *, locale: str, locale_name: str | None
) -> set[date]:
    condicao = (pl.col("locale") == locale) & pl.col("type").is_in(
        list(_EFFECTIVE_HOLIDAY_TYPES)
    ) & ~((pl.col("type") == "Holiday") & pl.col("transferred"))
    if locale_name is not None:
        condicao = condicao & (pl.col("locale_name") == locale_name)
    matches = holidays.filter(condicao)
    return set(matches["date"].to_list())


def _last_day_of_month(d: date) -> date:
    proximo_mes_dia_1 = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return proximo_mes_dia_1 - timedelta(days=1)


def _resolve_payday(year: int, month: int, day_spec: int) -> date:
    """`day_spec == -1` é o sentinela de "último dia do mês" -- nunca um dia
    fixo (28/30/31), que erraria em fevereiro ou em mês de 30 dias."""
    last_day = _last_day_of_month(date(year, month, 1))
    if day_spec == -1:
        return last_day
    return date(year, month, min(day_spec, last_day.day))


def _days_to_payday(d: date, payday_days_of_month: Sequence[int]) -> int:
    """Distância (>= 0) até o próximo dia de pagamento, podendo ser o
    próprio `d`. Olha só o mês corrente e o seguinte -- suficiente porque
    todo mês tem, por construção, pelo menos uma ocorrência de cada
    `day_spec` (o sentinela `-1` sempre resolve para um dia real do mês)."""
    candidatos: list[date] = []
    for offset in (0, 1):
        mes_total = d.month - 1 + offset
        ano = d.year + mes_total // 12
        mes = mes_total % 12 + 1
        for spec in payday_days_of_month:
            candidato = _resolve_payday(ano, mes, spec)
            if candidato >= d:
                candidatos.append(candidato)
    return (min(candidatos) - d).days


def build_calendar_features(
    dates: Sequence[date],
    *,
    locale: StoreLocale,
    holidays: pl.DataFrame,
    params: FeatureCalendarParams,
) -> pl.DataFrame:
    """Uma linha por data em `dates` (sem duplicar, ordem de `dates`
    preservada) com as sete features de calendário. Pura -- `holidays` e
    `locale` já vêm carregados por quem chama."""
    nacional = _effective_holiday_dates(holidays, locale="National", locale_name=None)
    regional = _effective_holiday_dates(holidays, locale="Regional", locale_name=locale.state)
    local = _effective_holiday_dates(holidays, locale="Local", locale_name=locale.city)

    linhas = [
        {
            "date": d,
            "weekday": d.isoweekday(),
            "is_month_start": d.day <= params.month_start_max_day,
            "quinzena": 1 if d.day <= params.quinzena_split_day else 2,
            "days_to_payday": _days_to_payday(d, params.payday_days_of_month),
            "is_holiday_national": d in nacional,
            "is_holiday_regional": d in regional,
            "is_holiday_local": d in local,
        }
        for d in dates
    ]
    return pl.DataFrame(
        linhas,
        schema={
            "date": pl.Date,
            "weekday": pl.Int64,
            "is_month_start": pl.Boolean,
            "quinzena": pl.Int64,
            "days_to_payday": pl.Int64,
            "is_holiday_national": pl.Boolean,
            "is_holiday_regional": pl.Boolean,
            "is_holiday_local": pl.Boolean,
        },
    )
