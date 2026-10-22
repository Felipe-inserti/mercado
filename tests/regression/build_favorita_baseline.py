"""Gera a referência da regressão do Favorita (Sprint 24, etapa 24.0).

    uv run python -m tests.regression.build_favorita_baseline [--skip-run]

Roda `erp_baseline` e `estatistico_basestock` em `results/baseline_sprint24/`
(fora do git) e grava `tests/regression/favorita_baseline.json` (versionado:
só hashes, contagens e métricas). Exige árvore git sem alterações em `src/`
e `config/` para que o `git_commit_hash` descreva o código rodado.
"""

from __future__ import annotations

import argparse
import json
import subprocess

import polars as pl

from motor.config import load_params
from motor.experiments.run import run_arm_and_save
from tests.regression.favorita import (
    ARMS,
    REFERENCE_JSON,
    REFERENCE_RESULTS_DIR,
    REPO_ROOT,
    canonical_hashes,
    params_section_hashes,
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-run", action="store_true", help="só reconstrói o JSON")
    parser.add_argument("--tests", type=int, required=True, help="testes passando (suíte padrão)")
    parser.add_argument("--skipped", type=int, required=True)
    parser.add_argument("--coverage-pct", type=int, required=True)
    args = parser.parse_args()

    dirty = _git("status", "--porcelain", "--", "src", "config")
    if dirty:
        msg = f"árvore suja, o git_commit_hash não descreveria o código rodado:\n{dirty}"
        raise SystemExit(msg)

    params = load_params(REPO_ROOT / "config" / "params.yaml")
    canonical_dir = REPO_ROOT / params.data.canonical_dir
    if not args.skip_run:
        for arm in ARMS:
            run_arm_and_save(
                arm,
                params,
                sales=pl.scan_parquet(canonical_dir / "sales.parquet"),
                items=pl.read_parquet(canonical_dir / "items.parquet"),
                suppliers=pl.read_parquet(canonical_dir / "suppliers.parquet"),
                stock=pl.read_parquet(canonical_dir / "stock.parquet"),
                subset_cache_path=REFERENCE_RESULTS_DIR / "subset_selection.json",
                canonical_dir=canonical_dir,
                results_dir=REFERENCE_RESULTS_DIR,
            )

    arms: dict[str, object] = {}
    for arm in ARMS:
        manifest = json.loads((REFERENCE_RESULTS_DIR / arm / "manifest.json").read_text())
        arms[arm] = {
            "n_items": manifest["n_items"],
            "row_counts": manifest["row_counts"],
            "portfolio": manifest["results"]["portfolio"],
        }
    reference = {
        "git_commit_hash": _git("rev-parse", "HEAD"),
        "suite": {
            "tests_passed": args.tests,
            "tests_skipped": args.skipped,
            "coverage_pct": args.coverage_pct,
        },
        "canonical_sha256": canonical_hashes(canonical_dir),
        "params_section_sha256": params_section_hashes(params),
        "arms": arms,
    }
    REFERENCE_JSON.write_text(
        json.dumps(reference, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    print(f"referência gravada em {REFERENCE_JSON}")


if __name__ == "__main__":
    main()
