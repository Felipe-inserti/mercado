"""Conversão de eventos do simulador para R$ (Sprint 8).

Puro: sem I/O, sem `pathlib`, sem `motor.config.Params` -- recebe os eventos
já produzidos pelo `Simulator` (Sprint 6/7) e as premissas econômicas já
resolvidas como valores simples (dict, float), exatamente como
`motor.experiments.shared` recebe premissas de simulação em vez de `Params`
inteiro.

PREÇO ÚNICO E A PROVA DE INVARIÂNCIA
-------------------------------------
O Favorita não tem preço em nenhuma linha do bruto (nem `Sale.price`, nem
`Item.cost`/`Item.price_ref` -- todos nulos no canônico). Margem percentual
sozinha não converte pra R$: falta uma âncora absoluta. A premissa desta
sprint é `economics.uniform_unit_price` -- um preço único (R$10,00) aplicado
a TODO item, com `cost_i = price x (1 - margin_pct_i)`.

Prova de que a escala de `price` não importa pra quem ganha a comparação
entre braços (só pro tamanho dos R$ absolutos reportados): com `price`
uniforme entre itens,

    margem_realizada_rs = sum(sold_i x price x margin_pct_i)
                        = price x sum(sold_i x margin_pct_i)
    capital_medio_rs    = mean_dia(sum(on_hand_i x price x (1 - margin_pct_i)))
                        = price x mean_dia(sum(on_hand_i x (1 - margin_pct_i)))
    giro_anualizado     = sum(sold_i x cost_i) / capital_medio_rs x (365/N)
                        = price x sum(sold_i x (1-margin_pct_i)) / (price x ...) x (365/N)

`price` é fator comum em numerador e denominador de `decision_metric`
(`(margem_realizada_rs - perda_rs) / capital_medio_rs`) e de `giro_anualizado`
-- cancela algebricamente. Os dois SÓ dependem de `margin_pct` por item e das
quantidades reais (sold, on_hand, unmet_demand, expired) -- nunca da escala
de `price`. `margem_realizada_rs` e `capital_medio_rs`, isolados, NÃO têm
esse cancelamento: escalam linearmente com `price`. Por isso:

    `margem_realizada_rs` e `capital_medio_rs` em R$ absolutos são de ESCALA
    ARBITRÁRIA -- não devem ser lidos como valor monetário real; só as
    razões (`decision_metric`, `giro_anualizado`) têm significado
    comparativo entre braços.

Checagem adicional de escala usada nos testes: no cenário de regime
permanente da Sprint 6 (demanda constante, ruptura zero), `giro_anualizado`
fecha em `730 / (review_period_days + 1)` -- fórmula fechada independente de
`daily_demand`, `price` e `cost`. Se essa independência quebrar, alguma conta
de escala está errada.

LIMITAÇÕES (MVP -- não detalhe de implementação)
-------------------------------------------------
1. Com `price` uniforme, a única diferenciação econômica entre itens é
   `margin_pct`. Neutro para a ordenação AGREGADA entre braços (prova
   acima), mas distorce qualquer regra que ordene ITENS ENTRE SI por valor
   -- notadamente a restrição de caixa da Sprint 13 (prioriza por margem
   sobre capital investido): com preço uniforme, essa priorização degenera
   em priorizar por `margin_pct` puro, como se dois itens de mesma margem %
   tivessem o mesmo ticket unitário na vida real. Some a isso as vendas
   fracionárias em kg (`unit_of_sale='kg'`): uma unidade de item vendido por
   peso (1kg de carne) passa a valer, nas métricas, o mesmo que uma unidade
   de item vendido por peça (1 lata de refrigerante) -- mesmo preço unitário
   arbitrado, grandezas físicas diferentes. Resolver isso exige preço real
   (ou ao menos por categoria) -- fora de escopo deste MVP. Revisar na
   Sprint 13.
2. A faixa <8% do documento de negócio descreve itens ÂNCORA com margem
   deliberadamente comprimida (arroz, leite, açúcar, refrigerante). Sem
   marcação de âncora (`Item.is_anchor` é 100% nulo no canônico -- Sprint 3
   decidiu não inventar um proxy que atribuiria significado de negócio que o
   dado não carrega), esses itens recebem a margem CHEIA da categoria (ex.
   18% em GROCERY). Neutro entre braços -- todos usam a mesma tabela -- mas
   infla a margem absoluta de itens que na prática quase não têm. Revisar na
   Sprint 13, quando `is_anchor` tiver consumidor real.
3. `perda_rs` existe como métrica (fórmula abaixo) mas é IDENTICAMENTE ZERO
   em qualquer rodada desta sprint: `shelf_life_from_arrival_days=None` para
   todo item (premissa da Sprint 7) faz `expired` ser sempre 0.0 em todo
   `DailyEvent`, mesmo para os itens marcados `is_perishable=True` no
   canônico (53% do subconjunto real). Não é ausência da métrica -- é a
   métrica presente, zerada por essa premissa. Existe para a Sprint 12/15
   comparar contra quando shelf life real entrar.

FÓRMULAS (sobre os eventos, já filtrados por `evaluation_start` -- warmup
descartado antes de qualquer leitura, CLAUDE.md seção 6)
----------------------------------------------------------------------------
    margem_dia   = sold x (price - cost)
    ruptura_dia  = unmet_demand x (price - cost)   -- unmet_demand é campo do
                   DailyEvent (Sprint 6); sold + unmet_demand == demand é
                   invariante já testado, não precisa ser recalculado aqui
    perda_dia    = expired x cost
    capital_dia  = on_hand_end x cost              -- mesmo campo que a Sprint 6
                   usa pra provar d x (R+1)/2 em regime permanente
                   (test_regime_permanente_*); usar on_hand_start aqui daria
                   um número diferente e inconsistente com esse resultado
    cogs_dia     = sold x cost

    margem_realizada_rs = sum(margem_dia)
    ruptura_rs          = sum(ruptura_dia)
    perda_rs            = sum(perda_dia)
    capital_medio_rs    = mean(capital_dia)                 -- por item, sobre os dias
    nivel_servico       = sum(sold) / sum(demand)            -- por unidade, não por ciclo
    giro_anualizado     = sum(cogs_dia) / capital_medio_rs x (365 / n_dias)
    carrying_cost_rs    = capital_medio_rs x n_dias x (capital_cost_annual / 365)
                          -- diagnóstico, NÃO entra em decision_metric
    decision_metric     = (margem_realizada_rs - perda_rs) / capital_medio_rs
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final

import polars as pl

DAYS_PER_YEAR = 365

PRICE_INVARIANCE_NOTE: Final[str] = (
    "decision_metric e giro_anualizado são invariantes à escala de "
    "uniform_unit_price -- prova algébrica na docstring deste módulo. Só "
    "dependem de margin_pct por item e das quantidades reais (sold, on_hand, "
    "unmet_demand, expired), nunca da escala de price."
)

SCALE_WARNING: Final[str] = (
    "margem_realizada_rs e capital_medio_rs em R$ absolutos são de ESCALA "
    "ARBITRÁRIA -- não devem ser lidos como valor monetário real; só as "
    "razões (decision_metric, giro_anualizado) têm significado comparativo "
    "entre braços."
)

LIMITATIONS: Final[tuple[str, ...]] = (
    "Com price uniforme, a única diferenciação econômica entre itens é "
    "margin_pct. Neutro para a ordenação agregada entre braços, mas distorce "
    "qualquer regra que ordene itens entre si por valor -- notadamente a "
    "restrição de caixa da Sprint 13 (prioriza por margem sobre capital "
    "investido), que degenera em priorizar por margin_pct puro. Some a isso "
    "as vendas fracionárias em kg (unit_of_sale='kg'): uma unidade de item "
    "vendido por peso vale, nas métricas, o mesmo que uma unidade de item "
    "vendido por peça -- mesmo preço unitário arbitrado, grandezas físicas "
    "diferentes. Resolver isso exige preço real (ou por categoria); fora de "
    "escopo deste MVP, revisar na Sprint 13.",
    "A faixa <8% do documento de negócio descreve itens ÂNCORA com margem "
    "deliberadamente comprimida (arroz, leite, açúcar, refrigerante). Sem "
    "marcação de âncora (Item.is_anchor é 100% nulo no canônico -- Sprint 3 "
    "decidiu não inventar um proxy que atribuiria significado de negócio que "
    "o dado não carrega), esses itens recebem a margem cheia da categoria "
    "(ex. 18% em GROCERY). Neutro entre braços -- todos usam a mesma tabela "
    "-- mas infla a margem absoluta de itens que na prática quase não têm. "
    "Revisar na Sprint 13, quando is_anchor tiver consumidor real.",
    "perda_rs existe como métrica mas é identicamente zero em qualquer "
    "rodada desta sprint: shelf_life_from_arrival_days=None para todo item "
    "(premissa da Sprint 7) faz expired ser sempre 0.0 em todo DailyEvent, "
    "mesmo para os itens marcados is_perishable=True no canônico (53% do "
    "subconjunto real). Não é ausência da métrica -- é a métrica presente, "
    "zerada por essa premissa. Existe para a Sprint 12/15 comparar contra "
    "quando shelf life real entrar.",
)


@dataclass(frozen=True)
class ItemEconomics:
    """Preço, custo e margem arbitrados de um item -- ver docstring do módulo
    para a prova de que a escala de `price` não afeta `decision_metric`/`giro_anualizado`."""

    item_id: str
    price: float
    cost: float
    margin_pct: float


@dataclass(frozen=True)
class ItemFinancialMetrics:
    """Métricas financeiras de um item, agregadas sobre o período pós-warmup."""

    item_id: str
    margem_realizada_rs: float
    ruptura_rs: float
    perda_rs: float
    capital_medio_rs: float
    nivel_servico: float
    giro_anualizado: float
    carrying_cost_rs: float
    decision_metric: float


@dataclass(frozen=True)
class PortfolioFinancialMetrics:
    """Mesmas métricas de `ItemFinancialMetrics`, agregadas sobre TODOS os
    itens -- calculadas direto dos eventos com preço (nunca como média das
    métricas por item: `nivel_servico` e `giro_anualizado` são razões de
    somas, não somas/médias de razões).
    """

    margem_realizada_rs: float
    ruptura_rs: float
    perda_rs: float
    capital_medio_rs: float
    nivel_servico: float
    giro_anualizado: float
    carrying_cost_rs: float
    decision_metric: float


class MissingItemEconomicsError(ValueError):
    """Algum `item_id` dos eventos não tem linha correspondente em `item_economics`.

    Erro alto e explícito -- um `join` silencioso deixaria `price`/`cost`
    nulos e as métricas desse item virariam `NaN` sem aviso.
    """


def build_item_economics(
    items: pl.DataFrame,
    *,
    category_margin_pct: dict[str, float],
    default_margin_pct: float,
    uniform_unit_price: float,
) -> pl.DataFrame:
    """Resolve `price`/`cost`/`margin_pct` por item a partir da categoria.

    `items` precisa só de `item_id` e `category`. Categoria sem entrada em
    `category_margin_pct` cai em `default_margin_pct` -- nunca erro, é o
    comportamento de fallback documentado (CLAUDE.md, seção 2: premissa vem
    de config, `default_margin_pct` é exatamente esse piso).

    Devolve colunas `item_id`, `price`, `cost`, `margin_pct`.
    """
    margin_table = pl.DataFrame(
        {
            "category": list(category_margin_pct.keys()),
            "margin_pct": list(category_margin_pct.values()),
        },
        schema={"category": pl.String, "margin_pct": pl.Float64},
    )
    return (
        items.select("item_id", "category")
        .join(margin_table, on="category", how="left")
        .with_columns(pl.col("margin_pct").fill_null(default_margin_pct))
        .with_columns(pl.lit(uniform_unit_price).alias("price"))
        .with_columns((pl.col("price") * (1.0 - pl.col("margin_pct"))).alias("cost"))
        .select("item_id", "price", "cost", "margin_pct")
    )


def _priced_events(
    events: pl.DataFrame, item_economics: pl.DataFrame, *, evaluation_start: date
) -> pl.DataFrame:
    """Junta `events` com `item_economics`, filtra `day >= evaluation_start`
    e calcula as colunas monetárias por item-dia (ver fórmulas na docstring
    do módulo). Função interna -- `compute_financial_metrics` e
    `compute_portfolio_metrics` agregam o resultado de formas diferentes,
    mas nenhuma recalcula o join nem as fórmulas por conta própria.
    """
    joined = events.filter(pl.col("day") >= evaluation_start).join(
        item_economics.select("item_id", "price", "cost"), on="item_id", how="left"
    )

    sem_economia = joined.filter(pl.col("price").is_null())["item_id"].unique().to_list()
    if sem_economia:
        msg = (
            f"item_economics não tem preço/custo para {len(sem_economia)} item(ns) "
            f"presentes nos eventos: {sorted(sem_economia)}"
        )
        raise MissingItemEconomicsError(msg)

    return joined.with_columns(
        (pl.col("sold") * (pl.col("price") - pl.col("cost"))).alias("margem_dia"),
        (pl.col("unmet_demand") * (pl.col("price") - pl.col("cost"))).alias("ruptura_dia"),
        (pl.col("expired") * pl.col("cost")).alias("perda_dia"),
        (pl.col("on_hand_end") * pl.col("cost")).alias("capital_dia"),
        (pl.col("sold") * pl.col("cost")).alias("cogs_dia"),
    )


def compute_financial_metrics(
    events: pl.DataFrame,
    item_economics: pl.DataFrame,
    *,
    evaluation_start: date,
    capital_cost_annual: float,
) -> pl.DataFrame:
    """Métricas financeiras por item, sobre `day >= evaluation_start`.

    `events`: colunas `item_id`, `day`, `demand`, `sold`, `unmet_demand`,
    `expired`, `on_hand_end` (saída de `motor.experiments.run`, ou os
    `DailyEvent` de um `Simulator` convertidos pra `pl.DataFrame`).
    `item_economics`: saída de `build_item_economics` (colunas `item_id`,
    `price`, `cost`).

    Devolve `pl.DataFrame` com uma linha por `item_id` e as colunas de
    `ItemFinancialMetrics`.
    """
    daily_rate = capital_cost_annual / DAYS_PER_YEAR
    priced = _priced_events(events, item_economics, evaluation_start=evaluation_start)

    return (
        priced.group_by("item_id", maintain_order=True)
        .agg(
            pl.col("margem_dia").sum().alias("margem_realizada_rs"),
            pl.col("ruptura_dia").sum().alias("ruptura_rs"),
            pl.col("perda_dia").sum().alias("perda_rs"),
            pl.col("capital_dia").mean().alias("capital_medio_rs"),
            pl.col("cogs_dia").sum().alias("cogs_rs"),
            pl.col("sold").sum().alias("sold_total"),
            pl.col("demand").sum().alias("demand_total"),
            pl.len().alias("n_dias"),
        )
        .with_columns(
            (pl.col("sold_total") / pl.col("demand_total")).alias("nivel_servico"),
            (
                pl.col("cogs_rs") / pl.col("capital_medio_rs") * (DAYS_PER_YEAR / pl.col("n_dias"))
            ).alias("giro_anualizado"),
            (pl.col("capital_medio_rs") * pl.col("n_dias") * daily_rate).alias("carrying_cost_rs"),
            (
                (pl.col("margem_realizada_rs") - pl.col("perda_rs")) / pl.col("capital_medio_rs")
            ).alias("decision_metric"),
        )
        .select(
            "item_id",
            "margem_realizada_rs",
            "ruptura_rs",
            "perda_rs",
            "capital_medio_rs",
            "nivel_servico",
            "giro_anualizado",
            "carrying_cost_rs",
            "decision_metric",
        )
    )


def compute_portfolio_metrics(
    events: pl.DataFrame,
    item_economics: pl.DataFrame,
    *,
    evaluation_start: date,
    capital_cost_annual: float,
) -> PortfolioFinancialMetrics:
    """Mesmas métricas, agregadas sobre TODOS os itens.

    `nivel_servico` e `giro_anualizado` são recalculados das somas brutas
    (nunca como média das métricas por item -- razão de somas não é soma de
    razões) e `capital_medio_rs` soma `capital_dia` por dia ANTES de tirar a
    média entre dias, não depois.
    """
    daily_rate = capital_cost_annual / DAYS_PER_YEAR
    priced = _priced_events(events, item_economics, evaluation_start=evaluation_start)

    capital_por_dia = priced.group_by("day").agg(pl.col("capital_dia").sum().alias("capital_dia"))
    capital_medio_rs = float(capital_por_dia["capital_dia"].mean())  # type: ignore[arg-type]
    n_dias = capital_por_dia.height

    margem_realizada_rs = float(priced["margem_dia"].sum())
    ruptura_rs = float(priced["ruptura_dia"].sum())
    perda_rs = float(priced["perda_dia"].sum())
    cogs_rs = float(priced["cogs_dia"].sum())
    sold_total = float(priced["sold"].sum())
    demand_total = float(priced["demand"].sum())

    nivel_servico = sold_total / demand_total
    giro_anualizado = cogs_rs / capital_medio_rs * (DAYS_PER_YEAR / n_dias)
    carrying_cost_rs = capital_medio_rs * n_dias * daily_rate
    decision_metric = (margem_realizada_rs - perda_rs) / capital_medio_rs

    return PortfolioFinancialMetrics(
        margem_realizada_rs=margem_realizada_rs,
        ruptura_rs=ruptura_rs,
        perda_rs=perda_rs,
        capital_medio_rs=capital_medio_rs,
        nivel_servico=nivel_servico,
        giro_anualizado=giro_anualizado,
        carrying_cost_rs=carrying_cost_rs,
        decision_metric=decision_metric,
    )
