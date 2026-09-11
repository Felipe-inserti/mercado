"""Sprint 4: seleção do subconjunto de trabalho (uma loja, 150-300 itens de demanda regular).

A Fase A (relatório de medição M1-M7) decidiu D1-D8; este módulo é a Fase B:
uma função pura, `select_subset`, que aplica esses cortes em ordem sobre as
quatro tabelas canônicas e devolve a lista final de `item_id` mais o funil
que sustenta a escolha perante um leitor cético (CLAUDE.md, seção 10).

Cada filtro é uma função isolada e testável, com frame sintético pequeno --
nunca um único `.filter()` encadeado (enunciado da Sprint 4, "Regras"). Cada
uma registra, no funil, quantos itens entraram e quantos saíram.

Ordem dos filtros -- a ordem importa e é a ordem em que os dados foram lidos
na Fase A, não deve ser alterada sem revisitar o relatório:

1. `_pairs_for_store`          -- pares da loja escolhida (D1). Estrutural,
   primeiro corte de escopo.
2. `_lifespan_complete`        -- histórico completo na janela canônica
   inteira (D2). Estrutural: olha se o item estava CADASTRADO o trecho todo,
   nunca se ele vendeu bem -- é a diferença entre corte estrutural (aceitável)
   e corte por desempenho futuro (proibido, CLAUDE.md seção 8).
3. `_density_by_item` + corte  -- densidade >= piso, medida SÓ na fatia seguro
   `subset_selection.density_window_*` (D3). Essa fatia termina estritamente
   antes de `simulation.start_date` -- `_assert_no_leakage` barra em runtime
   qualquer `params.yaml` que reabra a sobreposição. A fatia é lida como
   contrato fixo de `Params`, nunca como argumento de `select_subset`.
4. `_exclude_promo_dominated`  -- item cujos dias na fatia D3 são majoritariamente
   promoção (D6): não é demanda regular de prateleira.
5. `_exclude_degenerate_families` -- família inteira com poucos itens no pool
   regular sai (D6): fornecedor de 1-2 itens degenera a regra de pedido
   mínimo (M5). Depende da contagem PÓS-filtros acima, por isso vem depois.
6. `_cap_by_family`            -- único corte que reduz o N final para dentro
   de 150-300 (D5/D7). Ordem determinística por construção (sort explícito),
   nunca a ordem de iteração de um `group_by`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from motor.config import Params
from motor.io.contracts import PolarsDtype

# --------------------------------------------------------------------------
# Erros
# --------------------------------------------------------------------------


class LeakageGuardError(ValueError):
    """`subset_selection.density_window_end` alcança ou ultrapassa `simulation.start_date`.

    Existe para que uma edição futura de `params.yaml` não reabra em silêncio
    a sobreposição entre a fatia de medição de regularidade (D3) e o período
    que o simulador vai avaliar (D2) -- ver docstring do módulo.
    """


# --------------------------------------------------------------------------
# Resultado
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SubsetSelectionResult:
    """Saída de `select_subset`: loja, lista final de itens, e o funil que sustenta a escolha.

    `item_ids` já sai na ordem final determinística (D7): por família, na
    ordem (contagem_familia asc, family_slug asc via `supplier_id`), e dentro
    de cada família por (densidade desc, item_id asc). Não é ordem alfabética
    simples nem ordem de `group_by` -- é a ordem que
    `test_determinismo_do_cap_por_familia` verifica.
    """

    store_id: str
    item_ids: tuple[str, ...]
    funnel: pl.DataFrame


_FUNNEL_SCHEMA: dict[str, PolarsDtype] = {
    "stage": pl.String,
    "n_antes": pl.Int64,
    "n_depois": pl.Int64,
    "n_excluidos": pl.Int64,
    "motivo": pl.String,
}


def _funnel_row(stage: str, n_antes: int, n_depois: int, motivo: str) -> dict[str, object]:
    return {
        "stage": stage,
        "n_antes": n_antes,
        "n_depois": n_depois,
        "n_excluidos": n_antes - n_depois,
        "motivo": motivo,
    }


# --------------------------------------------------------------------------
# Filtros -- uma função pura por critério, componível
# --------------------------------------------------------------------------


def _pairs_for_store(sales: pl.LazyFrame, *, store_id: str) -> pl.DataFrame:
    """`item_id` distintos com ao menos uma linha para `store_id` (D1)."""
    return (
        sales.filter(pl.col("store_id") == store_id)
        .select("item_id")
        .unique()
        .sort("item_id")
        .collect(engine="streaming")
    )


def _lifespan_complete(
    sales: pl.LazyFrame, *, store_id: str, window_start: date, window_end: date
) -> pl.DataFrame:
    """`item_id` cujo lifespan, na loja `store_id`, cobre a janela canônica inteira (D2).

    "Cobre a janela inteira" = a primeira e a última linha do par estão
    exatamente em `window_start`/`window_end` -- a tabela de vendas já é
    reindexada (Sprint 3) para ter uma linha por dia de todo o lifespan do
    par, então isso não exige olhar `units_sold`, só presença de linha.
    Estrutural: pergunta se o item estava cadastrado o trecho todo, nunca se
    vendeu bem (CLAUDE.md, seção 4).
    """
    return (
        sales.filter(pl.col("store_id") == store_id)
        .group_by("item_id")
        .agg(pl.col("date").min().alias("_inicio"), pl.col("date").max().alias("_fim"))
        .filter((pl.col("_inicio") <= window_start) & (pl.col("_fim") >= window_end))
        .select("item_id")
        .sort("item_id")
        .collect(engine="streaming")
    )


def _density_by_item(
    sales: pl.LazyFrame,
    *,
    store_id: str,
    density_window_start: date,
    density_window_end: date,
) -> pl.DataFrame:
    """Densidade (dias com venda / dias da fatia) e proporção de dias em promoção, por item (D3/D6).

    O filtro por `date` é a PRIMEIRA coisa que a função faz -- nenhuma linha
    fora de `[density_window_start, density_window_end]` entra em qualquer
    agregação aqui. É essa propriedade que
    `test_isolamento_temporal_nao_ve_periodo_de_avaliacao` prova na prática:
    truncar o `sales` de entrada nessa data não muda o resultado.
    """
    janela = sales.filter(
        (pl.col("store_id") == store_id)
        & (pl.col("date") >= density_window_start)
        & (pl.col("date") <= density_window_end)
    )
    return (
        janela.group_by("item_id")
        .agg(
            pl.len().alias("n_dias_na_fatia"),
            (pl.col("units_sold") > 0).sum().alias("n_dias_com_venda"),
            pl.col("on_promo").fill_null(False).mean().alias("prop_promo"),
        )
        .with_columns((pl.col("n_dias_com_venda") / pl.col("n_dias_na_fatia")).alias("densidade"))
        .sort("item_id")
        .collect(engine="streaming")
    )


def _exclude_promo_dominated(density: pl.DataFrame, *, promo_days_max_share: float) -> pl.DataFrame:
    """Remove item cujo `prop_promo` (fração de dias em promoção na fatia D3) >= piso (D6).

    Item que só vende sob promoção não é demanda regular de prateleira -- é
    demanda de campanha (Fase A, M6).
    """
    return density.filter(pl.col("prop_promo") < promo_days_max_share)


def _exclude_degenerate_families(
    candidates: pl.DataFrame, items: pl.DataFrame, *, family_min_items: int
) -> tuple[pl.DataFrame, str]:
    """Remove família inteira com menos de `family_min_items` itens no pool regular (D6).

    A exclusão é da FAMÍLIA inteira, não só do item mais fraco dela: manter
    1-2 itens soltos não resolve o problema que motivou a exclusão --
    fornecedor de 1-2 itens degenera a regra de pedido mínimo (Fase A, M5).
    Devolve também a frase de motivo, com as famílias excluídas e suas
    contagens, para registrar no funil sem esconder o critério (D6 ⚠️).
    """
    with_family = candidates.join(
        items.select("item_id", "category", "supplier_id"), on="item_id", how="left"
    )
    family_counts = with_family.group_by("supplier_id").agg(pl.len().alias("n_familia"))
    degenerate = family_counts.filter(pl.col("n_familia") < family_min_items).sort("supplier_id")

    kept = with_family.join(degenerate.select("supplier_id"), on="supplier_id", how="anti")

    if degenerate.height == 0:
        motivo = f"nenhuma família abaixo do piso de {family_min_items} itens"
    else:
        detalhes = ", ".join(
            f"{row['supplier_id']}({row['n_familia']})"
            for row in degenerate.sort("supplier_id").iter_rows(named=True)
        )
        motivo = (
            f"família com menos de {family_min_items} itens no pool regular "
            f"excluída inteira: {detalhes}"
        )
    return kept, motivo


def _cap_by_family(candidates: pl.DataFrame, *, family_cap: int) -> pl.DataFrame:
    """Cap por família (D5), com ordem final determinística (D7).

    Dentro da família: `(densidade desc, item_id asc)`. Entre famílias: a
    contagem usada para ordenar é a do pool ANTES do cap (`n_familia`) --
    `(contagem_familia asc, supplier_id asc)`. O resultado sai construído por
    `sort` explícito nessas colunas, nunca pela ordem de iteração de um
    `group_by` (que pode variar entre execuções/versões do polars) --
    `test_determinismo_do_cap_por_familia` prova isso com um empate
    construído à mão.
    """
    family_counts = candidates.group_by("supplier_id").agg(pl.len().alias("n_familia"))
    ranked = (
        candidates.join(family_counts, on="supplier_id")
        .sort(["supplier_id", "densidade", "item_id"], descending=[False, True, False])
        .with_columns(pl.int_range(0, pl.len()).over("supplier_id").alias("_rank_na_familia"))
    )
    capped = ranked.filter(pl.col("_rank_na_familia") < family_cap)
    return capped.sort(
        ["n_familia", "supplier_id", "densidade", "item_id"],
        descending=[False, False, True, False],
    )


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------


def _assert_no_leakage(params: Params) -> None:
    """A fatia de densidade (D3) tem que terminar estritamente antes do loop do simulador.

    Barreira de runtime, não só de convenção -- ver `LeakageGuardError`.
    """
    density_end = params.subset_selection.density_window_end
    sim_start = params.simulation.start_date
    if density_end >= sim_start:
        raise LeakageGuardError(
            f"subset_selection.density_window_end ({density_end}) precisa ser "
            f"estritamente anterior a simulation.start_date ({sim_start}) -- "
            "senão a seleção de itens vaza para dentro do período avaliado (D3)."
        )


def select_subset(
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    stock: pl.DataFrame,
    params: Params,
) -> SubsetSelectionResult:
    """Seleciona a loja e os itens do subconjunto de trabalho (Sprint 4, D1-D8).

    Função pura: não lê disco, não tem estado global, não imprime nada -- o
    funil é o `DataFrame` devolvido em `SubsetSelectionResult.funnel`, não um
    print (enunciado da Sprint 4, "Funil obrigatório").

    `sales` é `pl.LazyFrame` (a tabela real tem ~108M linhas -- ver
    convenção de `motor.profiling`); `items`/`suppliers`/`stock` são
    `pl.DataFrame` (pequenas o bastante para já estarem materializadas).
    `suppliers` e `stock` entram na assinatura porque a função recebe as
    quatro tabelas canônicas por contrato (CLAUDE.md, seção 4) -- não são
    usadas aqui: `stock` está vazio no Favorita, e a granularidade de
    fornecedor já está em `items.supplier_id`.

    A loja (D1) e todos os cortes (D2-D8) vêm de `params.subset_selection` --
    a função nunca aceita um argumento separado para eles, para que a fatia
    de medição de densidade não vire um parâmetro que alguém troca pelo
    período de simulação (ver docstring do módulo).
    """
    del suppliers, stock  # recebidos pelo contrato das 4 tabelas canônicas; não usados aqui
    _assert_no_leakage(params)

    cfg = params.subset_selection
    store_id = cfg.store_id
    window_start = params.canonical.window_start
    window_end = params.canonical.window_end

    funnel_rows: list[dict[str, object]] = []

    n_universo = items.select("item_id").unique().height
    stage1 = _pairs_for_store(sales, store_id=store_id)
    funnel_rows.append(
        _funnel_row(
            "pares_loja",
            n_universo,
            stage1.height,
            f"item_id com ao menos 1 linha na loja {store_id} (D1)",
        )
    )

    stage2 = _lifespan_complete(
        sales, store_id=store_id, window_start=window_start, window_end=window_end
    )
    funnel_rows.append(
        _funnel_row(
            "lifespan_completo",
            stage1.height,
            stage2.height,
            f"lifespan cobre {window_start}..{window_end} por inteiro (D2)",
        )
    )

    density_all = _density_by_item(
        sales,
        store_id=store_id,
        density_window_start=cfg.density_window_start,
        density_window_end=cfg.density_window_end,
    )
    density_stage2 = density_all.join(stage2, on="item_id", how="semi")
    stage3 = density_stage2.filter(pl.col("densidade") >= cfg.density_threshold)
    funnel_rows.append(
        _funnel_row(
            "densidade_minima",
            stage2.height,
            stage3.height,
            f"densidade >= {cfg.density_threshold} em "
            f"{cfg.density_window_start}..{cfg.density_window_end} (D3)",
        )
    )

    stage4 = _exclude_promo_dominated(stage3, promo_days_max_share=cfg.promo_days_max_share)
    funnel_rows.append(
        _funnel_row(
            "exclusao_promocao",
            stage3.height,
            stage4.height,
            f"prop_promo >= {cfg.promo_days_max_share} nos dias da fatia D3 (D6)",
        )
    )

    stage5, motivo_familia = _exclude_degenerate_families(
        stage4, items, family_min_items=cfg.family_min_items
    )
    funnel_rows.append(
        _funnel_row("familia_degenerada", stage4.height, stage5.height, motivo_familia)
    )

    stage6 = _cap_by_family(stage5, family_cap=cfg.family_cap)
    funnel_rows.append(
        _funnel_row(
            "cap_por_familia",
            stage5.height,
            stage6.height,
            f"cap fixo de {cfg.family_cap} itens por família, desempate "
            "(densidade desc, item_id asc) (D5/D7)",
        )
    )

    funnel_rows.append(
        _funnel_row(
            "final",
            stage6.height,
            stage6.height,
            f"subconjunto final: {stage6.height} itens na loja {store_id}",
        )
    )

    funnel = pl.DataFrame(funnel_rows, schema=_FUNNEL_SCHEMA)
    item_ids = tuple(stage6["item_id"].to_list())

    return SubsetSelectionResult(store_id=store_id, item_ids=item_ids, funnel=funnel)
