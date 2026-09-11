# Motor de decisão de compra

Motor que gera a lista de compra semanal de um supermercado, decidindo quanto
pedir de cada item respeitando as regras do fornecedor. A validação é feita
por simulação, comparando o resultado financeiro de diferentes políticas de
decisão contra a regra ingênua que um ERP usa hoje.

## Ambiente

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12.

```bash
uv sync
```

## Verificação

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```
