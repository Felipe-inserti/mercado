"""Sprint 3: do parquet bruto do Favorita para as quatro tabelas canônicas.

`loaders.py` é a ÚNICA fronteira de nomes do projeto (CLAUDE.md, seção 4):
aqui, e só aqui, `store_nbr` vira `store_id`, `unit_sales` vira `units_sold`
etc. Acima desta camada, nenhum outro módulo sabe que o Favorita existe -- é
isso que torna o motor portável para o ERP de um cliente real sem reescrever
nada além deste arquivo.

As nove decisões de desenho (D1-D9) da Fase A desta sprint estão documentadas
função a função abaixo, e a decisão em si (valor, threshold) vive em
`config/params.yaml`, nunca hardcoded aqui (CLAUDE.md, seção 2).

Sem agregado global, por construção. `load_sales` e `load_items` recebem a
fatia de `sales_raw` que quem chama decidiu passar -- em produção
(`build_canonical_favorita`), a fatia restrita à janela de trabalho. Nenhuma
das duas filtra por janela sozinha: filtrar antes de entregar, nunca confiar
em quem recebe (CLAUDE.md, seção 6). A única exceção deliberada é
`_pair_lifespan_bounds`, que olha para o histórico IRRESTRITO só para achar
duas datas-limite (abertura da loja, primeira venda do par) -- um mínimo
estrutural, não uma média/encoding sensível a volume; ver a docstring da
função para o argumento completo.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import polars as pl
from pydantic import BaseModel, ConfigDict

from motor.config import AnomalyPeriodParams, Params, SupplierAssumptionsParams
from motor.io.contracts import (
    ITEMS_PRIMARY_KEY,
    SALES_PRIMARY_KEY,
    STOCK_PRIMARY_KEY,
    SUPPLIERS_PRIMARY_KEY,
    Item,
    SchemaValidationError,
    Stock,
    Supplier,
    UnitOfSale,
    Violation,
    expected_polars_schema,
    validate_referential_integrity,
    validate_supplier_order_cadence,
    validate_table,
)
from motor.io.raw import scan_raw
from motor.profiling import profile_fractional_by_item, profile_store_lifespan

_CANONICAL_TABLES: Final = ("sales", "items", "suppliers", "stock")
CANONICAL_SCHEMA_VERSION: Final = 1

# Campos de `Sale` que a checagem streaming de `sales` (`_validate_sales_streaming`)
# exige não-nulos: os obrigatórios do contrato (sem `| None`) mais `units_returned`,
# promovido via decomposição do líquido diário (D4) -- mesmo conjunto que
# `required_non_null={"units_returned"}` produziria em `validate_table`.
_SALES_REQUIRED_NON_NULL: Final = (
    "store_id",
    "item_id",
    "date",
    "units_sold",
    "units_returned",
    "is_operating_day",
    "is_anomaly",
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------
# Manifesto
# --------------------------------------------------------------------------


class InputFileManifest(BaseModel):
    """Impressão digital de um parquet bruto consumido pelo build: hash e tamanho."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str
    size_bytes: int


class OutputFileManifest(BaseModel):
    """Tamanho de um parquet canônico gerado pelo build."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    size_bytes: int


class CanonicalManifest(BaseModel):
    """Manifesto autossuficiente de uma execução de `build_canonical_favorita`.

    Grava tudo que se precisa saber, daqui a três sprints, sobre com que
    código e que parâmetros um parquet canônico nasceu -- mesmo requisito não
    negociável da Sprint 9, antecipado aqui (Fase B desta sprint).

    `generated_at` e `execution_seconds` são os dois únicos campos que variam
    entre duas execuções com o mesmo código, parâmetros e entrada -- não
    fazem parte da checagem de idempotência "byte a byte" dos quatro parquets
    de dado (condição de pronto da Fase B); todo o resto do manifesto sim.

    `params_hash` é o hash do `Params` ATIVO na chamada (`model_dump_json()`),
    não do arquivo `config/params.yaml` lido byte a byte: `build_canonical_favorita`
    recebe um `Params` já carregado (assinatura aprovada na Fase A), não um
    caminho de arquivo, e hashear os valores em vigor é mais robusto a
    comentário/formatação irrelevantes do yaml do que hashear o arquivo em
    si. `active_params` carrega os valores por extenso, escopados a
    `canonical` e `supplier_assumptions` -- as duas seções de `Params` que
    `loaders.py` de fato lê; as demais (simulação, economia, modelo...) não
    influenciam este parquet. Decisão registrada no relatório da Fase B como
    não especificada no prompt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    generated_at: datetime
    execution_seconds: float
    window_start: date
    window_end: date
    git_commit_hash: str | None
    params_hash: str
    active_params: dict[str, Any]
    input_files: dict[str, InputFileManifest]
    row_counts: dict[str, int]
    output_files: dict[str, OutputFileManifest]


def _hash_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """sha256 de um arquivo, lido em blocos -- nunca carrega o arquivo inteiro em memória."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_hash(repo_dir: Path) -> str | None:
    """Hash do commit HEAD do código, para o manifesto (Fase B, requisito novo).

    `None` quando o diretório não é um repositório git ou o comando `git` não
    está disponível -- nunca falha a geração do canônico por causa disso.
    Esta função só LÊ o estado do git (`rev-parse HEAD`); não é um dos
    comandos git proibidos para o agente nesta sprint (esses proíbem o
    agente de alterar histórico, não o código de produção de ler o commit
    corrente).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


# --------------------------------------------------------------------------
# D8 -- slug determinístico de supplier_id
# --------------------------------------------------------------------------

_SLUG_INVALID_CHARS: Final = re.compile(r"[^A-Z0-9]+")


def _slugify_supplier_id(family: str) -> str:
    """Slug determinístico de `family` para `supplier_id` (D8).

    Maiúsculas; qualquer sequência de caracteres fora de `[A-Z0-9]` vira um
    único `_`; aparado nas pontas. Ex.: `"BREAD/BAKERY"` -> `"SUP-BREAD_BAKERY"`.
    """
    slug = _SLUG_INVALID_CHARS.sub("_", family.strip().upper()).strip("_")
    return f"SUP-{slug}"


def _build_family_to_supplier_id(families: Iterable[str]) -> dict[str, str]:
    """Mapeia cada `family` distinta a um `supplier_id`, com checagem de colisão (D8).

    `sorted(set(...))` antes de iterar: o mapeamento não pode depender da
    ordem de chegada das linhas em `items_raw`, senão duas execuções sobre o
    mesmo dado poderiam divergir -- quebraria a idempotência. Colisão (duas
    families distintas gerando o mesmo slug) é um `ValueError` imediato, não
    um caso a absorver em silêncio: é assert de cadastro, exigido
    explicitamente pela Fase B, não só coberto por teste.
    """
    supplier_id_to_family: dict[str, str] = {}
    for family in sorted(set(families)):
        supplier_id = _slugify_supplier_id(family)
        existing_family = supplier_id_to_family.get(supplier_id)
        if existing_family is not None and existing_family != family:
            msg = (
                f"colisão de supplier_id: families {existing_family!r} e {family!r} "
                f"geram o mesmo slug {supplier_id!r}"
            )
            raise ValueError(msg)
        supplier_id_to_family[supplier_id] = family
    return {family: supplier_id for supplier_id, family in supplier_id_to_family.items()}


# --------------------------------------------------------------------------
# D2 -- bordas do lifespan do par, e o reindex propriamente dito
# --------------------------------------------------------------------------


def _pair_lifespan_bounds(
    sales_raw: pl.LazyFrame,
    sales_windowed: pl.LazyFrame,
    *,
    window_start: date,
    window_end: date,
    delisting_gap_days: int,
) -> pl.LazyFrame:
    """Por par (`store_nbr`, `item_nbr`) retido: data de entrada e de saída do reindex (D2).

    Só pares com ao menos uma venda DENTRO da janela aparecem no resultado --
    os demais (nunca vendidos na janela) são excluídos aqui, antes do
    reindex.

    Entrada: `max(primeira venda do par, abertura da loja, window_start)`.
    `abertura da loja` (reusa `profile_store_lifespan`, Sprint 2) e
    `primeira venda do par` vêm de `sales_raw` IRRESTRITO (histórico
    inteiro), de propósito: são limites estruturais (um `min()` de data), não
    uma média/estatística sensível ao volume de linhas -- olhar para fora da
    janela aqui não é o vazamento que o teste 8 ("sem vazamento por agregado
    global") cobre. Ver a docstring de `load_items` para o caso em que olhar
    para fora da janela SERIA vazamento (`fractional_ratio`, um agregado de
    verdade).

    Saída: se o buraco entre a última venda do par DENTRO da janela e
    `window_end` excede `delisting_gap_days`, trunca em
    `última_venda_na_janela + delisting_gap_days` -- par descontinuado (D2),
    a cauda de zero-fill não vai até o fim da janela. Senão, `window_end` --
    par ativo, zera normalmente até o fim. A última venda usada aqui vem só
    de `sales_windowed`: olhar além de `window_end` faria a decisão de
    truncar depender de dado futuro em relação à janela -- vazamento de
    verdade, e o motivo de `sales_windowed` ser um argumento à parte.
    """
    store_open = (
        profile_store_lifespan(sales_raw)
        .select(pl.col("store_nbr"), pl.col("first_sale").alias("store_open"))
        .lazy()
    )
    pair_first_sale = sales_raw.group_by("store_nbr", "item_nbr").agg(
        pl.col("date").min().alias("pair_first_sale")
    )
    pair_last_sale_windowed = sales_windowed.group_by("store_nbr", "item_nbr").agg(
        pl.col("date").max().alias("pair_last_sale_windowed")
    )

    window_start_lit = pl.lit(window_start, dtype=pl.Date)
    window_end_lit = pl.lit(window_end, dtype=pl.Date)

    return (
        pair_last_sale_windowed.join(pair_first_sale, on=["store_nbr", "item_nbr"], how="left")
        .join(store_open, on="store_nbr", how="left")
        .with_columns(
            pl.max_horizontal(
                pl.col("pair_first_sale"), pl.col("store_open"), window_start_lit
            ).alias("entry_date"),
            (window_end_lit - pl.col("pair_last_sale_windowed"))
            .dt.total_days()
            .alias("tail_gap_days"),
        )
        .with_columns(
            pl.when(pl.col("tail_gap_days") > delisting_gap_days)
            .then(pl.col("pair_last_sale_windowed") + pl.duration(days=delisting_gap_days))
            .otherwise(window_end_lit)
            .alias("exit_date")
        )
        .select("store_nbr", "item_nbr", "entry_date", "exit_date")
    )


def _reindex_spine(bounds: pl.LazyFrame) -> pl.LazyFrame:
    """Grade diária `(store_nbr, item_nbr, date)`, de `entry_date` a `exit_date`, por par.

    Junção lazy contra um spine de datas POR PAR -- nunca um produto
    cartesiano de todos os pares por todos os dias da janela (Fase A, seção
    5: 174.685 pares x ~1.600 dias explode; por par, cada um só gera os dias
    do seu próprio lifespan).
    """
    return (
        bounds.with_columns(
            pl.date_ranges(
                pl.col("entry_date"), pl.col("exit_date"), interval="1d", closed="both"
            ).alias("date")
        )
        # `entry_date <= exit_date` sempre (ver docstring de `_pair_lifespan_bounds`), então a
        # lista nunca é vazia aqui -- `empty_as_null` explícito só para não depender do default.
        .explode("date", empty_as_null=False)
        .select("store_nbr", "item_nbr", "date")
    )


def _store_operating_days(sales_windowed: pl.LazyFrame) -> pl.LazyFrame:
    """Pares `(store_nbr, date)`, dentro da janela, em que ao menos uma linha existe no bruto (D3).

    Ausência de linha para a loja INTEIRA num dia -- não por item -- é o
    critério (ver a docstring de `Sale.is_operating_day` em
    `motor.io.contracts`); não consulta `holidays_events`, que erra para
    fechamento idiossincrático de loja (medido na Fase A: lojas com dezenas a
    mais de cem dias ausentes que não são feriado nenhum).
    """
    return sales_windowed.select("store_nbr", "date").unique()


def _apply_anomalies(sales: pl.LazyFrame, anomalies: Sequence[AnomalyPeriodParams]) -> pl.LazyFrame:
    """Marca `is_anomaly`/`anomaly_reason` (D1) sem remover nenhuma linha.

    Apagar dado em silêncio é o mesmo pecado de descartar negativo em
    silêncio (CLAUDE.md, seção 8) -- quem consumir decide se exclui. Períodos
    são checados na ordem de `anomalies`; a primeira correspondência vence se
    dois períodos se sobrepuserem (não acontece nos parâmetros atuais, só um
    período, mas o comportamento fica definido).
    """
    if not anomalies:
        return sales.with_columns(
            pl.lit(False).alias("is_anomaly"),
            pl.lit(None, dtype=pl.String).alias("anomaly_reason"),
        )

    is_anomaly_expr = pl.any_horizontal(
        [pl.col("date").is_between(a.start, a.end) for a in anomalies]
    )
    reason_expr: pl.Expr = pl.lit(None, dtype=pl.String)
    for anomaly in reversed(anomalies):
        reason_expr = (
            pl.when(pl.col("date").is_between(anomaly.start, anomaly.end))
            .then(pl.lit(anomaly.reason))
            .otherwise(reason_expr)
        )
    return sales.with_columns(
        is_anomaly_expr.alias("is_anomaly"), reason_expr.alias("anomaly_reason")
    )


def load_sales(
    sales_raw: pl.LazyFrame,
    *,
    window_start: date,
    window_end: date,
    delisting_gap_days: int,
    anomalies: Sequence[AnomalyPeriodParams],
) -> pl.LazyFrame:
    """Reindex do bruto (`train`) para a grade diária canônica de `sales`.

    LazyFrame de ponta a ponta -- quem chama decide quando materializar
    (`.sink_parquet`, o caminho de produção; ver `build_canonical_favorita`).
    `sales_raw` é o histórico IRRESTRITO (não pré-filtrado pela janela): esta
    função filtra internamente onde precisa de dado restrito à janela e usa
    o histórico inteiro só onde a Fase A pede (`_pair_lifespan_bounds`).

    `units_sold = max(0, unit_sales)`, `units_returned = -min(0, unit_sales)`
    (D4) -- decomposição do LÍQUIDO diário, não reconstrução do bruto; ver a
    docstring de `Sale` em `motor.io.contracts` para a limitação completa.
    Nas linhas criadas pelo reindex, `unit_sales` é nulo após o join: os dois
    campos saem 0.0, que é exatamente "sem venda nem devolução registrada
    neste dia dentro do lifespan do par".

    `on_promo` fica nulo tanto nas linhas do reindex quanto nas linhas brutas
    anteriores a 2014-04 (D6) -- sem tratamento especial: o join deixa nulo
    onde não há linha bruta correspondente, e o bruto já é nulo onde o
    Favorita não registrava promoção; um `alias` simples preserva as duas
    semânticas.

    Sem agregado global: nenhuma média móvel, encoding nem estatística sobre
    a série inteira nasce aqui -- isso é Sprint 14 (CLAUDE.md, seção 8).
    """
    windowed = sales_raw.filter(pl.col("date").is_between(window_start, window_end))

    bounds = _pair_lifespan_bounds(
        sales_raw,
        windowed,
        window_start=window_start,
        window_end=window_end,
        delisting_gap_days=delisting_gap_days,
    )
    spine = _reindex_spine(bounds)
    operating_days = _store_operating_days(windowed).with_columns(
        pl.lit(True).alias("is_operating_day")
    )

    joined = (
        spine.join(windowed, on=["store_nbr", "item_nbr", "date"], how="left")
        .join(operating_days, on=["store_nbr", "date"], how="left")
        .with_columns(pl.col("is_operating_day").fill_null(False))
    )

    result = joined.with_columns(
        pl.col("store_nbr").cast(pl.String).alias("store_id"),
        pl.col("item_nbr").cast(pl.String).alias("item_id"),
        pl.col("unit_sales").fill_null(0.0).clip(lower_bound=0.0).alias("units_sold"),
        (-pl.col("unit_sales").fill_null(0.0)).clip(lower_bound=0.0).alias("units_returned"),
        pl.col("onpromotion").alias("on_promo"),
        pl.lit(None, dtype=pl.Float64).alias("price"),
    )
    result = _apply_anomalies(result, anomalies)
    return result.select(
        "store_id",
        "item_id",
        "date",
        "units_sold",
        "units_returned",
        "on_promo",
        "price",
        "is_operating_day",
        "is_anomaly",
        "anomaly_reason",
    ).sort("store_id", "item_id", "date")


# --------------------------------------------------------------------------
# items / suppliers / stock
# --------------------------------------------------------------------------


def load_items(
    items_raw: pl.LazyFrame,
    sales_raw: pl.LazyFrame,
    *,
    fractional_threshold: float,
    default_pack_multiple: float,
) -> pl.DataFrame:
    """`items.csv` bruto + `fractional_ratio` medido em `sales_raw` -> tabela `items` canônica.

    `sales_raw` decide `unit_of_sale` (D5): esta função não sabe de janela,
    só do que recebe -- em produção (`build_canonical_favorita`), quem chama
    passa a fatia já restrita à janela de trabalho, precisamente para que
    dado bem fora da janela não mova a classificação de nenhum item (teste
    8, "sem vazamento por agregado global"). Diferente de `_pair_lifespan_bounds`,
    `fractional_ratio` É uma média -- olhar para fora da janela aqui seria o
    vazamento de verdade, por isso a responsabilidade de restringir a janela
    fica com quem chama, não escondida dentro desta função.

    Item sem nenhuma venda na fatia recebida tem `fractional_ratio` nulo após
    o join -- classificado como `unidade` (ausência de evidência de venda
    fracionária não é evidência de peso).

    `ean`, `description`, `cost`, `price_ref` ficam sempre `null`: o Favorita
    não tem esses dados (D7). `is_anchor` também fica `null` -- decisão
    explícita de não inventar um proxy (por volume, por exemplo) que
    atribuiria significado de negócio que o dado não carrega.
    """
    families = items_raw.select("family").unique().collect(engine="streaming")["family"].to_list()
    family_to_supplier_id = _build_family_to_supplier_id(families)

    fractional = profile_fractional_by_item(sales_raw).select("item_nbr", "fractional_ratio").lazy()

    return (
        items_raw.join(fractional, on="item_nbr", how="left")
        .with_columns(
            pl.col("item_nbr").cast(pl.String).alias("item_id"),
            pl.lit(None, dtype=pl.String).alias("ean"),
            pl.lit(None, dtype=pl.String).alias("description"),
            pl.col("family").alias("category"),
            pl.col("class").cast(pl.String).alias("item_class"),
            pl.col("family").replace_strict(family_to_supplier_id).alias("supplier_id"),
            pl.when(pl.col("fractional_ratio").fill_null(0.0) >= fractional_threshold)
            .then(pl.lit(UnitOfSale.PESO.value))
            .otherwise(pl.lit(UnitOfSale.UNIDADE.value))
            .alias("unit_of_sale"),
            pl.lit(default_pack_multiple).alias("pack_multiple"),
            pl.col("perishable").cast(pl.Boolean).alias("is_perishable"),
            pl.lit(None, dtype=pl.Boolean).alias("is_anchor"),
            pl.lit(None, dtype=pl.Float64).alias("cost"),
            pl.lit(None, dtype=pl.Float64).alias("price_ref"),
        )
        .select(
            "item_id",
            "ean",
            "description",
            "category",
            "item_class",
            "supplier_id",
            "unit_of_sale",
            "pack_multiple",
            "is_perishable",
            "is_anchor",
            "cost",
            "price_ref",
        )
        .sort("item_id")
        .collect(engine="streaming")
    )


def load_suppliers(
    items_raw: pl.LazyFrame, *, supplier_assumptions: SupplierAssumptionsParams
) -> pl.DataFrame:
    """Uma linha por `family` distinta em `items_raw`, valores de `supplier_assumptions` (D8).

    O Favorita não tem fornecedor -- esta tabela é premissa inteiramente
    arbitrada. Nenhum valor hardcoded: a Sprint 16 varre lead time em
    sensibilidade e precisa mexer nesses números sem tocar neste arquivo.

    `supplier_id` usa o mesmo slug determinístico de `load_items`
    (`_build_family_to_supplier_id`) -- recalculado aqui, não recebido como
    argumento, para que esta função continue correta sozinha, sem depender
    de quem chama passar o mapeamento certo.
    """
    families = items_raw.select("family").unique().collect(engine="streaming")["family"].to_list()
    family_to_supplier_id = _build_family_to_supplier_id(families)
    supplier_ids = sorted(family_to_supplier_id.values())
    n = len(supplier_ids)

    return pl.DataFrame(
        {
            "supplier_id": supplier_ids,
            "lead_time_days": [supplier_assumptions.default_lead_time_days] * n,
            "order_days": [list(supplier_assumptions.default_order_weekdays)] * n,
            "review_period_days": [supplier_assumptions.default_review_period_days] * n,
            "min_order_value": [supplier_assumptions.default_min_order_value] * n,
            "min_order_units": [supplier_assumptions.default_min_order_units] * n,
        },
        schema={
            "supplier_id": pl.String,
            "lead_time_days": pl.Int64,
            "order_days": pl.List(pl.Int64),
            "review_period_days": pl.Int64,
            "min_order_value": pl.Float64,
            "min_order_units": pl.Float64,
        },
    )


def load_stock() -> pl.DataFrame:
    """Tabela `stock` vazia, no schema canônico (D9).

    O Favorita não tem saldo de estoque. A posição de estoque nasce no
    simulador (Fase II, CLAUDE.md seção 6) -- ruptura não é observável em
    dado público. Limitação registrada para a lista da Sprint 17.
    """
    return pl.DataFrame(schema=expected_polars_schema(Stock))


# --------------------------------------------------------------------------
# Validação streaming-safe de sales (única tabela em escala real)
# --------------------------------------------------------------------------


def _validate_sales_streaming(path: Path) -> None:
    """Validação leve e streaming-safe da tabela `sales` já escrita em disco.

    `sales` é a única tabela canônica em escala real (dezenas de milhões de
    linhas na janela de 24 meses). Rodar `validate_table` (que coleta o
    frame inteiro em memória para amostrar violações) contrariaria o
    requisito de streaming da Fase A, seção 5 ("não colete o frame inteiro
    em memória"). Esta função cobre o subconjunto de `validate_table` que
    cabe em agregado lazy: chave primária única e nulo indevido nos campos
    obrigatórios. Não repete checagem de dtype/enumeração/limite numérico
    coluna a coluna -- essas são garantidas por construção em `load_sales` e
    já cobertas pelos testes sintéticos (pequenos, sem esta restrição) desta
    sprint e de `motor.io.contracts`. Decisão registrada no relatório da
    Fase B como não especificada no prompt: streaming vs. validação completa
    é um trade-off de engenharia, não uma das nove decisões D1-D9.

    `items`, `suppliers` e `stock` são pequenas (milhares de linhas, no
    máximo) e continuam validadas por `validate_table`, sem essa exceção.
    """
    lf = pl.scan_parquet(path)

    dup_groups = (
        lf.group_by(list(SALES_PRIMARY_KEY))
        .len()
        .filter(pl.col("len") > 1)
        .collect(engine="streaming")
    )
    if dup_groups.height > 0:
        raise SchemaValidationError(
            "sales",
            [
                Violation(
                    ", ".join(SALES_PRIMARY_KEY),
                    "chave primária duplicada",
                    dup_groups.height,
                    dup_groups.head(5),
                )
            ],
        )

    null_counts = lf.select(
        [pl.col(c).is_null().sum().alias(c) for c in _SALES_REQUIRED_NON_NULL]
    ).collect(engine="streaming")
    violations = [
        Violation(col, "valores nulos não permitidos", int(null_counts[col].item()), None)
        for col in _SALES_REQUIRED_NON_NULL
        if null_counts[col].item() > 0
    ]
    if violations:
        raise SchemaValidationError("sales", violations)


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------


def build_canonical_favorita(
    raw_parquet_dir: Path, out_dir: Path, params: Params, *, overwrite: bool = False
) -> CanonicalManifest:
    """Orquestra as quatro tabelas canônicas a partir do parquet bruto do Favorita.

    Escreve `{sales,items,suppliers,stock}.parquet` e `manifest.json` em
    `out_dir`. `sales` sai via `sink_parquet` (streaming); as outras três,
    pequenas, via `write_parquet` de um `pl.DataFrame` já coletado.

    Idempotente: se `overwrite=False` e os quatro parquets mais o manifesto
    já existem em `out_dir`, a execução inteira é pulada e o manifesto salvo
    é relido e devolvido -- mesmo padrão de `convert_raw_to_parquet`
    (`motor.io.raw`). Com `overwrite=True`, refaz tudo; os quatro parquets de
    DADO saem byte a byte idênticos a uma execução anterior com os mesmos
    parâmetros e entrada -- `generated_at`/`execution_seconds` do manifesto
    são a exceção esperada e documentada, não fazem parte dessa garantia.
    """
    manifest_path = out_dir / "manifest.json"
    table_paths = {name: out_dir / f"{name}.parquet" for name in _CANONICAL_TABLES}
    if not overwrite and manifest_path.exists() and all(p.exists() for p in table_paths.values()):
        return CanonicalManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    start = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)

    train_raw = scan_raw("train", raw_parquet_dir)
    items_raw = scan_raw("items", raw_parquet_dir)
    canonical = params.canonical

    sales_lf = load_sales(
        train_raw,
        window_start=canonical.window_start,
        window_end=canonical.window_end,
        delisting_gap_days=canonical.delisting_gap_days,
        anomalies=canonical.anomalies,
    )
    sales_lf.sink_parquet(table_paths["sales"])
    _validate_sales_streaming(table_paths["sales"])
    sales_rows = int(pl.scan_parquet(table_paths["sales"]).select(pl.len()).collect().item())

    windowed_train_raw = train_raw.filter(
        pl.col("date").is_between(canonical.window_start, canonical.window_end)
    )
    items_df = load_items(
        items_raw,
        windowed_train_raw,
        fractional_threshold=canonical.fractional_threshold,
        default_pack_multiple=params.supplier_assumptions.default_pack_multiple,
    )
    validate_table(items_df, Item, table_name="items", primary_key=ITEMS_PRIMARY_KEY)
    items_df.write_parquet(table_paths["items"])

    suppliers_df = load_suppliers(items_raw, supplier_assumptions=params.supplier_assumptions)
    validate_table(
        suppliers_df, Supplier, table_name="suppliers", primary_key=SUPPLIERS_PRIMARY_KEY
    )
    validate_supplier_order_cadence(suppliers_df)
    suppliers_df.write_parquet(table_paths["suppliers"])

    stock_df = load_stock()
    validate_table(stock_df, Stock, table_name="stock", primary_key=STOCK_PRIMARY_KEY)
    stock_df.write_parquet(table_paths["stock"])

    validate_referential_integrity(items=items_df, suppliers=suppliers_df, stock=stock_df)
    _validate_sales_referential_integrity_streaming(table_paths["sales"], items_df)

    row_counts = {
        "sales": sales_rows,
        "items": items_df.height,
        "suppliers": suppliers_df.height,
        "stock": stock_df.height,
    }
    output_files = {
        name: OutputFileManifest(size_bytes=path.stat().st_size)
        for name, path in table_paths.items()
    }
    input_files = {
        name: InputFileManifest(
            sha256=_hash_file(raw_parquet_dir / f"{name}.parquet"),
            size_bytes=(raw_parquet_dir / f"{name}.parquet").stat().st_size,
        )
        for name in ("train", "items")
    }
    active_params = {
        "canonical": canonical.model_dump(mode="json"),
        "supplier_assumptions": params.supplier_assumptions.model_dump(mode="json"),
    }
    params_hash = hashlib.sha256(params.model_dump_json().encode("utf-8")).hexdigest()

    manifest = CanonicalManifest(
        schema_version=CANONICAL_SCHEMA_VERSION,
        generated_at=datetime.now(UTC),
        execution_seconds=time.monotonic() - start,
        window_start=canonical.window_start,
        window_end=canonical.window_end,
        git_commit_hash=_git_commit_hash(_REPO_ROOT),
        params_hash=params_hash,
        active_params=active_params,
        input_files=input_files,
        row_counts=row_counts,
        output_files=output_files,
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def _validate_sales_referential_integrity_streaming(
    sales_path: Path, items_df: pl.DataFrame
) -> None:
    """`item_id` de `sales` existe em `items` -- anti-join lazy, nunca coletando `sales` inteira."""
    orphans = (
        pl.scan_parquet(sales_path)
        .join(items_df.lazy().select("item_id"), on="item_id", how="anti")
        .limit(1)
        .collect(engine="streaming")
    )
    if orphans.height > 0:
        raise SchemaValidationError(
            "integridade referencial",
            [
                Violation(
                    "item_id", "referencia item_id inexistente em items (tabela sales)", None, None
                )
            ],
        )
