"""Perfil do dataset bruto Favorita -- funções puras sobre `pl.LazyFrame`.

Nenhuma função aqui lê arquivo nem imprime: recebem `pl.LazyFrame`, devolvem
`pl.DataFrame`. É isso que as torna testáveis com frame sintético construído à
mão (CLAUDE.md, seção 2: notebook e teste não podem depender do dado real
existir). Quem chama `scan_raw` e decide quando `.collect()` é o notebook.

Os nomes de coluna usados aqui são os do arquivo bruto (`store_nbr`,
`item_nbr`, `unit_sales`, `onpromotion`) -- mapear para os nomes canônicos
(`store_id`, `item_id`, `units_sold`, ...) é normalização, e normalização é
Sprint 3, fora do escopo desta sprint (ver CLAUDE.md, seção 4, e a "fronteira
de escopo" do prompt da Sprint 2).

Três armadilhas que este módulo existe para evitar (ver docstring de cada
função para o detalhe):

1. Linha de venda zero não existe no arquivo -- por isso a métrica central é
   densidade (dias com venda / dias do denominador), nunca a média das linhas
   presentes.
2. O denominador da densidade não pode ser o calendário global -- loja que
   abre no meio da série vira "item intermitente" por engano se usar o
   calendário global. `density_window` intersecta a janela de análise com o
   lifespan real da loja.
3. Não existe preço, custo nem saldo de estoque no Favorita -- "participação
   no volume" aqui é sempre participação em UNIDADES, nunca em R$.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import polars as pl

# --------------------------------------------------------------------------
# Calendário e cobertura
# --------------------------------------------------------------------------


def profile_calendar(sales: pl.LazyFrame) -> pl.DataFrame:
    """Perfil de uma linha só: intervalo de datas, nº de lojas, itens, pares e linhas.

    `n_pairs` é a contagem de combinações (store_nbr, item_nbr) distintas
    observadas em pelo menos uma linha -- não confundir com `n_stores *
    n_items`, que superestima (nem toda loja vende todo item).
    """
    scalar_stats = sales.select(
        pl.col("date").min().alias("date_min"),
        pl.col("date").max().alias("date_max"),
        pl.col("store_nbr").n_unique().alias("n_stores"),
        pl.col("item_nbr").n_unique().alias("n_items"),
        pl.len().alias("n_rows"),
    ).collect(engine="streaming")

    n_pairs = (
        sales.select("store_nbr", "item_nbr")
        .unique()
        .select(pl.len())
        .collect(engine="streaming")
        .item()
    )
    return scalar_stats.with_columns(pl.lit(n_pairs).alias("n_pairs"))


def profile_store_lifespan(sales: pl.LazyFrame) -> pl.DataFrame:
    """Por loja: primeira e última venda, e nº de dias distintos com movimento.

    `n_days_with_movement` conta dias com pelo menos uma linha de venda de
    qualquer item -- é o proxy de "a loja estava aberta e vendendo neste dia",
    usado por `profile_pair_coverage` para saber quando cada loja abriu.
    """
    return (
        sales.group_by("store_nbr")
        .agg(
            pl.col("date").min().alias("first_sale"),
            pl.col("date").max().alias("last_sale"),
            pl.col("date").n_unique().alias("n_days_with_movement"),
        )
        .sort("store_nbr")
        .collect(engine="streaming")
    )


def profile_pair_coverage(
    sales: pl.LazyFrame, *, window_start: date, window_end: date
) -> pl.DataFrame:
    """Por par (store_nbr, item_nbr): densidade de venda dentro da janela.

    Todas as colunas (`first_sale`, `last_sale`, `n_days_with_sale`,
    `span_days`) são calculadas sobre as vendas do par **restritas à janela**
    -- a janela é o que se está avaliando, não um filtro cosmético aplicado
    depois.

    Duas densidades, com denominadores diferentes de propósito (armadilha 2 da
    docstring do módulo):

    - `density_pair_span`: `n_days_with_sale / span_days`, onde `span_days` é
      o intervalo entre a primeira e a última venda do PAR dentro da janela.
      Auto-referente: mede quão intermitente o par é dentro do próprio trecho
      em que aparece, e não penaliza um par que só começou a vender no meio da
      janela.
    - `density_window`: `n_days_with_sale / window_denominator_days`, onde o
      denominador é a interseção de `[window_start, window_end]` com o
      lifespan da LOJA (`max(window_start, store_open)` até `window_end`).
      Loja que abre no meio da janela reduz o denominador; loja que já
      operava antes da janela usa a janela inteira. Esta é a densidade que a
      Sprint 4 usa para selecionar o subconjunto.

    `store_covers_full_window` é `True` quando a loja já operava em
    `window_start` (ou antes) -- ou seja, quando `density_window` não foi
    encurtada por abertura tardia. Não está na lista de colunas do enunciado
    da Sprint 2; foi acrescentada porque `count_candidates` precisa dessa
    informação para o parâmetro `require_full_window`, e recalculá-la ali
    duplicaria a lógica de lifespan que já mora aqui.

    `store_open` vem do histórico de vendas INTEIRO (não restrito à janela) --
    precisa saber quando a loja abriu de verdade, não só o que aparece dentro
    do recorte que está sendo avaliado.
    """
    store_open = sales.group_by("store_nbr").agg(pl.col("date").min().alias("store_open"))

    windowed = sales.filter(pl.col("date").is_between(window_start, window_end))
    pair_stats = windowed.group_by("store_nbr", "item_nbr").agg(
        pl.col("date").min().alias("first_sale"),
        pl.col("date").max().alias("last_sale"),
        pl.col("date").n_unique().alias("n_days_with_sale"),
    )

    window_start_lit = pl.lit(window_start, dtype=pl.Date)
    window_end_lit = pl.lit(window_end, dtype=pl.Date)

    result = (
        pair_stats.join(store_open, on="store_nbr", how="left")
        .with_columns(
            (pl.col("last_sale") - pl.col("first_sale")).dt.total_days().alias("span_days"),
            pl.max_horizontal(window_start_lit, pl.col("store_open")).alias(
                "effective_window_start"
            ),
        )
        .with_columns(
            (pl.col("span_days") + 1).alias("span_days"),
            (window_end_lit - pl.col("effective_window_start"))
            .dt.total_days()
            .alias("window_denominator_days"),
            (pl.col("effective_window_start") <= window_start_lit).alias(
                "store_covers_full_window"
            ),
        )
        .with_columns((pl.col("window_denominator_days") + 1).alias("window_denominator_days"))
        .with_columns(
            (pl.col("n_days_with_sale") / pl.col("span_days")).alias("density_pair_span"),
            (pl.col("n_days_with_sale") / pl.col("window_denominator_days")).alias(
                "density_window"
            ),
        )
        .select(
            "store_nbr",
            "item_nbr",
            "first_sale",
            "last_sale",
            "n_days_with_sale",
            "span_days",
            "density_pair_span",
            "density_window",
            "store_covers_full_window",
        )
        .sort("store_nbr", "item_nbr")
    )
    return result.collect(engine="streaming")


# --------------------------------------------------------------------------
# Volume (em unidades -- não existe preço no Favorita)
# --------------------------------------------------------------------------


def profile_item_volume(sales: pl.LazyFrame) -> pl.DataFrame:
    """Por item: unidades totais, mediana/p90/máximo da venda diária, nº de lojas e
    participação acumulada no volume.

    "Participação" é sempre em UNIDADES. O Favorita não tem preço nem custo;
    nada aqui é nem finge ser R$ (armadilha 3 da docstring do módulo).
    """
    per_item = (
        sales.group_by("item_nbr")
        .agg(
            pl.col("unit_sales").sum().alias("total_units"),
            pl.col("unit_sales").median().alias("median_daily_units"),
            pl.col("unit_sales").quantile(0.9).alias("p90_daily_units"),
            pl.col("unit_sales").max().alias("max_daily_units"),
            pl.col("store_nbr").n_unique().alias("n_stores"),
        )
        .collect(engine="streaming")
        .sort("total_units", descending=True)
    )
    total = per_item["total_units"].sum()
    return per_item.with_columns((pl.col("total_units").cum_sum() / total).alias("cum_unit_share"))


# --------------------------------------------------------------------------
# Vendas negativas e fracionárias -- funções separadas de propósito: shapes
# diferentes (uma linha global, uma linha por item) não devem sair do mesmo
# pl.DataFrame, senão quem chama não sabe qual recebeu.
# --------------------------------------------------------------------------


def profile_negatives_global(sales: pl.LazyFrame) -> pl.DataFrame:
    """Uma linha: proporção global de linhas com `unit_sales < 0`."""
    return sales.select(
        pl.len().alias("n_rows"),
        (pl.col("unit_sales") < 0).sum().alias("n_negative_rows"),
        (pl.col("unit_sales") < 0).mean().alias("negative_ratio"),
    ).collect(engine="streaming")


def profile_negatives_by_item(sales: pl.LazyFrame) -> pl.DataFrame:
    """Por item: proporção de linhas com `unit_sales < 0`."""
    return (
        sales.group_by("item_nbr")
        .agg(
            pl.len().alias("n_rows"),
            (pl.col("unit_sales") < 0).sum().alias("n_negative_rows"),
            (pl.col("unit_sales") < 0).mean().alias("negative_ratio"),
        )
        .sort("item_nbr")
        .collect(engine="streaming")
    )


def profile_fractional_global(sales: pl.LazyFrame) -> pl.DataFrame:
    """Uma linha: proporção global de linhas com `unit_sales` fracionário.

    Fracionário é o sinal de item vendido por peso -- é o que vai marcar
    `unit_of_sale = kg` na Sprint 3, não algo a "corrigir" aqui.
    """
    is_fractional = pl.col("unit_sales") != pl.col("unit_sales").round(0)
    return sales.select(
        pl.len().alias("n_rows"),
        is_fractional.sum().alias("n_fractional_rows"),
        is_fractional.mean().alias("fractional_ratio"),
    ).collect(engine="streaming")


def profile_fractional_by_item(sales: pl.LazyFrame) -> pl.DataFrame:
    """Por item: proporção de linhas com `unit_sales` fracionário."""
    is_fractional = pl.col("unit_sales") != pl.col("unit_sales").round(0)
    return (
        sales.group_by("item_nbr")
        .agg(
            pl.len().alias("n_rows"),
            is_fractional.sum().alias("n_fractional_rows"),
            is_fractional.mean().alias("fractional_ratio"),
        )
        .sort("item_nbr")
        .collect(engine="streaming")
    )


def profile_promo_availability(sales: pl.LazyFrame) -> pl.DataFrame:
    """Por mês: proporção de `onpromotion` nulo.

    É essa curva que diz a partir de que mês o campo passa a ser utilizável --
    o Favorita não registra promoção nos primeiros anos da série.
    """
    return (
        sales.with_columns(pl.col("date").dt.truncate("1mo").alias("month"))
        .group_by("month")
        .agg(
            pl.len().alias("n_rows"),
            pl.col("onpromotion").is_null().sum().alias("n_null"),
            pl.col("onpromotion").is_null().mean().alias("null_ratio"),
        )
        .sort("month")
        .collect(engine="streaming")
    )


# --------------------------------------------------------------------------
# Candidatos ao subconjunto de trabalho
# --------------------------------------------------------------------------


def count_candidates(
    coverage: pl.LazyFrame,
    *,
    min_density: Sequence[float],
    require_full_window: bool,
    items: pl.LazyFrame | None = None,
) -> pl.DataFrame:
    """Quantos pares loja-item sobrevivem a cada corte de `density_window`.

    Uma linha por valor em `min_density` -- "vários cortes, não um número só"
    quer dizer que `min_density` é uma sequência, varrida aqui dentro; não é
    responsabilidade de quem chama rodar a função várias vezes.

    `coverage` é a saída de `profile_pair_coverage`. Se `require_full_window`,
    filtra para pares cuja loja já cobria a janela inteira
    (`store_covers_full_window`) antes de aplicar o corte de densidade --
    exclui loja nova cuja densidade alta só existe porque o denominador dela é
    pequeno.

    `items` é opcional (tabela bruta `items.csv`, com `item_nbr`/`family`). Se
    informado, cada linha ganha `n_families` (famílias distintas entre os
    pares sobreviventes) e `top_family` (a de maior nº de pares, desempate
    alfabético para o resultado ser determinístico) -- dimensão que a Sprint 4
    precisa para não escolher o subconjunto de uma categoria só.
    """
    base = coverage
    if require_full_window:
        base = base.filter(pl.col("store_covers_full_window"))
    if items is not None:
        base = base.join(items.select("item_nbr", "family"), on="item_nbr", how="left")

    rows: list[pl.DataFrame] = []
    for cutoff in min_density:
        survivors = base.filter(pl.col("density_window") >= cutoff)
        agg_exprs = [
            pl.lit(cutoff).alias("min_density"),
            pl.len().alias("n_pairs"),
            pl.col("store_nbr").n_unique().alias("n_stores"),
            pl.col("item_nbr").n_unique().alias("n_items"),
        ]
        if items is not None:
            agg_exprs.append(pl.col("family").n_unique().alias("n_families"))
        row = survivors.select(agg_exprs).collect(engine="streaming")

        if items is not None:
            top_family_df = (
                survivors.group_by("family")
                .agg(pl.len().alias("n_pairs_in_family"))
                .sort(["n_pairs_in_family", "family"], descending=[True, False])
                .limit(1)
                .collect(engine="streaming")
            )
            top_family = top_family_df["family"].item() if top_family_df.height > 0 else None
            row = row.with_columns(pl.lit(top_family).alias("top_family"))

        rows.append(row)

    return pl.concat(rows)
