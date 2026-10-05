"""Auditoria de cadastro (Sprint 22): a primeira entrega que acha dinheiro sem modelo.

Documento de negócio, seção 5: "a auditoria de cadastro é a primeira
vitória entregável -- ela acha dinheiro na primeira semana sem modelo
nenhum". Sai das tabelas canônicas do cliente (`motor.io.loaders_cliente`)
e do que o loader decidiu (`ClientLoadResult.audit_inputs`/`report`).

As checagens, uma aba cada:

1. Margem negativa -- preço de cadastro abaixo do custo.
2. EAN e códigos duplicados -- o que o loader UNIU (DC4) e o que só aponta
   (mesmo EAN, unidade de venda diferente).
3. Custo divergente -- custo de cadastro diferente do custo da última nota
   regular (acima de `cost_divergence_tolerance`).
4. Parado com saldo -- sem venda há mais de `idle_days_threshold` dias com
   saldo positivo. Precisa da tabela `stock`: sem ela a checagem é "NÃO
   AVALIADA", e o arquivo diz isso, em vez de "0 achados".
5. Fardo -- (a) itens cuja última nota regular NÃO informa o fardo
   (`uCom == uTrib`; fonte usada: cadastro/fornecedor/desconhecido) e
   (b) itens cujo fardo do cadastro diverge do da nota (a nota vence).
6. Validade não informada -- item perecível sem `validade_dias` no cadastro
   (a lista de compra usa o default conservador de config).

Valores em R$ e margens aqui vêm do dado do cliente (custo de cadastro e de
nota). Sobre as fixtures, o arquivo traz o aviso de demonstração sobre dado
FICTÍCIO (`illustrative=True`) -- um achado de exemplo nunca se passa por
achado de cliente.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import polars as pl
import xlsxwriter

from motor.config import ClientLoaderParams, load_params
from motor.io.loaders_cliente import ClientLoadResult, load_client_tables


@dataclass(frozen=True)
class CadastreAudit:
    negative_margin: pl.DataFrame
    duplicate_ean: pl.DataFrame
    code_merges: pl.DataFrame
    repeated_codes: pl.DataFrame
    cost_divergence: pl.DataFrame
    idle_stock: pl.DataFrame
    idle_stock_evaluated: bool
    pack_unknown: pl.DataFrame
    pack_conflict: pl.DataFrame
    perishable_no_shelf_life: pl.DataFrame
    period_end: date


def _negative_margin(items: pl.DataFrame) -> pl.DataFrame:
    return (
        items.filter(pl.col("price_ref") < pl.col("cost"))
        .select(
            "item_id",
            "description",
            "price_ref",
            "cost",
            ((pl.col("price_ref") - pl.col("cost")) / pl.col("price_ref")).alias("margin_pct"),
        )
        .sort("item_id")
    )


def _duplicate_ean(items: pl.DataFrame, result: ClientLoadResult) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    merged_groups: dict[tuple[str, str], list[str]] = {}
    for m in result.report.merges:
        merged_groups.setdefault((m.ean, m.survivor), [m.survivor]).append(m.merged)
    rows.extend(
        {"ean": ean, "item_ids": sorted(ids), "merged": True}
        for (ean, _survivor), ids in merged_groups.items()
    )
    not_merged = (
        items.filter(pl.col("ean").is_not_null())
        .group_by("ean")
        .agg(pl.col("item_id").sort().alias("item_ids"))
        .filter(pl.col("item_ids").list.len() > 1)
    )
    rows.extend(
        {"ean": r["ean"], "item_ids": r["item_ids"], "merged": False}
        for r in not_merged.iter_rows(named=True)
    )
    return pl.DataFrame(
        rows,
        schema={"ean": pl.String, "item_ids": pl.List(pl.String), "merged": pl.Boolean},
    ).sort("ean")


def _cost_divergence(result: ClientLoadResult, tolerance: float) -> pl.DataFrame:
    return (
        result.audit_inputs.filter(
            pl.col("last_regular_nfe_cost").is_not_null() & (pl.col("cadastro_cost") > 0)
        )
        .with_columns(
            (pl.col("last_regular_nfe_cost") / pl.col("cadastro_cost") - 1).alias("divergence")
        )
        .filter(pl.col("divergence").abs() > tolerance)
        .join(result.items.select("item_id", "description"), on="item_id", how="left")
        .select(
            "item_id",
            "description",
            "cadastro_cost",
            pl.col("last_regular_nfe_cost").alias("last_nfe_cost"),
            "divergence",
            pl.col("last_regular_nfe_date").alias("last_nfe_date"),
        )
        .sort("item_id")
    )


def _idle_stock(result: ClientLoadResult, threshold_days: int) -> pl.DataFrame:
    period_end = result.report.period_end
    last_sale = (
        result.sales.filter(pl.col("units_sold") > 0)
        .group_by("item_id")
        .agg(pl.col("date").max().alias("last_sale"))
    )
    return (
        result.stock.filter(pl.col("on_hand") > 0)
        .join(last_sale, on="item_id", how="left")
        .with_columns(
            (pl.lit(period_end) - pl.col("last_sale").fill_null(result.report.period_start))
            .dt.total_days()
            .alias("days_since_last_sale")
        )
        .filter(pl.col("days_since_last_sale") > threshold_days)
        .join(result.items.select("item_id", "description"), on="item_id", how="left")
        .select("item_id", "description", "on_hand", "last_sale", "days_since_last_sale")
        .sort("item_id")
    )


def build_cadastre_audit(result: ClientLoadResult, *, params: ClientLoaderParams) -> CadastreAudit:
    """As seis checagens sobre o resultado do loader."""
    items = result.items
    described = items.select("item_id", "description")
    pack_unknown = (
        result.audit_inputs.filter(pl.col("nfe_pack_uninformative"))
        .join(described, on="item_id", how="left")
        .select("item_id", "description", "pack_source")
        .sort("item_id")
    )
    pack_conflict = (
        result.audit_inputs.filter(pl.col("pack_conflict"))
        .join(items.select("item_id", "description", "pack_multiple"), on="item_id", how="left")
        .select(
            "item_id", "description", "cadastro_pack", pl.col("pack_multiple").alias("nfe_pack")
        )
        .sort("item_id")
    )
    no_shelf_life = (
        items.filter(pl.col("is_perishable"))
        .join(result.audit_inputs.select("item_id", "shelf_life_days"), on="item_id", how="left")
        .filter(pl.col("shelf_life_days").is_null())
        .select("item_id", "description")
        .sort("item_id")
    )
    evaluated = result.stock.height > 0
    return CadastreAudit(
        negative_margin=_negative_margin(items),
        duplicate_ean=_duplicate_ean(items, result),
        code_merges=pl.DataFrame(
            [
                {"survivor": m.survivor, "merged": m.merged, "ean": m.ean}
                for m in result.report.merges
            ],
            schema={"survivor": pl.String, "merged": pl.String, "ean": pl.String},
        ),
        repeated_codes=pl.DataFrame(
            {"item_id": list(result.report.repeated_codes)}, schema={"item_id": pl.String}
        ),
        cost_divergence=_cost_divergence(result, params.cost_divergence_tolerance),
        idle_stock=(
            _idle_stock(result, params.idle_days_threshold)
            if evaluated
            else _idle_stock(result, params.idle_days_threshold).clear()
        ),
        idle_stock_evaluated=evaluated,
        pack_unknown=pack_unknown,
        pack_conflict=pack_conflict,
        perishable_no_shelf_life=no_shelf_life,
        period_end=result.report.period_end,
    )


# --------------------------------------------------------------------------
# xlsx
# --------------------------------------------------------------------------

_ILLUSTRATIVE_NOTICE: Final[str] = (
    "DEMONSTRAÇÃO sobre dados de exemplo FICTÍCIOS (tests/fixtures/cliente_exemplo) -- "
    "os achados abaixo foram plantados de propósito; não são achados de um cliente real."
)


def _write_frame(
    workbook: xlsxwriter.Workbook,
    name: str,
    frame: pl.DataFrame,
    headers: dict[str, str],
    *,
    empty_note: str,
    money_cols: frozenset[str] = frozenset(),
    pct_cols: frozenset[str] = frozenset(),
) -> None:
    header_fmt = workbook.add_format({"bold": True, "bg_color": "#1f3864", "font_color": "white"})
    money = workbook.add_format({"num_format": "R$ #,##0.00"})
    pct = workbook.add_format({"num_format": "0.0%"})
    sheet = workbook.add_worksheet(name)
    sheet.freeze_panes(1, 0)
    for c, col in enumerate(frame.columns):
        sheet.write(0, c, headers.get(col, col), header_fmt)
        sheet.set_column(c, c, 24)
    if frame.height == 0:
        sheet.write(1, 0, empty_note)
        return
    for r, row in enumerate(frame.iter_rows(named=True), start=1):
        for c, col in enumerate(frame.columns):
            value = row[col]
            if isinstance(value, list):
                sheet.write(r, c, ", ".join(str(v) for v in value))
            elif isinstance(value, date):
                sheet.write(r, c, value.isoformat())
            elif isinstance(value, bool):
                sheet.write(r, c, "sim" if value else "não")
            elif isinstance(value, float):
                fmt = money if col in money_cols else pct if col in pct_cols else None
                sheet.write_number(r, c, value, fmt)
            elif value is None:
                sheet.write(r, c, "")
            else:
                sheet.write(r, c, value)


def write_audit_workbook(audit: CadastreAudit, path: Path, *, illustrative: bool) -> Path:
    """Um xlsx com `Resumo` e uma aba por checagem. `illustrative=True` grava
    o aviso de que os achados são de dado de exemplo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(path))
    bold = workbook.add_format({"bold": True})
    note = workbook.add_format({"text_wrap": True, "italic": True})

    summary = workbook.add_worksheet("Resumo")
    summary.set_column(0, 0, 52)
    summary.set_column(1, 1, 18)
    summary.write(0, 0, "AUDITORIA DE CADASTRO", bold)
    summary.write(1, 0, f"Data de referência: {audit.period_end.isoformat()}")
    row = 2
    if illustrative:
        summary.write(row, 0, _ILLUSTRATIVE_NOTICE, note)
        summary.set_row(row, 45)
        row += 1
    row += 1
    idle_count: int | str = (
        audit.idle_stock.height
        if audit.idle_stock_evaluated
        else "não avaliado (sem tabela de estoque)"
    )
    for label, count in (
        ("Margem negativa (itens)", audit.negative_margin.height),
        ("EAN duplicado (grupos)", audit.duplicate_ean.height),
        ("Código repetido no cadastro (itens)", audit.repeated_codes.height),
        ("Custo de cadastro ≠ última nota (itens)", audit.cost_divergence.height),
        ("Parado com saldo (itens)", idle_count),
        ("Fardo que a nota não informa (itens)", audit.pack_unknown.height),
        ("Fardo do cadastro diverge da nota (itens)", audit.pack_conflict.height),
        ("Perecível sem validade informada (itens)", audit.perishable_no_shelf_life.height),
    ):
        summary.write(row, 0, label)
        if isinstance(count, int):
            summary.write_number(row, 1, count)
        else:
            summary.write(row, 1, count)
        row += 1

    _write_frame(
        workbook,
        "Margem negativa",
        audit.negative_margin,
        {
            "item_id": "código",
            "description": "descrição",
            "price_ref": "preço de venda",
            "cost": "custo",
            "margin_pct": "margem",
        },
        empty_note="Nenhum item com preço abaixo do custo.",
        money_cols=frozenset({"price_ref", "cost"}),
        pct_cols=frozenset({"margin_pct"}),
    )
    _write_frame(
        workbook,
        "EAN e códigos duplicados",
        audit.duplicate_ean,
        {"ean": "EAN", "item_ids": "códigos", "merged": "unido pelo loader"},
        empty_note="Nenhum EAN duplicado.",
    )
    _write_frame(
        workbook,
        "Custo divergente",
        audit.cost_divergence,
        {
            "item_id": "código",
            "description": "descrição",
            "cadastro_cost": "custo de cadastro",
            "last_nfe_cost": "custo da última nota",
            "divergence": "diferença",
            "last_nfe_date": "data da nota",
        },
        empty_note="Nenhum item com custo de cadastro fora da tolerância.",
        money_cols=frozenset({"cadastro_cost", "last_nfe_cost"}),
        pct_cols=frozenset({"divergence"}),
    )
    _write_frame(
        workbook,
        "Parado com saldo",
        audit.idle_stock,
        {
            "item_id": "código",
            "description": "descrição",
            "on_hand": "saldo",
            "last_sale": "última venda",
            "days_since_last_sale": "dias sem venda",
        },
        empty_note=(
            "Nenhum item parado com saldo."
            if audit.idle_stock_evaluated
            else "Checagem não avaliado: o cliente não enviou saldo de estoque. "
            "Isso não significa zero achados."
        ),
    )
    pack = pl.concat(
        [
            audit.pack_unknown.select(
                "item_id",
                "description",
                pl.lit("a nota não informa o fardo (uCom = uTrib)").alias("situação"),
                pl.col("pack_source").alias("fonte usada"),
            ),
            audit.pack_conflict.select(
                "item_id",
                "description",
                pl.lit("fardo do cadastro diverge da nota (a nota vence)").alias("situação"),
                pl.lit("nota").alias("fonte usada"),
            ),
        ]
    )
    _write_frame(
        workbook,
        "Fardo",
        pack,
        {"item_id": "código", "description": "descrição"},
        empty_note="Nenhum item com fardo indefinido ou divergente.",
    )
    _write_frame(
        workbook,
        "Validade não informada",
        audit.perishable_no_shelf_life,
        {"item_id": "código", "description": "descrição"},
        empty_note="Todo item perecível tem validade informada.",
    )
    workbook.close()
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Auditoria de cadastro do cliente (xlsx).")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--store-cnpj", required=True)
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    parser.add_argument("--illustrative", action="store_true", help="dado de exemplo fictício")
    args = parser.parse_args(argv)
    params = load_params(args.params).client_loader
    result = load_client_tables(
        args.input_dir, params=params, store_id=args.store_id, store_cnpj=args.store_cnpj
    )
    path = write_audit_workbook(
        build_cadastre_audit(result, params=params), args.output, illustrative=args.illustrative
    )
    print(f"auditoria salva em {path}")


if __name__ == "__main__":
    main()
