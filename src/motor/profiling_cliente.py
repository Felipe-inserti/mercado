"""Perfil do dado do cliente (Sprint 22): o perfil da Sprint 2, sobre o dado dele.

Irmão de `motor.profiling` (Favorita, sobre `LazyFrame` bruto): aqui o
perfil sai das tabelas canônicas já normalizadas e do `LoadReport`. Funções
puras; quem imprime/grava é o chamador.

O número que decide se o dado serve para reposição é a PROPORÇÃO DO
FATURAMENTO em código genérico ("diversos"): venda lançada num código
genérico não tem item, não dá para prever, e some da lista de compra. Se for
alta, o dado não serve -- e isso é um resultado do perfil, não uma falha do
loader.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

import polars as pl

from motor.config import ClientLoaderParams
from motor.io.loaders_cliente import ClientLoadResult

VERDICT_OK: Final[str] = "ok"
VERDICT_UNFIT: Final[str] = "inadequado_para_reposicao"


@dataclass(frozen=True)
class ClientProfile:
    period_start: date
    period_end: date
    n_calendar_days: int
    n_items: int
    n_suppliers: int
    n_nfe_files: int
    closed_days: tuple[date, ...]
    share_days_with_sale: float
    """Dias com venda / dias de funcionamento, sobre as linhas do canônico (série
    densa a partir da primeira venda de cada item) -- NÃO sobre o calendário global."""
    generic_revenue_share: float
    n_cancelled_rows: int
    n_orphan_rows: int
    items_without_supplier: tuple[str, ...]
    possible_emergency_suppliers: tuple[str, ...]


def generic_revenue_verdict(share: float, *, warn: float) -> str:
    """`"ok"` até o limite (inclusive); acima dele, o dado não serve para reposição."""
    return VERDICT_OK if share <= warn else VERDICT_UNFIT


def profile_client(result: ClientLoadResult, *, params: ClientLoaderParams) -> ClientProfile:
    del params  # o veredito é aplicado na renderização; o perfil guarda só o medido
    report = result.report
    n_days = (report.period_end - report.period_start).days + 1
    operating = result.sales.filter(pl.col("is_operating_day"))
    open_days = set(operating["date"].to_list())
    closed = tuple(
        d
        for d in (report.period_start + timedelta(days=i) for i in range(n_days))
        if d not in open_days
    )
    share = (
        float((operating["units_sold"] > 0).sum()) / operating.height if operating.height else 0.0
    )
    return ClientProfile(
        period_start=report.period_start,
        period_end=report.period_end,
        n_calendar_days=n_days,
        n_items=result.items.height,
        n_suppliers=result.suppliers.height,
        n_nfe_files=report.n_nfe_files,
        closed_days=closed,
        share_days_with_sale=share,
        generic_revenue_share=report.generic_revenue_share,
        n_cancelled_rows=report.n_cancelled_rows,
        n_orphan_rows=report.n_orphan_rows,
        items_without_supplier=report.excluded_no_supplier,
        possible_emergency_suppliers=report.possible_emergency_suppliers,
    )


def render_profile(profile: ClientProfile, *, params: ClientLoaderParams) -> str:
    """Perfil em texto (markdown). O veredito do código genérico vem primeiro."""
    warn = params.generic_revenue_share_warn
    verdict = generic_revenue_verdict(profile.generic_revenue_share, warn=warn)
    lines = ["# Perfil do dado do cliente", ""]
    if verdict == VERDICT_UNFIT:
        lines.append(
            f"**Este dado não serve para reposição:** {profile.generic_revenue_share:.1%} do "
            f"faturamento está em código genérico (limite {warn:.1%}). Venda sem item não "
            "entra na previsão."
        )
    else:
        lines.append(
            f"Faturamento em código genérico: {profile.generic_revenue_share:.2%} "
            f"(limite {warn:.1%}) -- dentro do limite."
        )
    lines += [
        "",
        f"- Período coberto: {profile.period_start} a {profile.period_end} "
        f"({profile.n_calendar_days} dias)",
        f"- Itens no canônico: {profile.n_items}; fornecedores regulares: {profile.n_suppliers}; "
        f"notas fiscais lidas: {profile.n_nfe_files}",
        "- Proporção de dias com venda (dias de funcionamento): "
        f"{profile.share_days_with_sale:.1%}",
        f"- Dias sem nenhum registro (buracos de calendário): "
        f"{', '.join(str(d) for d in profile.closed_days) or 'nenhum'}",
        f"- Linhas de venda canceladas: {profile.n_cancelled_rows}; "
        f"em código sem cadastro: {profile.n_orphan_rows}",
        f"- Itens sem fornecedor (fora do canônico): "
        f"{', '.join(profile.items_without_supplier) or 'nenhum'}",
    ]
    if profile.possible_emergency_suppliers:
        lines.append(
            "- AVISO: emitentes fora da entrevista, com poucas notas -- possível compra de "
            f"emergência: {', '.join(profile.possible_emergency_suppliers)}"
        )
    return "\n".join(lines) + "\n"
