"""Matriz de features do braço 3 (Sprint 14): histórico, atributos do item e
calendário, para uma data de decisão `as_of` -- sem alvo, sem modelo (Sprint 15).

GRÃO TEMPORAL -- a regra que ordena o módulo inteiro (CLAUDE.md, seção 8):

- Calendário (`weekday`, `is_holiday_*`, `is_month_start`, `quinzena`,
  `days_to_payday`) descreve o PRÓPRIO `as_of` -- não é vazamento, é
  calendário público, sempre conhecido de antemão.
- Histórico e promoção (lags, médias/somas móveis, proporções, `days_since_*`)
  só podem usar `date < as_of` -- nunca o próprio dia da decisão, nem mesmo
  para saber se HOJE está em promoção (o dataset não tem calendário
  promocional futuro; usar `on_promo` de `as_of` em diante seria fingir um
  dado que não existe -- mesmo problema já registrado na Sprint 13, regra de
  guarda "promoção prevista").

BURACO DE CALENDÁRIO -- `sales` (canônico, `motor.io.loaders.load_sales`) é
denso DENTRO do lifespan de cada par loja-item (todo dia entre `entry_date` e
`exit_date` tem uma linha, zero-fill), mas AUSENTE fora dele -- um item
introduzido no meio da janela não tem nenhuma linha antes da própria entrada.
Isso é o que faz as agregações por `item_id` (`.group_by("item_id")`, nunca
uma janela de linhas por posição) devolverem `null` de forma correta nessa
borda, sem precisar reconstruir um calendário artificial aqui: a ausência de
linha já É a resposta certa.

JANELAS COM MENOS DIAS DO QUE O NOMINAL -- quando o item só tem N < window_days
dias de vida dentro da janela, toda métrica é calculada sobre os N dias REAIS
presentes (nunca sobre `window_days` fixo): `share_days_with_sale_Nd`,
`promo_share_Nd` e `promo_known_share_Nd` dividem pelo número de linhas
REALMENTE presentes na janela, não por `window_days`. Um dia antes da entrada
do item não é "zero dias com venda" -- é "não sei", e não deveria puxar a
proporção para baixo por um motivo que não tem nada a ver com o
comportamento do item. Quando não há NENHUMA linha na janela, o resultado é
`null`, não `0/0`.

`promo_share_Nd` trata `on_promo` nulo (linha de reindex sem registro bruto
naquele dia) como `False` -- decisão registrada, não escondida: medido antes
de implementar (loja 44, período de simulação), 100% das linhas com
`on_promo` nulo têm `units_sold == 0`, então tratar como "sem promoção" não
inventa nenhuma venda que não existiu. Só que "sem promoção" e "não sei se
tinha promoção" não são a mesma coisa -- por isso toda janela de
`promo_share_Nd` tem uma companheira `promo_known_share_Nd` (MESMA janela,
sempre pareada): a fração de dias, dentro da janela, com status de promoção
conhecido. Ela domina em informação a alternativa óbvia (excluir os dias
nulos do denominador de `promo_share`): o modelo pode reconstruir sozinho a
taxa condicional (`promo_share/promo_known_share`) quando quiser, e o caso
degenerado -- nenhum dia com status conhecido -- vira `promo_known_share=0`,
um sinal aprendível, em vez de um nulo ou uma divisão por zero. Também
medido antes de implementar: `promo_known_share` NÃO é redundante com
`share_days_with_sale` -- existem linhas de venda zero com `on_promo`
conhecido (143 de 251.211 na loja 44, período de simulação), então a folga é
pequena mas real.

`days_since_last_promo` tem o mesmo problema de fundo que `promo_share`, sem
companheira dedicada: se o último dia de promoção real caiu num dia de
status desconhecido, a feature aponta para um dia anterior real e
SUPERESTIMA a distância -- na mesma direção, pelos mesmos itens
intermitentes. Decisão explícita (documentada, não corrigida nesta sprint):
esta feature só é confiável onde `promo_known_share_Nd` (a janela mais curta
disponível) é alto; onde não é, o modelo já tem o sinal para descontá-la.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import polars as pl

from motor.config import FeaturesParams
from motor.features.calendar import StoreLocale, build_calendar_features


def _target_item_ids(items: pl.DataFrame, item_ids: Sequence[str] | None) -> list[str]:
    if item_ids is not None:
        return list(dict.fromkeys(item_ids))
    return items["item_id"].unique(maintain_order=True).to_list()


def _lag_feature(history: pl.DataFrame, as_of: date, lag_days: int) -> pl.DataFrame:
    lag_date = as_of - timedelta(days=lag_days)
    return history.filter(pl.col("date") == lag_date).select(
        "item_id", pl.col("units_sold").alias(f"lag_units_{lag_days}")
    )


def _window_features(history: pl.DataFrame, as_of: date, window_days: int) -> pl.DataFrame:
    """As cinco métricas de uma janela `[as_of - window_days, as_of)`, uma
    linha por `item_id` -- item sem NENHUMA linha na janela simplesmente não
    aparece (o `left join` de quem chama produz `null`, não `0`). Todo
    denominador é `n_rows` (linhas realmente presentes), nunca `window_days`
    -- ver docstring do módulo."""
    window_start = as_of - timedelta(days=window_days)
    window_slice = history.filter((pl.col("date") >= window_start) & (pl.col("date") < as_of))

    agg = window_slice.group_by("item_id").agg(
        pl.len().alias("n_rows"),
        pl.col("units_sold").mean().alias("mean_units"),
        pl.col("units_sold").sum().alias("sum_units"),
        (pl.col("units_sold") > 0).sum().alias("n_sale_days"),
        pl.col("on_promo").fill_null(False).sum().alias("n_promo_true"),
        pl.col("on_promo").is_not_null().sum().alias("n_promo_known"),
    )
    w = window_days
    return agg.select(
        "item_id",
        pl.col("mean_units").alias(f"rolling_mean_units_{w}d"),
        pl.col("sum_units").alias(f"rolling_sum_units_{w}d"),
        (pl.col("n_sale_days") / pl.col("n_rows")).alias(f"share_days_with_sale_{w}d"),
        (pl.col("n_promo_true") / pl.col("n_rows")).alias(f"promo_share_{w}d"),
        (pl.col("n_promo_known") / pl.col("n_rows")).alias(f"promo_known_share_{w}d"),
    )


def _days_since_last_sale(history: pl.DataFrame, as_of: date) -> pl.DataFrame:
    last_sale = (
        history.filter(pl.col("units_sold") > 0)
        .group_by("item_id")
        .agg(pl.col("date").max().alias("last_sale_date"))
    )
    return last_sale.select(
        "item_id",
        (pl.lit(as_of) - pl.col("last_sale_date")).dt.total_days().alias("days_since_last_sale"),
    )


def _days_since_last_promo(history: pl.DataFrame, as_of: date) -> pl.DataFrame:
    """`on_promo` nulo tratado como "sem promoção" -- mesma decisão de
    `_window_features`, mesma limitação registrada na docstring do módulo."""
    last_promo = (
        history.filter(pl.col("on_promo").fill_null(False))
        .group_by("item_id")
        .agg(pl.col("date").max().alias("last_promo_date"))
    )
    return last_promo.select(
        "item_id",
        (pl.lit(as_of) - pl.col("last_promo_date")).dt.total_days().alias("days_since_last_promo"),
    )


def _select_active_columns(frame: pl.DataFrame, active_features: Sequence[str]) -> pl.DataFrame:
    disponiveis = set(frame.columns)
    desconhecidas = [c for c in active_features if c not in disponiveis]
    if desconhecidas:
        msg = (
            f"features.active_features contém coluna(s) que build_features não calcula: "
            f"{desconhecidas} -- colunas disponíveis: {sorted(disponiveis)}"
        )
        raise ValueError(msg)
    return frame.select("store_id", "item_id", "as_of", *active_features)


def build_features(
    sales: pl.DataFrame,
    items: pl.DataFrame,
    as_of: date,
    *,
    store_id: str,
    calendar: pl.DataFrame,
    params: FeaturesParams,
    item_ids: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Uma linha por item elegível (`item_ids`, ou todo item de `items` se
    omitido), com as colunas de `params.active_features`.

    `sales`: canônico, qualquer recorte que cubra `date < as_of` para os
    itens pedidos -- este módulo não sabe nem precisa saber se veio do
    parquet inteiro ou de uma fatia; a filtragem por `store_id`/`date` é
    feita aqui dentro, sempre. `stock` NÃO é parâmetro desta função: o
    Favorita não tem estoque real, e estimar demanda censurada sem esse
    dado seria inventar -- fora de escopo desta sprint (nenhum modelo,
    nenhuma alteração). Quando houver estoque real de cliente, a assinatura
    ganha o parâmetro de volta, consumido por uma feature nova, não antes.

    `calendar`: saída de `build_calendar_features` para `[as_of]` -- exatamente
    1 linha, cuja `date` precisa bater com `as_of` (conferido, erro claro se
    não bater). Item sem nenhuma linha em `sales` antes de `as_of` ainda
    ganha uma linha na saída: colunas de calendário/atributo preenchidas,
    colunas de histórico `null` -- não removida (ver docstring do módulo).
    """
    if calendar.height != 1:
        msg = f"`calendar` deve ter exatamente 1 linha (a de `as_of`); recebeu {calendar.height}"
        raise ValueError(msg)
    calendar_date = calendar["date"][0]
    if calendar_date != as_of:
        msg = f"`calendar` é da data {calendar_date!r}, não bate com as_of={as_of!r}"
        raise ValueError(msg)

    target_ids = _target_item_ids(items, item_ids)
    result = pl.DataFrame({"item_id": target_ids})

    history = sales.filter((pl.col("store_id") == store_id) & (pl.col("date") < as_of))

    for lag in params.historico.lag_days:
        result = result.join(_lag_feature(history, as_of, lag), on="item_id", how="left")

    all_windows = sorted(
        set(params.historico.rolling_windows_days) | {params.historico.risk_window_reference_days}
    )
    for window_days in all_windows:
        result = result.join(
            _window_features(history, as_of, window_days), on="item_id", how="left"
        )

    result = result.join(_days_since_last_sale(history, as_of), on="item_id", how="left")
    result = result.join(_days_since_last_promo(history, as_of), on="item_id", how="left")

    attrs = items.select("item_id", "category", "item_class", "is_perishable").unique(
        subset="item_id"
    )
    result = result.join(attrs, on="item_id", how="left")

    calendar_for_join = calendar.select(pl.col("date").alias("as_of"), pl.exclude("date"))
    result = result.with_columns(pl.lit(as_of).alias("as_of"))
    result = result.join(calendar_for_join, on="as_of", how="left")
    result = result.with_columns(pl.lit(store_id).alias("store_id"))

    return _select_active_columns(result, params.active_features)


def build_training_matrix(
    sales: pl.DataFrame,
    items: pl.DataFrame,
    as_of_dates: Sequence[date],
    *,
    store_id: str,
    locale: StoreLocale,
    holidays: pl.DataFrame,
    params: FeaturesParams,
    item_ids: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Empilha `build_features` para cada `as_of` em `as_of_dates`, sem alvo
    (o alvo -- demanda acumulada futura -- é Sprint 15).

    Implementado como um LOOP simples sobre `build_features`, de propósito,
    não vetorizado: cada chamada já filtra `sales` por `date < as_of`
    internamente e de forma independente, então a corretude da matriz
    inteira se reduz à corretude de `build_features` (testada à parte,
    `tests/test_features_build.py`) -- nenhuma data da lista pode enxergar
    dado de outra. Performance não é gargalo nesta sprint (poucas dezenas de
    `as_of` x ~275 itens do subconjunto de trabalho) -- CLAUDE.md, seção 10:
    não otimizar antes do resultado estar correto.
    """
    frames = []
    for as_of in as_of_dates:
        calendar = build_calendar_features(
            [as_of], locale=locale, holidays=holidays, params=params.calendar
        )
        frames.append(
            build_features(
                sales,
                items,
                as_of,
                store_id=store_id,
                calendar=calendar,
                params=params,
                item_ids=item_ids,
            )
        )
    return pl.concat(frames)
