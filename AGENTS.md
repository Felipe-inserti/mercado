# Instruções para agentes

Leia `CLAUDE.md`: ele contém o contrato do projeto. A seção **Git** vale
para qualquer agente; commits e alterações do índice/histórico são feitos
pelo desenvolvedor, nunca pelo agente.

Verifique as mudanças com:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

Nenhum módulo fora de `src/motor/experiments/` pode importar
`motor.experiments`; confira `tests/test_architecture.py`.

Nunca regenere `tests/golden/` sem decisão humana registrada.
