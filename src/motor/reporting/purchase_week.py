"""Lista de compra da semana num arquivo só (Sprint 22): uma aba por fornecedor.

O comprador abre UM xlsx na segunda de manhã, com uma aba por fornecedor na
ordem em que ele precisa fazer os pedidos (dia de pedido, depois
`supplier_id`), mais a aba inicial "Resumo da semana". O xlsx por fornecedor
(`motor.reporting.purchase_list.write_supplier_workbook`) continua existindo.

Cada fornecedor aparece UMA vez, na sua primeira data de pedido da semana. Um
fornecedor que pede segunda e quinta tem a quinta apontada no Resumo
("próxima decisão") -- a lista dela sai com o saldo e os pedidos em aberto de
quinta, na próxima execução, não adivinhada hoje.

LIMITAÇÃO DECLARADA: `generate_purchase_list` roda uma vez por data de decisão,
então a restrição de caixa (quando há orçamento) vale por data, não sobre a
semana inteira -- o orçamento semanal não é repartido entre as datas. O custo
computacional é de uma execução do pipeline por data distinta (até 7).
"""

from __future__ import annotations

import argparse
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import xlsxwriter

from motor.config import Params, load_params
from motor.experiments.iso_service import CanonicalTables
from motor.io.loaders_cliente import client_params_for, load_client_tables
from motor.reporting.purchase_list import (
    _COLUMN_WIDTHS,
    _EXCEPTION_HEADERS,
    _MAIN_HEADERS,
    _OUTCOME_LABELS,
    DEMO_BANNER,
    CanonicalInputs,
    PurchaseListRow,
    SupplierPurchaseList,
    SupplierTerms,
    generate_purchase_list,
    write_supplier_workbook,
)

_WEEKDAYS_PT: Final[tuple[str, ...]] = (
    "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo",
)  # fmt: skip
_SHEET_NAME_MAX: Final[int] = 31
_SUMMARY_NAME: Final[str] = "Resumo da semana"
_SUMMARY_HEADERS: Final[tuple[str, ...]] = (
    "fornecedor", "dia do pedido", "resultado", "itens (lista principal)", "exceções",
    "total sugerido (R$)", "próxima decisão na semana",
)  # fmt: skip

CASH_PER_DATE_NOTE: Final[str] = (
    "A restrição de caixa, quando há orçamento, foi aplicada POR DATA DE DECISÃO (cada lista foi "
    "gerada na sua data), não sobre a semana inteira: o orçamento semanal não é repartido entre "
    "as datas."
)
FIRST_DATE_NOTE: Final[str] = (
    "Cada fornecedor aparece uma vez, na primeira data de pedido da semana. Fornecedor com mais "
    "de um dia de pedido tem a próxima decisão indicada na última coluna: a lista dela sai na "
    "data, com o saldo e os pedidos em aberto daquele dia."
)


def safe_sheet_name(raw: str, *, taken: set[str]) -> str:
    """Nome de aba válido no Excel (até 31 caracteres, sem `[ ] : * ? / \\`) e único
    entre os já usados em `taken`."""
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", raw)[:_SHEET_NAME_MAX] or "fornecedor"
    name = cleaned
    counter = 2
    while name in taken:
        suffix = f"_{counter}"
        name = cleaned[: _SHEET_NAME_MAX - len(suffix)] + suffix
        counter += 1
    return name


def generate_weekly_lists(
    week_start: date,
    *,
    base_params: Params,
    tables: CanonicalTables,
    supplier_terms: SupplierTerms = SupplierTerms.ASSUMED_CELL,
    canonical_inputs: CanonicalInputs | None = None,
) -> tuple[dict[date, dict[str, SupplierPurchaseList]], dict[str, tuple[date, ...]]]:
    """Roda a lista de compra na primeira data de pedido de cada fornecedor na semana
    `[week_start, week_start + 6]`. Devolve `(listas por data, outras datas de pedido do
    mesmo fornecedor na semana)`."""
    week = [week_start + timedelta(days=i) for i in range(7)]
    order_days = {r["supplier_id"]: r["order_days"] for r in tables.suppliers.iter_rows(named=True)}
    first_date: dict[str, date] = {}
    other_dates: dict[str, tuple[date, ...]] = {}
    for supplier_id, days in sorted(order_days.items()):
        dates = [d for d in week if d.isoweekday() in days]
        if not dates:
            continue
        first_date[supplier_id] = dates[0]
        if len(dates) > 1:
            other_dates[supplier_id] = tuple(dates[1:])

    by_date: dict[date, dict[str, SupplierPurchaseList]] = {}
    for decision_date in sorted(set(first_date.values())):
        results, _report = generate_purchase_list(
            decision_date,
            base_params=base_params,
            tables=tables,
            supplier_terms=supplier_terms,
            canonical_inputs=canonical_inputs,
        )
        by_date[decision_date] = {
            sid: lst for sid, lst in results.items() if first_date.get(sid) == decision_date
        }
    return by_date, other_dates


def _total_value(lst: SupplierPurchaseList) -> float:
    return sum(r.value_rs for r in (*lst.main, *lst.exceptions))


def _day_label(d: date) -> str:
    return f"{d.isoformat()} ({_WEEKDAYS_PT[d.weekday()]})"


def _table(
    sheet: object,
    top: int,
    rows: tuple[PurchaseListRow, ...],
    headers: tuple[str, ...],
    formats: dict[str, object],
    *,
    with_description: bool,
    empty_note: str,
) -> int:
    """Escreve um cabeçalho + linhas a partir da linha `top`; devolve a próxima linha livre."""
    offset = 1 if with_description else 0
    full = (headers[0], "descrição", *headers[1:]) if with_description else headers
    for col, header in enumerate(full):
        sheet.write(top, col, header, formats["header"])  # type: ignore[attr-defined]
    if not rows:
        sheet.write(top + 1, 0, empty_note)  # type: ignore[attr-defined]
        return top + 2
    for r, row in enumerate(rows, start=top + 1):
        sheet.write(r, 0, row.item_id)  # type: ignore[attr-defined]
        if with_description:
            sheet.write(r, 1, row.description or "")  # type: ignore[attr-defined]
        sheet.write(r, 1 + offset, row.category)  # type: ignore[attr-defined]
        sheet.write(r, 2 + offset, row.unit_of_sale)  # type: ignore[attr-defined]
        sheet.write_number(r, 3 + offset, row.quantity_units, formats["number"])  # type: ignore[attr-defined]
        sheet.write_number(r, 4 + offset, row.quantity_packs, formats["number"])  # type: ignore[attr-defined]
        sheet.write_number(r, 5 + offset, row.on_hand, formats["number"])  # type: ignore[attr-defined]
        sheet.write_number(r, 6 + offset, row.in_transit, formats["number"])  # type: ignore[attr-defined]
        if row.coverage_days_after_order is None:
            sheet.write(r, 7 + offset, "sem demanda recente")  # type: ignore[attr-defined]
        else:
            sheet.write_number(r, 7 + offset, row.coverage_days_after_order, formats["number"])  # type: ignore[attr-defined]
        sheet.write_number(r, 8 + offset, row.value_rs, formats["money"])  # type: ignore[attr-defined]
        if len(full) > 9 + offset:
            sheet.write(r, 9 + offset, "; ".join(row.adjustments))  # type: ignore[attr-defined]
    return top + 1 + len(rows)


def _write_summary_sheet(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    entries: list[tuple[date, str, SupplierPurchaseList]],
    other: dict[str, tuple[date, ...]],
    *,
    week_start: date,
    any_demo: bool,
) -> None:
    summary = workbook.add_worksheet(_SUMMARY_NAME)
    summary.set_column(0, 0, 24)
    summary.set_column(1, 1, 26)
    summary.set_column(2, 6, 22)
    r = 0
    if any_demo:
        summary.write(r, 0, DEMO_BANNER, formats["banner"])
        r += 1
    summary.write(r, 0, "LISTA DE COMPRA DA SEMANA", formats["bold"])
    summary.write(
        r + 1,
        0,
        f"Semana de {week_start.isoformat()} a {(week_start + timedelta(days=6)).isoformat()}",
    )
    r += 3
    if not entries:
        summary.write(r, 0, "Nenhum fornecedor com pedido nesta semana.")
        r += 2
    else:
        for col, header in enumerate(_SUMMARY_HEADERS):
            summary.write(r, col, header, formats["header"])
        for r_idx, (decision_date, supplier_id, lst) in enumerate(entries, start=r + 1):
            summary.write(r_idx, 0, supplier_id)
            summary.write(r_idx, 1, _day_label(decision_date))
            summary.write(r_idx, 2, _OUTCOME_LABELS[lst.outcome])
            summary.write_number(r_idx, 3, len(lst.main))
            summary.write_number(r_idx, 4, len(lst.exceptions))
            summary.write_number(r_idx, 5, _total_value(lst), formats["money"])
            summary.write(r_idx, 6, ", ".join(d.isoformat() for d in other.get(supplier_id, ())))
        r += len(entries) + 2
    for text in (FIRST_DATE_NOTE, CASH_PER_DATE_NOTE):
        summary.write(r, 0, text, formats["note"])
        summary.set_row(r, 48)
        r += 1


def write_weekly_workbook(
    lists_by_date: dict[date, dict[str, SupplierPurchaseList]],
    path: Path,
    *,
    week_start: date,
    other_order_dates: dict[str, tuple[date, ...]] | None = None,
) -> Path:
    """Grava o xlsx da semana: "Resumo da semana" + uma aba por fornecedor, em ordem de data
    de pedido e depois `supplier_id`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    other = other_order_dates or {}
    entries = sorted(
        ((d, sid, lst) for d, per_day in lists_by_date.items() for sid, lst in per_day.items()),
        key=lambda e: (e[0], e[1]),
    )
    any_demo = any(
        lst.provenance is not None and lst.provenance.simulated_stock for _, _, lst in entries
    )

    workbook = xlsxwriter.Workbook(str(path))
    formats: dict[str, object] = {
        "header": workbook.add_format(
            {"bold": True, "bg_color": "#1f3864", "font_color": "white", "border": 1}
        ),
        "money": workbook.add_format({"num_format": "R$ #,##0.00"}),
        "number": workbook.add_format({"num_format": "#,##0.00"}),
        "bold": workbook.add_format({"bold": True}),
        "note": workbook.add_format({"text_wrap": True, "valign": "top"}),
        "banner": workbook.add_format({"bold": True, "bg_color": "#c00000", "font_color": "white"}),
    }

    _write_summary_sheet(
        workbook, formats, entries, other, week_start=week_start, any_demo=any_demo
    )

    taken: set[str] = {_SUMMARY_NAME}
    for decision_date, supplier_id, lst in entries:
        name = safe_sheet_name(supplier_id, taken=taken)
        taken.add(name)
        sheet = workbook.add_worksheet(name)
        demo = lst.provenance is not None and lst.provenance.simulated_stock
        top = 0
        if demo:
            sheet.write(0, 0, DEMO_BANNER, formats["banner"])
            top = 1
        for col, width in enumerate((_COLUMN_WIDTHS[0], 36, *_COLUMN_WIDTHS[1:])):
            sheet.set_column(col, col, width)
        sheet.write(
            top,
            0,
            f"Fornecedor {supplier_id} -- decisão em {_day_label(decision_date)} -- "
            f"resultado: {_OUTCOME_LABELS[lst.outcome]}",
            formats["bold"],
        )
        with_description = any(r_.description for r_ in (*lst.main, *lst.exceptions))
        sheet.write(top + 2, 0, "Lista principal", formats["bold"])
        nxt = _table(
            sheet, top + 3, lst.main, _MAIN_HEADERS, formats,
            with_description=with_description,
            empty_note="Nenhum item nesta lista para esta data de decisão.",
        )  # fmt: skip
        sheet.write(nxt + 1, 0, "Exceções", formats["bold"])
        _table(
            sheet, nxt + 2, lst.exceptions, _EXCEPTION_HEADERS, formats,
            with_description=with_description,
            empty_note="Nenhuma exceção.",
        )  # fmt: skip
    workbook.close()
    return path


def main(argv: list[str] | None = None) -> None:
    """CLI do modo CLIENTE: exportação do cliente -> xlsx por fornecedor + arquivo da semana.

    `--week-start` (uma segunda-feira, em geral) gera a semana; `--as-of` gera uma data só.
    O modo Favorita continua em `python -m motor.reporting.purchase_list`."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--client-dir", type=Path, required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--store-cnpj", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    when = parser.add_mutually_exclusive_group(required=True)
    when.add_argument("--week-start", type=date.fromisoformat)
    when.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args(argv)

    base = load_params(args.params)
    result = load_client_tables(
        args.client_dir,
        params=base.client_loader,
        store_id=args.store_id,
        store_cnpj=args.store_cnpj,
    )
    params = client_params_for(base, result)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tables = CanonicalTables(
        sales=result.sales.lazy(),
        items=result.items,
        suppliers=result.suppliers,
        stock=result.stock,
        subset_cache_path=args.output_dir / ".subset_nao_usado_no_modo_canonical.json",
    )
    inputs = CanonicalInputs(purchases=result.purchases, open_orders=result.open_orders)
    other: dict[str, tuple[date, ...]] = {}
    if args.week_start is not None:
        week_start = args.week_start
        by_date, other = generate_weekly_lists(
            week_start,
            base_params=params,
            tables=tables,
            supplier_terms=SupplierTerms.CANONICAL,
            canonical_inputs=inputs,
        )
    else:
        week_start = args.as_of
        lists, _report = generate_purchase_list(
            week_start,
            base_params=params,
            tables=tables,
            supplier_terms=SupplierTerms.CANONICAL,
            canonical_inputs=inputs,
        )
        by_date = {week_start: lists}

    for decision_date, per_supplier in by_date.items():
        for lst in per_supplier.values():
            write_supplier_workbook(lst, as_of=decision_date, out_dir=args.output_dir)
    weekly = write_weekly_workbook(
        by_date,
        args.output_dir / f"semana_{week_start.isoformat()}.xlsx",
        week_start=week_start,
        other_order_dates=other,
    )
    n_lists = sum(len(v) for v in by_date.values())
    print(f"{n_lists} fornecedor(es) com pedido; arquivo da semana: {weekly}")
    if any(
        lst.provenance is not None and lst.provenance.simulated_stock
        for per_supplier in by_date.values()
        for lst in per_supplier.values()
    ):
        print(f"ATENÇÃO: {DEMO_BANNER} -- o cliente não enviou saldo de estoque.")


if __name__ == "__main__":
    main()
