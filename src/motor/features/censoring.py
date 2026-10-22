"""Censura de ruptura provável (Sprint 24, etapa 24.4b).

Venda zero num item que costuma vender, sem entrada de mercadoria recente, é
quase sempre ruptura -- o cliente quis comprar e não havia produto --, não
"demanda zero". Alimentar a previsão com esse zero ensina o modelo a pedir
menos justamente do item que faltou (CLAUDE.md, seção 8: venda tratada como
demanda). Este módulo marca esses dias; quem prevê os remove do histórico com
`drop_censored`. A demanda usada para MEDIR atendimento nunca passa por aqui.

Puro e sem vazamento: o dia `d` só olha `[d - janela_dias, d)`, nunca `d` nem
o futuro.

`stock` NÃO é entrada deste módulo: saldo de estoque fica fora de
`motor.features` (CLAUDE.md, Emenda da Sprint 15) até haver dado real com
saldo; reabrir com nova conversa.
"""

from __future__ import annotations

from typing import Final

import polars as pl

from motor.config import CensuraParams

REASON_NO_RECENT_ENTRY: Final = "sem_entrada_recente"
REASON_ENTRIES_UNKNOWN: Final = "sem_tabela_entries_condicao_de_entrada_ignorada"

_KEYS: Final = ("store_id", "item_id", "date")
_TOTAL_ITEM_ID: Final = "TOTAL"


def flag_probable_stockout(
    sales: pl.DataFrame,
    entries: pl.DataFrame | None,
    params: CensuraParams,
) -> pl.DataFrame:
    """Marca os dias de ruptura provável. Uma linha por linha de `sales`.

    Um dia é marcado quando, ao mesmo tempo:
      1. `units_sold == 0`;
      2. a média de `units_sold` das linhas dos `janela_dias` dias ANTERIORES
         é >= `media_minima_por_dia`;
      3. há >= `dias_minimos_com_venda` dias com venda nessa janela;
      4. o item não recebeu nenhuma entrada nos `dias_sem_entrada_antes` dias
         anteriores (ignorada se `entries is None`; `reason` registra isso).

    `media_minima_por_dia` e `dias_minimos_com_venda` dependem do dado real e
    ficam `null` no `params.yaml`: usá-los vazios levanta `MissingParamError`.

    Colunas de saída: `store_id`, `item_id`, `date`, `is_censored`, `reason`
    (`reason` nulo nas linhas não marcadas).
    """
    min_mean = float(params.require("media_minima_por_dia"))
    min_sale_days = int(params.require("dias_minimos_com_venda"))
    window = f"{params.janela_dias}d"
    group = ["store_id", "item_id"]

    ordered = sales.select(*_KEYS, "units_sold").sort(*group, "date")
    ordered = ordered.with_columns(
        pl.col("units_sold").rolling_mean_by("date", window, closed="left").over(group).alias("_m"),
        (pl.col("units_sold") > 0)
        .cast(pl.Int64)
        .rolling_sum_by("date", window, closed="left")
        .over(group)
        .alias("_n"),
    )
    pattern = (
        (pl.col("units_sold") == 0) & (pl.col("_m") >= min_mean) & (pl.col("_n") >= min_sale_days)
    ).fill_null(False)

    if entries is None:
        recent_entry = pl.lit(False)
        pattern_reason = REASON_ENTRIES_UNKNOWN
    else:
        covered = (
            entries.select(
                "store_id",
                "item_id",
                pl.date_ranges(
                    pl.col("received_date") + pl.duration(days=1),
                    pl.col("received_date") + pl.duration(days=params.dias_sem_entrada_antes),
                ).alias("date"),
            )
            .explode("date", empty_as_null=False)
            .unique()
            .with_columns(pl.lit(True).alias("_recent_entry"))
        )
        ordered = ordered.join(covered, on=list(_KEYS), how="left")
        recent_entry = pl.col("_recent_entry").fill_null(False)
        pattern_reason = REASON_NO_RECENT_ENTRY

    by_pattern = pattern & ~recent_entry
    return ordered.select(
        *_KEYS,
        by_pattern.alias("is_censored"),
        pl.when(by_pattern)
        .then(pl.lit(pattern_reason))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias("reason"),
    )


def flags_if_active(
    sales: pl.DataFrame,
    entries: pl.DataFrame | None,
    params: CensuraParams,
) -> pl.DataFrame | None:
    """Calcula as flags UMA vez, para quem monta o experimento passá-las para
    dentro; com `censura.ativa: false` devolve `None` (e nada é calculado), o
    sinal que todo ponto de chamada trata como "comportamento de antes"."""
    if not params.ativa:
        return None
    return flag_probable_stockout(sales, entries, params)


def flags_for_item(flags: pl.DataFrame, store_id: str, item_id: str) -> pl.DataFrame:
    """Flags de UM par loja-item, só `date` e `is_censored` -- o formato que o
    grão por par do simulador consome."""
    return flags.filter((pl.col("store_id") == store_id) & (pl.col("item_id") == item_id)).select(
        "date", "is_censored"
    )


def drop_censored(history: pl.DataFrame, flags: pl.DataFrame) -> pl.DataFrame:
    """Remove de `history` as linhas marcadas em `flags`.

    A junção usa as colunas entre `store_id`, `item_id` e `date` presentes nas
    DUAS tabelas (`date` sempre): `history` por par (só `date`) casa com
    `flags_for_item`; `history` de painel casa com as flags completas.
    Sem nenhuma linha marcada, devolve `history` inalterado.
    """
    marked = flags.filter(pl.col("is_censored"))
    if marked.height == 0:
        return history
    keys = [c for c in _KEYS if c in history.columns and c in marked.columns]
    if "date" not in keys:
        msg = "drop_censored exige a coluna `date` em history e em flags"
        raise ValueError(msg)
    return history.join(marked.select(keys).unique(), on=keys, how="anti")


def censoring_summary(flags: pl.DataFrame, params: CensuraParams) -> pl.DataFrame:
    """Dias marcados por item e no total.

    Colunas: `store_id`, `item_id`, `days`, `censored_days`, `censored_share`,
    `alert` (`True` quando `censored_share > alerta_percentual_dias_censurados`).
    A última linha é o total (`item_id == "TOTAL"`, `store_id` nulo). Muito dia
    censurado sinaliza limiar frouxo demais, ou ruptura crônica que o piloto
    precisa tratar antes de qualquer modelo.
    """
    per_item = (
        flags.group_by("store_id", "item_id")
        .agg(
            pl.len().alias("days"),
            pl.col("is_censored").sum().cast(pl.Int64).alias("censored_days"),
        )
        .sort("store_id", "item_id")
    )
    total = pl.DataFrame(
        {
            "store_id": [None],
            "item_id": [_TOTAL_ITEM_ID],
            "days": [int(per_item["days"].sum())],
            "censored_days": [int(per_item["censored_days"].sum())],
        },
        schema=per_item.schema,
    )
    return (
        pl.concat([per_item, total])
        .with_columns((pl.col("censored_days") / pl.col("days")).alias("censored_share"))
        .with_columns(
            (pl.col("censored_share") > params.alerta_percentual_dias_censurados).alias("alert")
        )
    )
