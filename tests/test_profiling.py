"""Testes de motor.profiling -- todo frame é sintético, construído à mão.

Nenhum teste depende dos arquivos reais em data/raw/favorita/ (eles não
existem no repositório e o CI não os teria).
"""

from __future__ import annotations

from datetime import date

import polars as pl

from motor.profiling import (
    count_candidates,
    profile_fractional_by_item,
    profile_fractional_global,
    profile_negatives_by_item,
    profile_negatives_global,
    profile_pair_coverage,
    profile_promo_availability,
)

# --------------------------------------------------------------------------
# profile_pair_coverage
# --------------------------------------------------------------------------


def test_densidade_com_buracos_de_calendario_conhecidos() -> None:
    """Um único par, loja já aberta bem antes da janela (denominador da
    densidade da janela = janela inteira, sem interação de lifespan -- isso é
    testado à parte).

    Janela: 2021-01-01 .. 2021-01-10 (10 dias corridos).
    Vendas do par dentro da janela: 01-01, 01-03, 01-05 (3 dias distintos, com
    buracos em 01-02 e 01-04).

    Contas à mão:
    - n_days_with_sale = 3
    - span_days = (01-05 - 01-01) + 1 = 5  -> density_pair_span = 3/5 = 0.6
    - window_denominator_days = janela inteira = 10 (loja cobre a janela toda)
      -> density_window = 3/10 = 0.3
    """
    sales = pl.LazyFrame(
        {
            "store_nbr": [1, 1, 1, 1],
            "item_nbr": [100, 100, 100, 100],
            "date": [
                date(2020, 1, 1),  # fora da janela: só serve para fixar store_open bem antes dela
                date(2021, 1, 1),
                date(2021, 1, 3),
                date(2021, 1, 5),
            ],
        }
    )

    result = profile_pair_coverage(
        sales, window_start=date(2021, 1, 1), window_end=date(2021, 1, 10)
    )

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["store_nbr"] == 1
    assert row["item_nbr"] == 100
    assert row["first_sale"] == date(2021, 1, 1)
    assert row["last_sale"] == date(2021, 1, 5)
    assert row["n_days_with_sale"] == 3
    assert row["span_days"] == 5
    assert row["density_pair_span"] == 3 / 5
    assert row["density_window"] == 3 / 10
    assert row["store_covers_full_window"] is True


def test_interseccao_com_lifespan_de_loja_reduz_denominador() -> None:
    """Loja que abre no meio da janela: o denominador de density_window usa o
    lifespan real da loja, não o calendário global da janela (armadilha 2).

    Janela: 2021-01-01 .. 2021-01-10.
    Loja 2 vende pela primeira vez em 2021-01-05 (essa é a primeira linha dela
    em todo o histórico, não só na janela) -- ela "abriu" no meio da janela.
    Vendas do par (2, 200) dentro da janela: 01-05, 01-06, 01-08 (3 dias).

    Contas à mão:
    - n_days_with_sale = 3
    - span_days = (01-08 - 01-05) + 1 = 4 -> density_pair_span = 3/4 = 0.75
    - effective_window_start = max(01-01, store_open=01-05) = 01-05
    - window_denominator_days = (01-10 - 01-05) + 1 = 6 -> density_window = 3/6 = 0.5

    Uma loja que já operava antes da janela (loja 1) serve de contraste: para
    ela, window_denominator_days é a janela inteira (10), não 6.
    """
    sales = pl.LazyFrame(
        {
            "store_nbr": [1, 1, 2, 2, 2],
            "item_nbr": [100, 100, 200, 200, 200],
            "date": [
                date(2019, 1, 1),  # fixa store_open da loja 1 bem antes da janela
                date(2021, 1, 1),
                date(2021, 1, 5),  # primeira venda da loja 2 em todo o histórico
                date(2021, 1, 6),
                date(2021, 1, 8),
            ],
        }
    )

    result = profile_pair_coverage(
        sales, window_start=date(2021, 1, 1), window_end=date(2021, 1, 10)
    ).sort("store_nbr")

    loja_2 = result.filter(pl.col("store_nbr") == 2).row(0, named=True)
    assert loja_2["n_days_with_sale"] == 3
    assert loja_2["span_days"] == 4
    assert loja_2["density_pair_span"] == 3 / 4
    assert loja_2["density_window"] == 3 / 6
    assert loja_2["store_covers_full_window"] is False

    loja_1 = result.filter(pl.col("store_nbr") == 1).row(0, named=True)
    assert loja_1["density_window"] == 1 / 10
    assert loja_1["store_covers_full_window"] is True


# --------------------------------------------------------------------------
# negativos e fracionários -- não podem se confundir
# --------------------------------------------------------------------------


def _sales_negativas_e_fracionarias() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "item_nbr": [100, 100, 100, 200, 200],
            "unit_sales": [
                5.0,  # item 100: positivo, inteiro
                -2.0,  # item 100: negativo, inteiro (NÃO fracionário)
                3.5,  # item 100: positivo, fracionário (NÃO negativo)
                4.0,  # item 200: positivo, inteiro
                -1.25,  # item 200: negativo E fracionário ao mesmo tempo
            ],
        }
    )


def test_negativos_e_fracionarios_contagem_global_nao_se_confunde() -> None:
    sales = _sales_negativas_e_fracionarias()

    negatives = profile_negatives_global(sales).row(0, named=True)
    assert negatives["n_rows"] == 5
    assert negatives["n_negative_rows"] == 2  # -2.0 e -1.25
    assert negatives["negative_ratio"] == 2 / 5

    fractional = profile_fractional_global(sales).row(0, named=True)
    assert fractional["n_rows"] == 5
    assert fractional["n_fractional_rows"] == 2  # 3.5 e -1.25
    assert fractional["fractional_ratio"] == 2 / 5


def test_negativos_e_fracionarios_contagem_por_item_nao_se_confunde() -> None:
    sales = _sales_negativas_e_fracionarias()

    negatives = profile_negatives_by_item(sales).sort("item_nbr")
    item_100 = negatives.filter(pl.col("item_nbr") == 100).row(0, named=True)
    item_200 = negatives.filter(pl.col("item_nbr") == 200).row(0, named=True)
    assert item_100["n_negative_rows"] == 1  # só -2.0
    assert item_100["negative_ratio"] == 1 / 3
    assert item_200["n_negative_rows"] == 1  # só -1.25
    assert item_200["negative_ratio"] == 1 / 2

    fractional = profile_fractional_by_item(sales).sort("item_nbr")
    item_100_frac = fractional.filter(pl.col("item_nbr") == 100).row(0, named=True)
    item_200_frac = fractional.filter(pl.col("item_nbr") == 200).row(0, named=True)
    assert item_100_frac["n_fractional_rows"] == 1  # só 3.5
    assert item_100_frac["fractional_ratio"] == 1 / 3
    assert item_200_frac["n_fractional_rows"] == 1  # só -1.25
    assert item_200_frac["fractional_ratio"] == 1 / 2


# --------------------------------------------------------------------------
# profile_promo_availability
# --------------------------------------------------------------------------


def test_promo_availability_mes_todo_nulo_vs_parcial() -> None:
    sales = pl.LazyFrame(
        {
            "date": [
                date(2021, 1, 5),
                date(2021, 1, 15),
                date(2021, 1, 25),
                date(2021, 2, 5),
                date(2021, 2, 10),
                date(2021, 2, 20),
                date(2021, 2, 25),
            ],
            "onpromotion": [None, None, None, True, None, False, None],
        }
    )

    result = profile_promo_availability(sales).sort("month")

    janeiro = result.row(0, named=True)
    assert janeiro["month"] == date(2021, 1, 1)
    assert janeiro["n_rows"] == 3
    assert janeiro["n_null"] == 3
    assert janeiro["null_ratio"] == 1.0

    fevereiro = result.row(1, named=True)
    assert fevereiro["month"] == date(2021, 2, 1)
    assert fevereiro["n_rows"] == 4
    assert fevereiro["n_null"] == 2
    assert fevereiro["null_ratio"] == 0.5


# --------------------------------------------------------------------------
# count_candidates
# --------------------------------------------------------------------------


def _coverage_sintetica() -> pl.LazyFrame:
    # store_covers_full_window=False só no par (2, 200) -- é o único que
    # require_full_window deve excluir.
    return pl.LazyFrame(
        {
            "store_nbr": [1, 1, 1, 2, 2],
            "item_nbr": [100, 101, 102, 200, 201],
            "density_window": [0.9, 0.8, 0.7, 0.6, 0.4],
            "store_covers_full_window": [True, True, True, False, True],
        }
    )


def _items_sinteticos() -> pl.LazyFrame:
    # familia A domina (3 pares) sobre familia B (2 pares) em todo corte baixo.
    return pl.LazyFrame(
        {
            "item_nbr": [100, 101, 102, 200, 201],
            "family": ["A", "A", "A", "B", "B"],
        }
    )


def test_count_candidates_varre_cortes_sem_items() -> None:
    coverage = _coverage_sintetica()

    result = count_candidates(coverage, min_density=[0.3, 0.75], require_full_window=False)

    assert result["min_density"].to_list() == [0.3, 0.75]
    assert "n_families" not in result.columns
    assert "top_family" not in result.columns

    corte_baixo = result.row(0, named=True)
    assert corte_baixo["n_pairs"] == 5  # todos: 0.9,0.8,0.7,0.6,0.4 >= 0.3
    assert corte_baixo["n_stores"] == 2
    assert corte_baixo["n_items"] == 5

    corte_alto = result.row(1, named=True)
    assert corte_alto["n_pairs"] == 2  # só 0.9 e 0.8


def test_count_candidates_com_items_adiciona_dimensao_de_familia() -> None:
    coverage = _coverage_sintetica()
    items = _items_sinteticos()

    result = count_candidates(coverage, min_density=[0.3], require_full_window=False, items=items)

    row = result.row(0, named=True)
    assert row["n_pairs"] == 5
    assert row["n_families"] == 2
    assert row["top_family"] == "A"  # família A tem 3 pares contra 2 de B


def test_count_candidates_require_full_window_exclui_loja_nova() -> None:
    coverage = _coverage_sintetica()

    sem_filtro = count_candidates(coverage, min_density=[0.3], require_full_window=False)
    com_filtro = count_candidates(coverage, min_density=[0.3], require_full_window=True)

    assert sem_filtro.row(0, named=True)["n_pairs"] == 5
    assert com_filtro.row(0, named=True)["n_pairs"] == 4  # exclui o par (2, 200)
