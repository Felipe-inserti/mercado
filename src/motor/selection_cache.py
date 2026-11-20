"""Cache validado do subconjunto, compartilhado por produto e experimentos."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

from motor.config import Params
from motor.selection import SubsetSelectionResult, select_subset


class StaleSubsetSelectionError(RuntimeError):
    """O cache de subconjunto em disco foi calculado com outros parâmetros de
    seleção -- reusar em silêncio esconderia uma mudança em `params.yaml` que
    deveria invalidar o subconjunto (ajuste da revisão da Sprint 7). A
    correção é apagar o cache ou rodar a seleção de novo antes de continuar,
    nunca ignorar a divergência.
    """


def _selection_params_hash(params: Params) -> str:
    """Hash determinístico só dos campos de `Params` que afetam
    `select_subset` -- não o arquivo inteiro: mudar `erp_baseline.factor`,
    por exemplo, não deveria invalidar um subconjunto que não depende disso.

    Escopo DIFERENTE do `params_hash` do `RunManifest` (Sprint 9) -- aquele
    hasheia `Params` inteiro, pra rastreabilidade; este hasheia só o que
    decide o subconjunto, pra servir de gatilho de cache. Mesmo nome de
    campo (`params_hash`) em dois arquivos, escopos diferentes de propósito
    -- não comparar um contra o outro.
    """
    payload = {
        "subset_selection": params.subset_selection.model_dump(mode="json"),
        "canonical_window_start": params.canonical.window_start.isoformat(),
        "canonical_window_end": params.canonical.window_end.isoformat(),
        "simulation_start_date": params.simulation.start_date.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_or_select_subset(
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    stock: pl.DataFrame,
    params: Params,
    *,
    cache_path: Path,
) -> SubsetSelectionResult:
    """Lê `cache_path` se existir e o hash bater; senão roda `select_subset`
    (que escaneia a tabela de vendas inteira) e grava o cache pra próxima vez.

    Levanta `StaleSubsetSelectionError` se o cache existir com um hash
    diferente do calculado agora -- nunca reusa em silêncio.
    """
    current_hash = _selection_params_hash(params)

    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached["params_hash"] != current_hash:
            msg = (
                f"{cache_path} foi calculado com outros parâmetros de seleção "
                f"(hash salvo {cached['params_hash']!r} != hash atual {current_hash!r}). "
                "config/params.yaml mudou desde a última seleção -- apague o "
                "cache ou rode a seleção de novo antes de continuar; reusar em "
                "silêncio compararia braços com subconjuntos diferentes."
            )
            raise StaleSubsetSelectionError(msg)
        return SubsetSelectionResult(
            store_id=cached["store_id"],
            item_ids=tuple(cached["item_ids"]),
            funnel=pl.DataFrame(cached["funnel"]),
        )

    result = select_subset(sales, items, suppliers, stock, params)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "params_hash": current_hash,
                "store_id": result.store_id,
                "item_ids": list(result.item_ids),
                "funnel": result.funnel.to_dicts(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return result
