"""Fronteiras de produto: imports, carga do GBM e configuração validada."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MOTOR_ROOT = REPO_ROOT / "src" / "motor"


def test_product_modules_do_not_import_experiments() -> None:
    violations: list[str] = []
    for path in sorted(MOTOR_ROOT.rglob("*.py")):
        relative = path.relative_to(MOTOR_ROOT)
        if "experiments" in relative.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    package = ("motor", *relative.parent.parts)
                    base = package[: len(package) - node.level + 1]
                    module = ".".join((*base, *module.split("."))).rstrip(".")
                imported = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            for name in imported:
                if name == "motor.experiments" or name.startswith("motor.experiments."):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}")
    assert not violations, "Produto importa experimentos:\n" + "\n".join(violations)


def _fresh_import(module: str) -> subprocess.CompletedProcess[str]:
    """Processo novo impede que imports de outros testes contaminem a verificação."""
    script = (
        "import importlib, sys; "
        f"importlib.import_module({module!r}); "
        "assert 'lightgbm' not in sys.modules, 'lightgbm carregado pelo produto'"
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_purchase_list_import_does_not_load_lightgbm() -> None:
    result = _fresh_import("motor.reporting.purchase_list")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module", ["motor.io.canonical", "motor.simulator.pair"])
def test_product_helpers_import_without_lightgbm(module: str) -> None:
    result = _fresh_import(module)
    assert result.returncode == 0, result.stdout + result.stderr


def test_reporting_and_policy_do_not_bypass_params_validation() -> None:
    violations = []
    for folder in ("reporting", "policy"):
        for path in sorted((MOTOR_ROOT / folder).rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if re.search(r"\bmodel_copy\s*\(", line):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not violations, "Cópia sem validar Params:\n" + "\n".join(violations)
