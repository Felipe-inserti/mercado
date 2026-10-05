"""Sprint 22: da exportação de um cliente para as quatro tabelas canônicas.

Esta é a prova da promessa da Sprint 1 ("o contrato define o que o sistema
precisa, e isso torna o motor portável para o ERP de um cliente sem
reescrever nada acima de `io/`"): aqui, e só aqui, `codigo` vira `item_id`,
`fornecedor` vira `supplier_id`. Acima desta camada ninguém sabe que o
cliente existe. Irmão de `motor.io.loaders` (Favorita).

ENTRADAS (um diretório; dado de cliente vive em `data/cliente/`, nunca no git)
-----------------------------------------------------------------------------
- `vendas.csv`        data;codigo;quantidade;preco_unit;tipo  (V venda, D devolução, C cancelamento)
- `cadastro.csv`      codigo;ean;descricao;categoria;unidade_venda;fornecedor;custo_cadastro;
                      preco_venda  + opcionais: fardo;saldo_estoque;perecivel;validade_dias
- `fornecedores.csv`  fornecedor_id;nome;tipo;lead_time_dias;dias_pedido;revisao_dias;
                      pedido_minimo_rs;pedido_minimo_un;fardo_padrao  (preenchido na entrevista)
- `nfe/*.xml`         NF-e 4.00 de ENTRADA (custo real, fornecedor, fardo)

Formato brasileiro: `;` como separador, vírgula decimal, datas `dd/mm/aaaa`;
UTF-8 (com ou sem BOM) ou Windows-1252. Só CSV nesta versão ("salvar como
CSV"); NFC-e de venda é o próximo passo, fora da Sprint 22.

DECISÕES (DC1-DC9; prefixo DC para não colidir com D1-D9 da Sprint 3)
---------------------------------------------------------------------
DC1 Cancelamento. Linha `tipo=C` sai de `sales` e é CONTADA no `LoadReport`.
DC2 Devolução. A demanda é a VENDA BRUTA: `units_sold = V`, e a devolução fica
    em `units_returned = D`, sem descontar uma da outra. A devolução refere-se a
    uma compra de OUTRO dia e afeta o estoque, não a demanda: descontá-la da
    venda de hoje subestimaria o que o cliente quis comprar hoje. (O Favorita
    segue outra decomposição, a do líquido diário, porque só tem o líquido.)
DC3 Código genérico ("diversos"). Fora de `sales` (não dá para prever), e a
    PARCELA DO FATURAMENTO que ele representa vai para o perfil -- se for
    alta, o dado não serve para reposição. Código sem cadastro idem: fora,
    listado no `LoadReport`, e conta no denominador do faturamento.
DC4 Item duplicado. Mesmo EAN e mesma unidade de venda: une os códigos no de
    venda mais recente (empate: menor código), somando as vendas -- TODA
    união vai para o `LoadReport` e para a auditoria. Mesmo EAN com unidade
    diferente NÃO une (EAN de caixa e de unidade parecem duplicata e não
    são): só a auditoria aponta. Mesmo `codigo` duas vezes no cadastro: a
    última linha vence, e é listado.
DC5 Unidade de compra. O fardo vem de `qTrib/qCom` da última nota regular do
    item, SÓ quando `uCom != uTrib`. Com `uCom == uTrib` a razão não informa
    o fardo: usa `fardo` do cadastro, depois `fardo_padrao` do fornecedor
    (só item vendido por unidade, nunca por kg), senão desconhecido -- e a
    auditoria aponta. Nota e cadastro divergentes: a nota vence, auditoria
    registra.
DC6 Fornecedor principal. O fornecedor REGULAR de maior valor comprado do
    item (soma de `vProd`) na janela de `principal_supplier_window_days`,
    ANCORADA NA ÚLTIMA NOTA DOS DADOS (nunca no relógio: determinístico).
    Desempate: compra mais recente, depois menor `supplier_id`. Sem nota na
    janela: o fornecedor do cadastro. Sem nenhum: o item sai e é listado.
    Só entra como fornecedor quem está em `fornecedores.csv` (precisa de
    prazo e dias de pedido, que a nota não traz).
DC7 Compra de emergência (atacarejo). `tipo` explícito em `fornecedores.csv`
    vence; vazio, o nome do emitente (ou o prefixo do CNAE, quando a tag
    existe) contra os padrões de `client_loader`. Emergência não vira
    principal, não entra no custo e sai de `suppliers`. Emitente desconhecido
    com poucas notas só gera AVISO (nunca muda a classificação).
DC8 Custo. `(vProd - vDesc + vIPI + vICMSST) / qTrib` da última nota regular
    (por data de emissão, não por ordem de arquivo). Frete FORA -- limitação
    declarada. Sem nota: custo do cadastro. `economics_origin` registra qual.
DC9 Saldo negativo. Vira 0 (o contrato proíbe negativo) e é contado.

LIMITAÇÃO: a NF-e não traz a data de chegada nem a do pedido, então o LEAD
TIME não é observável pela nota -- vem da entrevista (`fornecedores.csv`).
"""

from __future__ import annotations

import argparse
import io
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from motor.config import ClientLoaderParams, Params, load_params
from motor.io.contracts import (
    ITEMS_PRIMARY_KEY,
    SALES_PRIMARY_KEY,
    STOCK_PRIMARY_KEY,
    SUPPLIERS_PRIMARY_KEY,
    Item,
    Sale,
    Stock,
    Supplier,
    UnitOfSale,
    expected_polars_schema,
    validate_referential_integrity,
    validate_supplier_order_cadence,
    validate_table,
)
from motor.io.nfe_xml import NfeDocument, parse_nfe

_TRUE_TOKENS: Final = frozenset({"S", "SIM", "1", "TRUE", "Y", "T"})
_UNIT_TOKENS: Final[dict[str, str]] = {
    "UN": UnitOfSale.UNIDADE.value,
    "UNIDADE": UnitOfSale.UNIDADE.value,
    "KG": UnitOfSale.PESO.value,
    "PESO": UnitOfSale.PESO.value,
}
_MOVEMENT_TYPES: Final = ("V", "D", "C")


class ClientDataError(ValueError):
    """Exportação do cliente ilegível ou fora do formato esperado -- a
    mensagem nomeia arquivo e coluna."""


@dataclass(frozen=True)
class CodeMerge:
    """Uma união de códigos do cadastro (DC4)."""

    survivor: str
    merged: str
    ean: str


@dataclass(frozen=True)
class LoadReport:
    """Tudo que o loader decidiu ou descartou -- nada some em silêncio."""

    period_start: date
    period_end: date
    n_sales_rows: int
    n_cancelled_rows: int
    n_generic_rows: int
    generic_revenue_share: float
    n_orphan_rows: int
    orphan_codes: tuple[str, ...]
    excluded_no_supplier: tuple[str, ...]
    merges: tuple[CodeMerge, ...]
    repeated_codes: tuple[str, ...]
    emergency_suppliers: tuple[str, ...]
    unknown_issuers: tuple[str, ...]
    possible_emergency_suppliers: tuple[str, ...]
    n_nfe_files: int
    n_nfe_other_recipient: int
    n_nfe_returns_ignored: int
    n_nfe_items_unmatched: int
    negative_stock_clamped: int
    n_open_orders_unmatched: int


@dataclass(frozen=True)
class ClientLoadResult:
    sales: pl.DataFrame
    items: pl.DataFrame
    suppliers: pl.DataFrame
    stock: pl.DataFrame
    audit_inputs: pl.DataFrame
    """Por item: de onde veio cada decisão (custo, fardo, fornecedor), para a auditoria."""
    purchases: pl.DataFrame
    """Compras REAIS lidas das notas (`item_id, date, units`), de qualquer emitente
    conhecido -- alimenta a média de compras recentes do limite de variação."""
    open_orders: pl.DataFrame | None
    """Pedidos em aberto (`item_id, supplier_id, quantity, expected_date`). `None` =
    arquivo ausente (não se sabe o que está a caminho); vazio = sabe-se que nada está."""
    report: LoadReport


# --------------------------------------------------------------------------
# leitura de CSV
# --------------------------------------------------------------------------


def _read_csv(
    path: Path, *, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> pl.DataFrame:
    """CSV com `;`, tudo como texto, colunas em minúsculas e vazio -> nulo."""
    if not path.exists():
        raise ClientDataError(f"{path.name}: arquivo não encontrado em {path.parent}")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    df = pl.read_csv(io.BytesIO(text.encode("utf-8")), separator=";", infer_schema=False)
    df = df.rename({c: c.strip().lower() for c in df.columns})
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ClientDataError(
            f"{path.name}: coluna(s) obrigatória(s) ausente(s): {missing}; "
            f"encontradas: {df.columns}"
        )
    for col in optional:
        if col not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.String).alias(col))
    return df.with_columns(pl.col(pl.String).str.strip_chars().replace("", None))


def _num(name: str) -> pl.Expr:
    """Texto brasileiro ('1.234,56' ou '12,5') -> Float64; nulo continua nulo."""
    c = pl.col(name)
    normalized = (
        pl.when(c.str.contains(",", literal=True))
        .then(c.str.replace_all(".", "", literal=True).str.replace(",", ".", literal=True))
        .otherwise(c)
    )
    return normalized.cast(pl.Float64, strict=True).alias(name)


def _parse(df: pl.DataFrame, exprs: list[pl.Expr], *, file: str) -> pl.DataFrame:
    try:
        return df.with_columns(exprs)
    except pl.exceptions.PolarsError as exc:
        raise ClientDataError(f"{file}: valor numérico ou data inválido ({exc})") from exc


def _only_digits(name: str) -> pl.Expr:
    return pl.col(name).str.replace_all(r"\D", "").replace("", None).alias(name)


# --------------------------------------------------------------------------
# DC7 -- compra de emergência
# --------------------------------------------------------------------------


def classify_supplier(
    *, kind: str | None, name: str, cnae: str | None, params: ClientLoaderParams
) -> bool:
    """`True` se o fornecedor é de COMPRA DE EMERGÊNCIA (atacarejo) -- DC7.

    O `tipo` explícito da entrevista vence qualquer heurística (um "Atacado
    do Zé" regular declarado como `regular` continua regular). Sem `tipo`,
    nome do emitente ou prefixo de CNAE contra os padrões de config."""
    declared = (kind or "").strip().lower()
    if declared == "emergency":
        return True
    if declared == "regular":
        return False
    upper = name.upper()
    if any(pattern.upper() in upper for pattern in params.emergency_name_patterns):
        return True
    digits = "".join(ch for ch in (cnae or "") if ch.isdigit())
    return bool(digits) and any(digits.startswith(p) for p in params.emergency_cnae_prefixes)


# --------------------------------------------------------------------------
# DC6 -- fornecedor principal
# --------------------------------------------------------------------------


def select_principal_suppliers(purchases: pl.DataFrame, *, window_days: int) -> pl.DataFrame:
    """Fornecedor principal por item (DC6).

    `purchases`: `item_id, supplier_id, issued_on, value_rs, is_emergency`. A
    janela termina na ÚLTIMA data de `purchases` (os dados, não o relógio).
    Emergência fica fora. Maior valor na janela; empate: compra mais recente,
    depois menor `supplier_id`. Item sem compra regular na janela não aparece
    no resultado -- quem chama cai no cadastro."""
    if purchases.height == 0:
        return pl.DataFrame(schema={"item_id": pl.String, "supplier_id": pl.String})
    anchor = purchases["issued_on"].max()
    assert isinstance(anchor, date)
    window_start = anchor - timedelta(days=window_days)
    return (
        purchases.filter((pl.col("issued_on") >= window_start) & ~pl.col("is_emergency"))
        .group_by("item_id", "supplier_id")
        .agg(pl.col("value_rs").sum().alias("total"), pl.col("issued_on").max().alias("last"))
        .sort(
            ["item_id", "total", "last", "supplier_id"],
            descending=[False, True, True, False],
        )
        .group_by("item_id", maintain_order=True)
        .first()
        .select("item_id", "supplier_id")
        .sort("item_id")
    )


# --------------------------------------------------------------------------
# fornecedores (entrevista)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _SupplierFile:
    table: pl.DataFrame  # todas as linhas do arquivo, com `is_emergency`
    regular: pl.DataFrame  # as do esquema canônico Supplier, só regulares
    default_pack: dict[str, float]


def _load_suppliers_file(path: Path, params: ClientLoaderParams) -> _SupplierFile:
    df = _read_csv(
        path,
        required=(
            "fornecedor_id", "nome", "tipo", "lead_time_dias", "dias_pedido", "revisao_dias",
            "pedido_minimo_rs", "pedido_minimo_un",
        ),
        optional=("fardo_padrao",),
    )  # fmt: skip
    df = _parse(
        df.with_columns(_only_digits("fornecedor_id")),
        [
            pl.col("lead_time_dias").cast(pl.Int64, strict=True),
            pl.col("revisao_dias").cast(pl.Int64, strict=True),
            _num("pedido_minimo_rs"),
            _num("pedido_minimo_un"),
            _num("fardo_padrao"),
        ],
        file=path.name,
    )
    emergency = [
        classify_supplier(kind=r["tipo"], name=r["nome"] or "", cnae=None, params=params)
        for r in df.iter_rows(named=True)
    ]
    df = df.with_columns(pl.Series("is_emergency", emergency, dtype=pl.Boolean))
    try:
        order_days = [
            sorted({int(d) for d in str(v).replace(",", "|").split("|") if d.strip()})
            for v in df["dias_pedido"].to_list()
        ]
    except ValueError as exc:
        raise ClientDataError(f"{path.name}: dias_pedido inválido (use ex.: 1|4): {exc}") from exc
    regular = (
        df.with_columns(pl.Series("order_days", order_days, dtype=pl.List(pl.Int64)))
        .filter(~pl.col("is_emergency"))
        .select(
            pl.col("fornecedor_id").alias("supplier_id"),
            pl.col("lead_time_dias").alias("lead_time_days"),
            "order_days",
            pl.col("revisao_dias").alias("review_period_days"),
            pl.col("pedido_minimo_rs").fill_null(0.0).alias("min_order_value"),
            pl.col("pedido_minimo_un").fill_null(0.0).alias("min_order_units"),
        )
        .sort("supplier_id")
    )
    default_pack = {
        r["fornecedor_id"]: r["fardo_padrao"]
        for r in df.iter_rows(named=True)
        if r["fardo_padrao"] is not None and r["fardo_padrao"] > 0
    }
    return _SupplierFile(table=df, regular=regular, default_pack=default_pack)


# --------------------------------------------------------------------------
# cadastro
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Cadastro:
    rows: pl.DataFrame
    repeated_codes: tuple[str, ...]
    generic_codes: frozenset[str]


def _load_cadastro(path: Path, params: ClientLoaderParams) -> _Cadastro:
    df = _read_csv(
        path,
        required=(
            "codigo", "ean", "descricao", "categoria", "unidade_venda", "fornecedor",
            "custo_cadastro", "preco_venda",
        ),
        optional=("fardo", "saldo_estoque", "perecivel", "validade_dias"),
    )  # fmt: skip
    counts = Counter(df["codigo"].to_list())
    repeated = tuple(sorted(code for code, n in counts.items() if n > 1))
    df = df.unique(subset="codigo", keep="last", maintain_order=True)  # DC4: a última linha vence
    unknown_units = sorted(
        {u for u in df["unidade_venda"].to_list() if (u or "").upper() not in _UNIT_TOKENS}
    )
    if unknown_units:
        raise ClientDataError(
            f"{path.name}: unidade_venda desconhecida: {unknown_units} (use UN ou KG)"
        )
    df = _parse(
        df.with_columns(_only_digits("fornecedor")),
        [
            _num("custo_cadastro"),
            _num("preco_venda"),
            _num("fardo"),
            _num("saldo_estoque"),
            _num("validade_dias"),
        ],
        file=path.name,
    )
    df = df.with_columns(
        pl.col("unidade_venda").str.to_uppercase().replace_strict(_UNIT_TOKENS).alias("unit"),
        pl.col("perecivel")
        .str.to_uppercase()
        .is_in(list(_TRUE_TOKENS))
        .fill_null(False)
        .alias("perishable"),
        pl.when(pl.col("fardo") > 0).then(pl.col("fardo")).otherwise(None).alias("fardo"),
    )
    patterns = [p.upper() for p in params.generic_description_patterns]
    generic = set(params.generic_codes) | {
        r["codigo"]
        for r in df.iter_rows(named=True)
        if any(p in (r["descricao"] or "").upper() for p in patterns)
    }
    return _Cadastro(
        rows=df.filter(~pl.col("codigo").is_in(list(generic))),
        repeated_codes=repeated,
        generic_codes=frozenset(generic),
    )


# --------------------------------------------------------------------------
# vendas (DC1, DC2, DC3)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _SalesRaw:
    movements: pl.DataFrame  # V e D de códigos do cadastro: codigo, day, tipo, qty, price
    open_days: frozenset[date]
    period_start: date
    period_end: date
    n_rows: int
    n_cancelled: int
    n_generic: int
    generic_share: float
    n_orphan: int
    orphan_codes: tuple[str, ...]


def _load_sales(path: Path, cadastro: _Cadastro) -> _SalesRaw:
    df = _read_csv(path, required=("data", "codigo", "quantidade", "preco_unit", "tipo"))
    df = df.with_columns(pl.col("tipo").str.to_uppercase())
    bad = sorted(set(df["tipo"].to_list()) - set(_MOVEMENT_TYPES))
    if bad:
        raise ClientDataError(
            f"{path.name}: tipo de movimento desconhecido: {bad} (esperado V, D ou C)"
        )
    df = _parse(
        df,
        [
            pl.col("data").str.to_date("%d/%m/%Y", strict=True).alias("day"),
            _num("quantidade").alias("qty"),
            _num("preco_unit").alias("price"),
        ],
        file=path.name,
    ).drop("data", "quantidade", "preco_unit")
    if df.height == 0:
        raise ClientDataError(f"{path.name}: nenhuma linha de venda")

    day_min, day_max = df["day"].min(), df["day"].max()
    assert isinstance(day_min, date)
    assert isinstance(day_max, date)
    open_days = frozenset(df["day"].unique().to_list())
    n_cancelled = df.filter(pl.col("tipo") == "C").height  # DC1
    live = df.filter(pl.col("tipo") != "C")

    sold = live.filter(pl.col("tipo") == "V").with_columns(
        (pl.col("qty") * pl.col("price")).alias("value")
    )
    total_value = float(sold["value"].sum() or 0.0)
    is_generic = pl.col("codigo").is_in(list(cadastro.generic_codes))
    generic_value = float(sold.filter(is_generic)["value"].sum() or 0.0)  # DC3

    known_codes = list(cadastro.rows["codigo"].to_list())
    is_known = pl.col("codigo").is_in(known_codes)
    orphans = live.filter(~is_known & ~is_generic)
    return _SalesRaw(
        movements=live.filter(is_known).select("codigo", "day", "tipo", "qty", "price"),
        open_days=open_days,
        period_start=day_min,
        period_end=day_max,
        n_rows=df.height,
        n_cancelled=n_cancelled,
        n_generic=live.filter(is_generic).height,
        generic_share=generic_value / total_value if total_value > 0 else 0.0,
        n_orphan=orphans.height,
        orphan_codes=tuple(sorted(orphans["codigo"].unique().to_list())),
    )


# --------------------------------------------------------------------------
# DC4 -- união de códigos
# --------------------------------------------------------------------------


def _plan_merges(cadastro: pl.DataFrame, movements: pl.DataFrame) -> tuple[CodeMerge, ...]:
    last_sale: dict[str, date] = {
        r["codigo"]: r["last"]
        for r in movements.filter((pl.col("tipo") == "V") & (pl.col("qty") > 0))
        .group_by("codigo")
        .agg(pl.col("day").max().alias("last"))
        .iter_rows(named=True)
    }
    by_ean: dict[str, list[dict[str, object]]] = defaultdict(list)
    for r in cadastro.filter(pl.col("ean").is_not_null()).iter_rows(named=True):
        by_ean[r["ean"]].append(r)
    merges: list[CodeMerge] = []
    for ean, rows in sorted(by_ean.items()):
        if len(rows) < 2 or len({r["unit"] for r in rows}) != 1:
            continue  # unidades diferentes: NÃO une, só a auditoria aponta
        codes = sorted(str(r["codigo"]) for r in rows)
        survivor = max(codes, key=lambda c: (last_sale.get(c, date.min), [-ord(ch) for ch in c]))
        merges.extend(CodeMerge(survivor, c, ean) for c in codes if c != survivor)
    return tuple(sorted(merges, key=lambda m: (m.survivor, m.merged)))


# --------------------------------------------------------------------------
# notas fiscais (DC5-DC8)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Notes:
    lines: (
        pl.DataFrame
    )  # item_id, supplier_id, issued_on, key, value_rs, cost_num, qtrib, pack_ratio, is_emergency
    n_files: int
    n_other_recipient: int
    n_returns_ignored: int
    n_unmatched: int
    unknown_issuers: tuple[str, ...]
    possible_emergency: tuple[str, ...]


_LINE_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "item_id": pl.String, "supplier_id": pl.String, "issued_on": pl.Date, "key": pl.String,
    "value_rs": pl.Float64, "cost_num": pl.Float64, "qtrib": pl.Float64,
    "pack_ratio": pl.Float64, "is_emergency": pl.Boolean,
}  # fmt: skip


def _load_notes(
    nfe_dir: Path,
    *,
    store_cnpj: str,
    ean_to_item: dict[str, str],
    suppliers: _SupplierFile,
    params: ClientLoaderParams,
) -> _Notes:
    files = sorted(nfe_dir.glob("*.xml")) if nfe_dir.is_dir() else []
    known = {r["fornecedor_id"]: r for r in suppliers.table.iter_rows(named=True)}
    docs: list[NfeDocument] = [parse_nfe(f) for f in files]
    n_other = n_returns = n_unmatched = 0
    rows: list[dict[str, object]] = []
    unknown_notes: Counter[str] = Counter()
    anchor = max((d.issued_on for d in docs), default=None)
    for doc in sorted(docs, key=lambda d: (d.issued_on, d.key)):
        if doc.recipient_cnpj != store_cnpj:
            n_other += 1
            continue
        if doc.purpose == 4:  # devolução ao fornecedor: não é compra
            n_returns += 1
            continue
        issuer = known.get(doc.issuer_cnpj)
        if issuer is None:
            if anchor and doc.issued_on >= anchor - timedelta(
                days=params.principal_supplier_window_days
            ):
                unknown_notes[doc.issuer_cnpj] += 1
            continue
        is_emergency = bool(issuer["is_emergency"]) or classify_supplier(
            kind=issuer["tipo"], name=doc.issuer_name, cnae=doc.issuer_cnae, params=params
        )
        for it in doc.items:
            item_id = ean_to_item.get(it.ean)
            if item_id is None:
                n_unmatched += 1
                continue
            rows.append(
                {
                    "item_id": item_id, "supplier_id": doc.issuer_cnpj, "issued_on": doc.issued_on,
                    "key": doc.key, "value_rs": it.vprod,
                    "cost_num": it.vprod - it.vdesc + it.vipi + it.vicmsst, "qtrib": it.qtrib,
                    "pack_ratio": it.pack_ratio, "is_emergency": is_emergency,
                }
            )  # fmt: skip
    unknown = tuple(sorted(unknown_notes))
    return _Notes(
        lines=pl.DataFrame(rows, schema=_LINE_SCHEMA),
        n_files=len(files),
        n_other_recipient=n_other,
        n_returns_ignored=n_returns,
        n_unmatched=n_unmatched,
        unknown_issuers=unknown,
        possible_emergency=tuple(
            c for c in unknown if unknown_notes[c] <= params.emergency_warn_max_notes
        ),
    )


def _last_regular_note(lines: pl.DataFrame) -> pl.DataFrame:
    """Por item, a última nota REGULAR (data de emissão, depois chave): custo
    unitário e razão do fardo dessa nota -- DC5/DC8."""
    if lines.height == 0:
        return pl.DataFrame(
            schema={
                "item_id": pl.String, "last_regular_nfe_date": pl.Date,
                "last_regular_nfe_cost": pl.Float64, "last_pack_ratio": pl.Float64,
            }
        )  # fmt: skip
    return (
        lines.filter(~pl.col("is_emergency"))
        .group_by("item_id", "key", "issued_on")
        .agg(
            pl.col("cost_num").sum().alias("cost_num"),
            pl.col("qtrib").sum().alias("qtrib"),
            pl.col("pack_ratio").first().alias("last_pack_ratio"),
        )
        .sort(["item_id", "issued_on", "key"])
        .group_by("item_id", maintain_order=True)
        .last()
        .select(
            "item_id",
            pl.col("issued_on").alias("last_regular_nfe_date"),
            (pl.col("cost_num") / pl.col("qtrib")).alias("last_regular_nfe_cost"),
            "last_pack_ratio",
        )
    )


# --------------------------------------------------------------------------
# montagem
# --------------------------------------------------------------------------


def _ean_map(cadastro: pl.DataFrame, merges: tuple[CodeMerge, ...]) -> dict[str, str]:
    """EAN -> item_id do cadastro já com uniões. EAN ambíguo (dois itens não
    unidos) fica de fora: a linha da nota vira "sem correspondência"."""
    survivors = {m.merged: m.survivor for m in merges}
    owners: dict[str, set[str]] = defaultdict(set)
    for r in cadastro.filter(pl.col("ean").is_not_null()).iter_rows(named=True):
        owners[r["ean"]].add(survivors.get(r["codigo"], r["codigo"]))
    return {ean: next(iter(codes)) for ean, codes in owners.items() if len(codes) == 1}


def _sum_optional(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _merge_cadastro(cad: pl.DataFrame, merges: tuple[CodeMerge, ...]) -> pl.DataFrame:
    """Aplica as uniões: o sobrevivente fica com a linha dele, e o saldo dos
    códigos unidos soma no dele."""
    if not merges:
        return cad
    merged_into = {m.merged: m.survivor for m in merges}
    saldo: dict[str, list[float | None]] = defaultdict(list)
    for r in cad.iter_rows(named=True):
        saldo[merged_into.get(r["codigo"], r["codigo"])].append(r["saldo_estoque"])
    kept = cad.filter(~pl.col("codigo").is_in(list(merged_into)))
    totals = [_sum_optional(saldo[c]) for c in kept["codigo"].to_list()]
    return kept.with_columns(pl.Series("saldo_estoque", totals, dtype=pl.Float64))


def _resolve_suppliers(
    cad: pl.DataFrame,
    purchases: pl.DataFrame,
    *,
    regular_ids: set[str],
    window_days: int,
) -> pl.DataFrame:
    """Colunas `supplier_id` e `supplier_source` por item; sem fornecedor -> nulo."""
    principal = {
        r["item_id"]: r["supplier_id"]
        for r in select_principal_suppliers(purchases, window_days=window_days).iter_rows(
            named=True
        )
        if r["supplier_id"] in regular_ids
    }
    supplier_ids: list[str | None] = []
    sources: list[str | None] = []
    for r in cad.iter_rows(named=True):
        if r["codigo"] in principal:
            supplier_ids.append(principal[r["codigo"]])
            sources.append("nota")
        elif r["fornecedor"] in regular_ids:
            supplier_ids.append(r["fornecedor"])
            sources.append("cadastro")
        else:
            supplier_ids.append(None)
            sources.append(None)
    return cad.with_columns(
        pl.Series("supplier_id", supplier_ids, dtype=pl.String),
        pl.Series("supplier_source", sources, dtype=pl.String),
    )


def _decide_pack(
    row: dict[str, object], default_pack: dict[str, float]
) -> tuple[float | None, str, bool, bool]:
    """(fardo, fonte, nota_nao_informa, conflito) -- DC5."""
    ratio = row["last_pack_ratio"]
    has_note = row["last_regular_nfe_date"] is not None
    cad_pack = row["fardo"]
    if isinstance(ratio, float):
        conflict = isinstance(cad_pack, float) and abs(cad_pack - ratio) > 1e-9
        return ratio, "nota", False, conflict
    uninformative = has_note
    if isinstance(cad_pack, float):
        return cad_pack, "cadastro", uninformative, False
    supplier_default = default_pack.get(str(row["supplier_id"]))
    if supplier_default is not None and row["unit"] == UnitOfSale.UNIDADE.value:
        return supplier_default, "fornecedor", uninformative, False
    return None, "desconhecido", uninformative, False


def _build_items(
    cad: pl.DataFrame, last_note: pl.DataFrame, suppliers: _SupplierFile, params: ClientLoaderParams
) -> tuple[pl.DataFrame, pl.DataFrame]:
    joined = cad.join(last_note, left_on="codigo", right_on="item_id", how="left")
    packs = [_decide_pack(r, suppliers.default_pack) for r in joined.iter_rows(named=True)]
    joined = joined.with_columns(
        pl.Series("pack", [p[0] for p in packs], dtype=pl.Float64),
        pl.Series("pack_source", [p[1] for p in packs], dtype=pl.String),
        pl.Series("nfe_pack_uninformative", [p[2] for p in packs], dtype=pl.Boolean),
        pl.Series("pack_conflict", [p[3] for p in packs], dtype=pl.Boolean),
        pl.col("last_regular_nfe_cost").is_not_null().alias("_has_cost"),
    )
    items = joined.select(
        pl.col("codigo").alias("item_id"),
        pl.col("ean"),
        pl.col("descricao").alias("description"),
        pl.col("categoria").alias("category"),
        pl.lit(None, dtype=pl.String).alias("item_class"),
        pl.col("supplier_id"),
        pl.col("unit").alias("unit_of_sale"),
        pl.col("pack").alias("pack_multiple"),
        pl.col("perishable").alias("is_perishable"),
        pl.lit(None, dtype=pl.Boolean).alias("is_anchor"),
        pl.when(pl.col("_has_cost"))
        .then(pl.col("last_regular_nfe_cost"))
        .otherwise(pl.col("custo_cadastro"))
        .alias("cost"),
        pl.col("preco_venda").alias("price_ref"),
        pl.when(pl.col("_has_cost"))
        .then(pl.lit("nfe_ultima_entrada"))
        .otherwise(pl.lit("cadastro"))
        .alias("economics_origin"),
    ).sort("item_id")
    audit_inputs = joined.select(
        pl.col("codigo").alias("item_id"),
        pl.col("custo_cadastro").alias("cadastro_cost"),
        "last_regular_nfe_cost",
        "last_regular_nfe_date",
        "supplier_source",
        "pack_source",
        "nfe_pack_uninformative",
        "pack_conflict",
        pl.col("fardo").alias("cadastro_pack"),
        pl.col("validade_dias").alias("shelf_life_days"),
    ).sort("item_id")
    _ = params
    return items, audit_inputs


def _build_sales(
    movements: pl.DataFrame,
    *,
    item_ids: list[str],
    code_map: dict[str, str],
    raw: _SalesRaw,
    store_id: str,
) -> pl.DataFrame:
    mapped = movements.with_columns(pl.col("codigo").replace(code_map)).filter(
        pl.col("codigo").is_in(item_ids)
    )
    daily = (
        mapped.group_by("codigo", "day")
        .agg(
            pl.col("qty").filter(pl.col("tipo") == "V").sum().alias("v"),
            pl.col("qty").filter(pl.col("tipo") == "D").sum().alias("d"),
            (pl.col("qty") * pl.col("price")).filter(pl.col("tipo") == "V").sum().alias("vv"),
        )
        .with_columns(
            pl.col("v").alias("units_sold"),  # DC2: venda bruta
            pl.col("d").alias("units_returned"),  # DC2: só registrada, não desconta a demanda
            pl.when(pl.col("v") > 0)
            .then(pl.col("vv") / pl.col("v"))
            .otherwise(None)
            .alias("price"),
        )
    )
    calendar = pl.DataFrame(
        {"date": pl.date_range(raw.period_start, raw.period_end, interval="1d", eager=True)}
    )
    first_day = daily.group_by("codigo").agg(pl.col("day").min().alias("first_day"))
    grid = first_day.join(calendar, how="cross").filter(pl.col("date") >= pl.col("first_day"))
    open_days = list(raw.open_days)
    return (
        grid.join(daily, left_on=["codigo", "date"], right_on=["codigo", "day"], how="left")
        .select(
            pl.lit(store_id).alias("store_id"),
            pl.col("codigo").alias("item_id"),
            "date",
            pl.col("units_sold").fill_null(0.0),
            pl.col("units_returned").fill_null(0.0),
            pl.lit(None, dtype=pl.Boolean).alias("on_promo"),
            pl.col("price").cast(pl.Float64),
            pl.col("date").is_in(open_days).alias("is_operating_day"),
            pl.lit(False).alias("is_anomaly"),
            pl.lit(None, dtype=pl.String).alias("anomaly_reason"),
        )
        .sort("item_id", "date")
    )


def _build_stock(cad: pl.DataFrame, *, store_id: str, snapshot: date) -> tuple[pl.DataFrame, int]:
    schema = expected_polars_schema(Stock)
    informed = cad.filter(pl.col("saldo_estoque").is_not_null())
    clamped = informed.filter(pl.col("saldo_estoque") < 0).height  # DC9
    if informed.height == 0:
        return pl.DataFrame(schema=schema), 0
    stock = informed.select(
        pl.lit(store_id).alias("store_id"),
        pl.col("codigo").alias("item_id"),
        pl.lit(snapshot).alias("date"),
        pl.col("saldo_estoque").clip(lower_bound=0.0).alias("on_hand"),
        pl.lit(None, dtype=pl.Float64).alias("in_transit"),
    ).sort("item_id")
    return stock, clamped


def _build_purchases(lines: pl.DataFrame, kept_items: list[str]) -> pl.DataFrame:
    if lines.height == 0:
        return pl.DataFrame(schema={"item_id": pl.String, "date": pl.Date, "units": pl.Float64})
    return (
        lines.filter(pl.col("item_id").is_in(kept_items))
        .group_by("item_id", "key", "issued_on")
        .agg(pl.col("qtrib").sum().alias("units"))
        .select("item_id", pl.col("issued_on").alias("date"), "units")
        .sort("item_id", "date")
    )


def _load_open_orders(
    path: Path, *, code_map: dict[str, str], kept_items: list[str]
) -> tuple[pl.DataFrame | None, int]:
    """`pedidos_em_aberto.csv` (opcional): `codigo;fornecedor;quantidade;data_prevista`.
    Código fora do canônico é descartado e contado."""
    if not path.exists():
        return None, 0
    df = _read_csv(
        path, required=("codigo", "quantidade"), optional=("fornecedor", "data_prevista")
    )
    df = _parse(
        df.with_columns(_only_digits("fornecedor")),
        [
            _num("quantidade"),
            pl.col("data_prevista").str.to_date("%d/%m/%Y", strict=True),
        ],
        file=path.name,
    ).with_columns(pl.col("codigo").replace(code_map))
    known = df.filter(pl.col("codigo").is_in(kept_items))
    out = (
        known.group_by("codigo", "fornecedor", "data_prevista")
        .agg(pl.col("quantidade").sum())
        .select(
            pl.col("codigo").alias("item_id"),
            pl.col("fornecedor").alias("supplier_id"),
            pl.col("quantidade").alias("quantity"),
            pl.col("data_prevista").alias("expected_date"),
        )
        .sort("item_id", "expected_date")
    )
    return out, df.height - known.height


def load_client_tables(
    input_dir: Path, *, params: ClientLoaderParams, store_id: str, store_cnpj: str
) -> ClientLoadResult:
    """Exportação do cliente -> tabelas canônicas, validadas, + `LoadReport`."""
    suppliers = _load_suppliers_file(input_dir / "fornecedores.csv", params)
    cadastro = _load_cadastro(input_dir / "cadastro.csv", params)
    raw = _load_sales(input_dir / "vendas.csv", cadastro)

    merges = _plan_merges(cadastro.rows, raw.movements)
    code_map = {m.merged: m.survivor for m in merges}
    cad = _merge_cadastro(cadastro.rows, merges)

    notes = _load_notes(
        input_dir / "nfe",
        store_cnpj=store_cnpj,
        ean_to_item=_ean_map(cadastro.rows, merges),
        suppliers=suppliers,
        params=params,
    )
    purchases = notes.lines.select(
        "item_id", "supplier_id", "issued_on", "value_rs", "is_emergency"
    )
    regular_ids = set(suppliers.regular["supplier_id"].to_list())
    cad = _resolve_suppliers(
        cad, purchases, regular_ids=regular_ids, window_days=params.principal_supplier_window_days
    )
    excluded = tuple(sorted(cad.filter(pl.col("supplier_id").is_null())["codigo"].to_list()))
    cad = cad.filter(pl.col("supplier_id").is_not_null())

    items, audit_inputs = _build_items(cad, _last_regular_note(notes.lines), suppliers, params)
    sales = _build_sales(
        raw.movements,
        item_ids=items["item_id"].to_list(),
        code_map=code_map,
        raw=raw,
        store_id=store_id,
    )
    stock, clamped = _build_stock(cad, store_id=store_id, snapshot=raw.period_end)
    kept_items = items["item_id"].to_list()
    purchases = _build_purchases(notes.lines, kept_items)
    open_orders, open_unmatched = _load_open_orders(
        input_dir / "pedidos_em_aberto.csv", code_map=code_map, kept_items=kept_items
    )

    validate_table(
        sales,
        Sale,
        table_name="sales",
        primary_key=SALES_PRIMARY_KEY,
        required_non_null=frozenset({"units_returned"}),
    )
    validate_table(
        items,
        Item,
        table_name="items",
        primary_key=ITEMS_PRIMARY_KEY,
        required_non_null=frozenset({"cost", "price_ref"}),
    )
    validate_table(
        suppliers.regular, Supplier, table_name="suppliers", primary_key=SUPPLIERS_PRIMARY_KEY
    )
    validate_table(stock, Stock, table_name="stock", primary_key=STOCK_PRIMARY_KEY)
    validate_supplier_order_cadence(suppliers.regular)
    validate_referential_integrity(
        items=items, suppliers=suppliers.regular, sales=sales, stock=stock
    )

    emergency = tuple(
        sorted(suppliers.table.filter(pl.col("is_emergency"))["fornecedor_id"].to_list())
    )
    report = LoadReport(
        period_start=raw.period_start,
        period_end=raw.period_end,
        n_sales_rows=raw.n_rows,
        n_cancelled_rows=raw.n_cancelled,
        n_generic_rows=raw.n_generic,
        generic_revenue_share=raw.generic_share,
        n_orphan_rows=raw.n_orphan,
        orphan_codes=raw.orphan_codes,
        excluded_no_supplier=excluded,
        merges=merges,
        repeated_codes=cadastro.repeated_codes,
        emergency_suppliers=emergency,
        unknown_issuers=notes.unknown_issuers,
        possible_emergency_suppliers=notes.possible_emergency,
        n_nfe_files=notes.n_files,
        n_nfe_other_recipient=notes.n_other_recipient,
        n_nfe_returns_ignored=notes.n_returns_ignored,
        n_nfe_items_unmatched=notes.n_unmatched,
        negative_stock_clamped=clamped,
        n_open_orders_unmatched=open_unmatched,
    )
    return ClientLoadResult(
        sales=sales,
        items=items,
        suppliers=suppliers.regular,
        stock=stock,
        audit_inputs=audit_inputs,
        purchases=purchases,
        open_orders=open_orders,
        report=report,
    )


def client_params_for(base: Params, result: ClientLoadResult) -> Params:
    """`Params` para rodar a lista de compra no modo `canonical` sobre este cliente.

    O `Params` do Favorita fixa loja, datas e validade por categoria do
    Favorita. Aqui, e só aqui (dentro de `io/`, para nada acima dele mudar),
    esses campos são DERIVADOS dos dados do cliente; o resto do `Params`
    passa intacto:

    - `guardrails.shelf_life_days_by_category`: por categoria, o MÍNIMO entre
      os itens (`validade_dias` do cadastro; sem ele, o default de config --
      perecível usa o conservador). Mínimo = a regra mais protetora.
    - `canonical.window_*` e `simulation.*`: o período dos dados. O simulador só
      roda no modo demo (sem saldo de estoque); começa
      `simulation_start_after_days` dias depois do primeiro dado.
    """
    cfg = base.client_loader
    report = result.report
    items = result.items.join(
        result.audit_inputs.select("item_id", "shelf_life_days"), on="item_id", how="left"
    )
    shelf_life: dict[str, int] = {}
    for row in items.iter_rows(named=True):
        declared = row["shelf_life_days"]
        if declared is not None:
            days = int(declared)
        elif row["is_perishable"]:
            days = cfg.default_perishable_shelf_life_days
        else:
            days = cfg.default_shelf_life_days
        category = row["category"]
        shelf_life[category] = min(days, shelf_life.get(category, days))

    last_possible_start = report.period_end - timedelta(days=1)
    start = min(
        report.period_start + timedelta(days=cfg.simulation_start_after_days), last_possible_start
    )
    warmup = base.simulation.warmup_days
    return base.model_copy(
        update={
            "guardrails": base.guardrails.model_copy(
                update={"shelf_life_days_by_category": shelf_life}
            ),
            "canonical": base.canonical.model_copy(
                update={
                    "window_start": report.period_start,
                    "window_end": report.period_end,
                    "anomalies": [],
                }
            ),
            "simulation": base.simulation.model_copy(
                update={
                    "start_date": start,
                    "evaluation_start_date": min(start + timedelta(days=warmup), report.period_end),
                    "end_date": report.period_end,
                }
            ),
        }
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Exportação do cliente -> tabelas canônicas.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--store-cnpj", required=True)
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    args = parser.parse_args(argv)

    params = load_params(args.params).client_loader
    result = load_client_tables(
        args.input_dir, params=params, store_id=args.store_id, store_cnpj=args.store_cnpj
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("sales", "items", "suppliers", "stock", "audit_inputs"):
        getattr(result, name).write_parquet(args.out_dir / f"{name}.parquet")
    (args.out_dir / "load_report.json").write_text(
        json.dumps(
            result.report.__dict__,
            default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o),
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"tabelas canônicas em {args.out_dir}")


if __name__ == "__main__":
    main()
