"""Relatório de qualidade do dado de entrada (Sprint 24, etapa 24.6).

Roda sobre as tabelas canônicas -- não conhece o formato do mercado -- e diz,
antes de qualquer modelo, o quanto o dado merece confiança: seis verificações,
cada uma devolvendo ocorrências (`tipo`, `item_id`, `date`, `valor`,
`descricao`). O relatório agrega por tipo: quantidade, % sobre as linhas da
tabela verificada, cinco exemplos, e marca como CRÍTICO acima de
`mercado_piloto.qualidade.limite_percentual_critico`.

Verificação sem dado para rodar aparece como NÃO AVALIADA, com o motivo --
nunca como zero ocorrências. "Zero" diz que o dado está limpo; "não avaliada"
diz que ninguém olhou. Confundir as duas é o erro que este módulo existe para
evitar.

A verificação 3 (dia sem venda em item regular) REUSA
`motor.features.censoring.flag_probable_stockout`: é exatamente o mesmo padrão
(zero num item que costuma vender, sem entrada recente), só com a definição de
"regular" tirada de `mercado_piloto.qualidade`, não dos limiares da censura.

`stock` não é entrada: nenhuma das seis verificações o usa, e saldo de estoque
fica fora até haver dado real com saldo (Emenda da Sprint 15 do CLAUDE.md).
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import polars as pl
import xlsxwriter

from motor.config import CensuraParams, Params, QualidadeParams
from motor.features.censoring import flag_probable_stockout

_OCCURRENCE_SCHEMA: Final = {
    "tipo": pl.String,
    "item_id": pl.String,
    "date": pl.Date,
    "valor": pl.String,
    "descricao": pl.String,
}
_N_EXAMPLES: Final = 5

NOT_EVALUATED: Final = "não avaliada"
EVALUATED: Final = "avaliada"

# tipo -> título legível (usado no resumo da dona e no nome da aba)
CHECK_TITLES: Final = {
    "descricao_divergente": "Código com mais de uma descrição",
    "devolucao_sem_venda": "Devolução sem venda correspondente",
    "dia_sem_venda_item_regular": "Dia sem venda em item de venda regular",
    "unidade_divergente": "Código com unidades de venda diferentes",
    "recebimento_antes_do_pedido": "Recebimento antes do pedido",
    "cadastro_incompleto": "Item ativo sem fardo ou sem validade",
}


@dataclass(frozen=True)
class CheckResult:
    """Resultado de UMA verificação.

    `status == "não avaliada"`: `count`/`pct` são `None` e `reason` diz por quê.
    `pct`: ocorrências / `base_rows` (linhas da tabela verificada).
    """

    tipo: str
    title: str
    status: str
    reason: str | None
    base_rows: int
    count: int | None
    pct: float | None
    critical: bool
    examples: pl.DataFrame
    occurrences: pl.DataFrame
    note: str | None = None


@dataclass(frozen=True)
class QualityReport:
    checks: tuple[CheckResult, ...]
    limite_percentual_critico: float

    def check(self, tipo: str) -> CheckResult:
        return next(c for c in self.checks if c.tipo == tipo)


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=_OCCURRENCE_SCHEMA)


def _occurrences(tipo: str, rows: Sequence[tuple[str, date | None, str, str]]) -> pl.DataFrame:
    """Linhas `(item_id, date, valor, descricao)` -> tabela de ocorrências."""
    if not rows:
        return _empty()
    return pl.DataFrame(
        {
            "tipo": [tipo] * len(rows),
            "item_id": [r[0] for r in rows],
            "date": [r[1] for r in rows],
            "valor": [r[2] for r in rows],
            "descricao": [r[3] for r in rows],
        },
        schema=_OCCURRENCE_SCHEMA,
    )


def _evaluated(
    tipo: str, occurrences: pl.DataFrame, base_rows: int, limit: float, note: str | None = None
) -> CheckResult:
    count = occurrences.height
    pct = count / base_rows if base_rows > 0 else 0.0
    return CheckResult(
        tipo=tipo,
        title=CHECK_TITLES[tipo],
        status=EVALUATED,
        reason=None,
        base_rows=base_rows,
        count=count,
        pct=pct,
        critical=pct > limit,
        examples=occurrences.head(_N_EXAMPLES),
        occurrences=occurrences,
        note=note,
    )


def _not_evaluated(tipo: str, reason: str, base_rows: int) -> CheckResult:
    return CheckResult(
        tipo=tipo,
        title=CHECK_TITLES[tipo],
        status=NOT_EVALUATED,
        reason=reason,
        base_rows=base_rows,
        count=None,
        pct=None,
        critical=False,
        examples=_empty(),
        occurrences=_empty(),
    )


# --------------------------------------------------------------------------
# verificações -- cada uma devolve só as ocorrências
# --------------------------------------------------------------------------


def _check_divergent_values(
    items: pl.DataFrame, column: str, tipo: str, label: str
) -> pl.DataFrame:
    """Código (`item_id`) com mais de um valor distinto em `column`."""
    divergent = (
        items.filter(pl.col(column).is_not_null())
        .group_by("item_id")
        .agg(pl.col(column).cast(pl.String).unique().sort().alias("_valores"))
        .filter(pl.col("_valores").list.len() > 1)
        .sort("item_id")
    )
    rows = [
        (
            r["item_id"],
            None,
            " | ".join(r["_valores"]),
            f"O código {r['item_id']} aparece com {label} diferentes.",
        )
        for r in divergent.iter_rows(named=True)
    ]
    return _occurrences(tipo, rows)


def _check_returns_without_sale(sales: pl.DataFrame, window_days: int) -> pl.DataFrame:
    """Linha com `units_returned > 0` sem nenhuma venda (`units_sold > 0`) do
    mesmo loja-item nos `window_days` dias ANTERIORES à devolução."""
    returns = sales.filter(pl.col("units_returned") > 0).sort("store_id", "item_id", "date")
    if returns.height == 0:
        return _empty()
    sale_dates: dict[tuple[str, str], list[date]] = {}
    for key, frame in (
        sales.filter(pl.col("units_sold") > 0)
        .sort("date")
        .group_by("store_id", "item_id", maintain_order=True)
    ):
        sale_dates[(str(key[0]), str(key[1]))] = frame["date"].to_list()

    rows: list[tuple[str, date | None, str, str]] = []
    for r in returns.iter_rows(named=True):
        dates = sale_dates.get((r["store_id"], r["item_id"]), [])
        start = r["date"] - timedelta(days=window_days)
        first_in_window = bisect_left(dates, start)
        has_sale = first_in_window < len(dates) and dates[first_in_window] < r["date"]
        if not has_sale:
            rows.append(
                (
                    r["item_id"],
                    r["date"],
                    f"{r['units_returned']:g}",
                    f"Devolução de {r['units_returned']:g} un. sem venda do item nos "
                    f"{window_days} dias anteriores.",
                )
            )
    return _occurrences("devolucao_sem_venda", rows)


def _regularity_params(quality: QualidadeParams, censura: CensuraParams) -> CensuraParams:
    """Traduz "item regular" de `mercado_piloto.qualidade` para os parâmetros de
    `flag_probable_stockout`: janela de regularidade; mínimo de dias com venda =
    `percentual_dias_com_venda_regular` da janela; sem média mínima (a regra de
    dias com venda já a implica)."""
    return CensuraParams(
        ativa=True,
        janela_dias=quality.janela_regularidade_dias,
        media_minima_por_dia=0.0,
        dias_minimos_com_venda=max(
            1,
            math.ceil(quality.percentual_dias_com_venda_regular * quality.janela_regularidade_dias),
        ),
        dias_sem_entrada_antes=censura.dias_sem_entrada_antes,
        alerta_percentual_dias_censurados=censura.alerta_percentual_dias_censurados,
    )


def _check_zero_day_in_regular_item(
    sales: pl.DataFrame,
    entries: pl.DataFrame | None,
    quality: QualidadeParams,
    censura: CensuraParams,
) -> pl.DataFrame:
    flags = flag_probable_stockout(sales, entries, _regularity_params(quality, censura))
    rows = [
        (
            r["item_id"],
            r["date"],
            "0",
            "Dia sem nenhuma venda em item que vende quase todo dia"
            + (
                ", sem recebimento recente."
                if entries is not None
                else " (recebimentos não informados)."
            ),
        )
        for r in flags.filter(pl.col("is_censored")).sort("item_id", "date").iter_rows(named=True)
    ]
    return _occurrences("dia_sem_venda_item_regular", rows)


def _check_receipt_before_order(entries: pl.DataFrame) -> pl.DataFrame:
    bad = entries.filter(
        pl.col("order_date").is_not_null() & (pl.col("received_date") < pl.col("order_date"))
    ).sort("item_id", "received_date")
    rows = [
        (
            r["item_id"],
            r["received_date"],
            f"{r['received_date']} < {r['order_date']}",
            f"Recebido em {r['received_date']}, antes do pedido de {r['order_date']}.",
        )
        for r in bad.iter_rows(named=True)
    ]
    return _occurrences("recebimento_antes_do_pedido", rows)


def _active_items(sales: pl.DataFrame, window_days: int) -> pl.DataFrame:
    """Itens com venda (`units_sold > 0`) nos últimos `window_days` dias do `sales`."""
    last_day = sales["date"].max()
    assert isinstance(last_day, date)
    start = last_day - timedelta(days=window_days - 1)
    return (
        sales.filter((pl.col("date") >= start) & (pl.col("units_sold") > 0))
        .select("item_id")
        .unique()
    )


# --------------------------------------------------------------------------
# agregação
# --------------------------------------------------------------------------


def build_quality_report(
    sales: pl.DataFrame,
    items: pl.DataFrame,
    *,
    entries: pl.DataFrame | None = None,
    params: Params,
) -> QualityReport:
    """Seis verificações sobre `sales`/`items` (e `entries`, se houver).

    `entries` é opcional: sem ele a verificação 5 fica "não avaliada" e a 3
    roda sem a condição de entrada (a descrição da ocorrência diz isso).
    """
    quality = params.mercado_piloto.qualidade
    censura = params.mercado_piloto.censura
    limit = quality.limite_percentual_critico
    n_sales, n_items = sales.height, items.height
    checks: list[CheckResult] = []

    checks.append(
        _evaluated(
            "descricao_divergente",
            _check_divergent_values(items, "description", "descricao_divergente", "descrições"),
            n_items,
            limit,
        )
    )

    if "units_returned" in sales.columns and sales["units_returned"].null_count() < n_sales:
        checks.append(
            _evaluated(
                "devolucao_sem_venda",
                _check_returns_without_sale(sales, quality.janela_devolucao_dias),
                n_sales,
                limit,
            )
        )
    else:
        checks.append(
            _not_evaluated(
                "devolucao_sem_venda", "a tabela de vendas não informa devoluções", n_sales
            )
        )

    checks.append(
        _evaluated(
            "dia_sem_venda_item_regular",
            _check_zero_day_in_regular_item(sales, entries, quality, censura),
            n_sales,
            limit,
        )
    )

    checks.append(
        _evaluated(
            "unidade_divergente",
            _check_divergent_values(
                items, "unit_of_sale", "unidade_divergente", "unidades de venda"
            ),
            n_items,
            limit,
        )
    )

    if entries is None:
        checks.append(
            _not_evaluated("recebimento_antes_do_pedido", "não há tabela de recebimentos", 0)
        )
    elif entries["order_date"].null_count() == entries.height:
        checks.append(
            _not_evaluated(
                "recebimento_antes_do_pedido",
                "os recebimentos não trazem a data do pedido",
                entries.height,
            )
        )
    else:
        checks.append(
            _evaluated(
                "recebimento_antes_do_pedido",
                _check_receipt_before_order(entries),
                entries.height,
                limit,
            )
        )

    checks.append(_check_incomplete_registry(sales, items, quality, limit))
    return QualityReport(checks=tuple(checks), limite_percentual_critico=limit)


def _check_incomplete_registry(
    sales: pl.DataFrame, items: pl.DataFrame, quality: QualidadeParams, limit: float
) -> CheckResult:
    """Item ativo sem fardo (`pack_multiple`). O cadastro canônico não tem campo
    de validade: essa metade da verificação é "não avaliada" e o resumo diz isso.
    Crítico também se o % de cadastro completo ficar abaixo de
    `cadastro_minimo_completo`."""
    tipo = "cadastro_incompleto"
    active = _active_items(sales, quality.janela_regularidade_dias)
    # um item por código (cadastro com linhas repetidas não conta duas vezes);
    # "sem fardo" = nenhuma das linhas do código traz `pack_multiple`.
    registry = (
        items.join(active, on="item_id", how="inner")
        .group_by("item_id")
        .agg(pl.col("pack_multiple").is_not_null().any().alias("_has_pack"))
    )
    missing = registry.filter(~pl.col("_has_pack")).sort("item_id")
    rows = [
        (
            r["item_id"],
            None,
            "sem fardo",
            f"Item ativo {r['item_id']} sem múltiplo de fardo cadastrado.",
        )
        for r in missing.iter_rows(named=True)
    ]
    occurrences = _occurrences(tipo, rows)
    n_active = registry.height
    complete = 1.0 - missing.height / n_active if n_active else 1.0
    result = _evaluated(
        tipo,
        occurrences,
        n_active,
        limit,
        note=(
            f"Cadastro completo (fardo): {complete:.1%} dos itens ativos "
            f"(mínimo exigido {quality.cadastro_minimo_completo:.0%}). "
            "Validade: não avaliada -- o cadastro não tem campo de validade."
        ),
    )
    if complete < quality.cadastro_minimo_completo:
        return CheckResult(**{**result.__dict__, "critical": True})
    return result


# --------------------------------------------------------------------------
# exportação
# --------------------------------------------------------------------------


def _sheet_name(title: str, used: set[str]) -> str:
    name = title[:31]
    for bad in "[]:*?/\\":
        name = name.replace(bad, " ")
    base, n = name, 2
    while name in used:
        name = f"{base[:28]} {n}"
        n += 1
    used.add(name)
    return name


def export_quality_report_xlsx(report: QualityReport, path: Path) -> Path:
    """Grava o relatório em xlsx: aba "Resumo" legível pela dona (português,
    sem nome técnico de coluna) e uma aba por tipo de verificação."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with xlsxwriter.Workbook(path) as workbook:
        header = workbook.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})
        wrap = workbook.add_format({"text_wrap": True, "valign": "top"})
        red = workbook.add_format({"bold": True, "font_color": "#9C0006", "bg_color": "#FFC7CE"})
        grey = workbook.add_format({"italic": True, "font_color": "#595959"})
        pct_fmt = workbook.add_format({"num_format": "0.0%"})

        used: set[str] = set()
        summary = workbook.add_worksheet(_sheet_name("Resumo", used))
        summary.set_column(0, 0, 44)
        summary.set_column(1, 1, 14)
        summary.set_column(2, 3, 16)
        summary.set_column(4, 4, 70)
        for col, label in enumerate(
            ["Verificação", "Situação", "Quantidade", "% das linhas", "Observação"]
        ):
            summary.write(0, col, label, header)

        tabs: list[tuple[CheckResult, str]] = []
        for row, check in enumerate(report.checks, start=1):
            tabs.append((check, _sheet_name(check.title, used)))
            summary.write(row, 0, check.title, wrap)
            if check.status == NOT_EVALUATED:
                summary.write(row, 1, "Não avaliada", grey)
                summary.write(row, 4, f"Não foi possível verificar: {check.reason}.", wrap)
                continue
            summary.write(
                row, 1, "CRÍTICO" if check.critical else "OK", red if check.critical else None
            )
            summary.write(row, 2, check.count)
            summary.write(row, 3, check.pct, pct_fmt)
            summary.write(row, 4, check.note or "", wrap)

        for check, name in tabs:
            sheet = workbook.add_worksheet(name)
            sheet.set_column(0, 0, 14)
            sheet.set_column(1, 1, 12)
            sheet.set_column(2, 2, 26)
            sheet.set_column(3, 3, 80)
            if check.status == NOT_EVALUATED:
                sheet.write(0, 0, f"Não avaliada: {check.reason}.", grey)
                continue
            for col, label in enumerate(["Código do item", "Data", "Valor", "O que aconteceu"]):
                sheet.write(0, col, label, header)
            for row, occ in enumerate(check.occurrences.iter_rows(named=True), start=1):
                sheet.write(row, 0, occ["item_id"])
                sheet.write(row, 1, occ["date"].isoformat() if occ["date"] else "")
                sheet.write(row, 2, occ["valor"])
                sheet.write(row, 3, occ["descricao"], wrap)
    return path
