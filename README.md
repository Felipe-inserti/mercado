# Motor de decisão de compra

Motor que gera a lista de compra semanal de um supermercado, decidindo quanto
pedir de cada item respeitando as regras do fornecedor. A validação é feita
por simulação, comparando o resultado financeiro de diferentes políticas de
decisão contra a regra ingênua que um ERP usa hoje.

## Ambiente

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12.

```bash
uv sync --locked
```

## Verificação

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

O mypy roda em modo strict; o piso de cobertura é 85%. O CI executa esses
checks em push e pull_request. O contrato completo está em [CLAUDE.md](CLAUDE.md)
e as instruções para agentes em [AGENTS.md](AGENTS.md).

## Estrutura e camadas

- `config/params.yaml`: premissas e configuração validada por `motor.config`.
- `src/motor/io/`: contratos, bruto, canônico, overrides e qualidade dos dados.
- `selection.py` / `selection_cache.py`: seleção e cache de subconjunto.
- `features/`, `forecast/`, `policy/`: histórico, previsão e decisão.
- `inventory.py` / `simulator/`: estoque, loop diário e montagem por par.
- `metrics/`: métricas financeiras e qualidade da previsão.
- `reporting/purchase_list.py`: lista de compra por fornecedor e Excel.
- `experiments/`: comparação de braços, sensibilidade, iso-serviço e
  `monthly_report.py` (relatório mensal dos experimentos).
- `tests/`: testes sintéticos, arquitetura e golden; `notebooks/`: exploração.
- `docs/`: histórico das sprints, decisões pendentes e pacote de coleta.

Nenhum módulo fora de `src/motor/experiments/` importa `motor.experiments`.
Experimentos podem importar produto. `tests/test_architecture.py` garante
essa direção e que importar a lista, o canônico ou o simulador por par não
carrega LightGBM. Nunca regenerar `tests/golden/` sem decisão humana registrada.

## Gerar a lista de compra

Com os quatro parquet canônicos disponíveis no diretório configurado:

```bash
uv run python -m motor.reporting.purchase_list \
  --params config/params.yaml \
  --as-of 2016-11-28 \
  --output-dir /tmp/listas-compra
```

A data acima é exemplo do Favorita. Use data e configuração adequadas ao
dado disponível. A saída é um XLSX por fornecedor com lista principal,
exceções e notas das premissas. `purchase_list` configura alpha, overrides
de prazo e período do orçamento; override `null` usa o cadastro do próprio
fornecedor. Os valores atuais 0,66 e 7/14 são herdados do experimento e
precisam de revisão com dado real. A CLI também oferece
`--weekly-budget-rs` para estresse explícito, validado e declarado na saída.

## Piloto e regressão

As [decisões em aberto](docs/decisoes_em_aberto.md) têm responsáveis e
evidência necessária. O [roteiro de coleta](docs/coleta/roteiro_exportacao.md),
o [dicionário](docs/coleta/dicionario_de_dados.md) e os
[CSV fictícios](docs/coleta/modelos/) orientam a exportação do ERP.
O adaptador do mercado e o backtest 24.7 ainda não estão no repositório.

A regressão do Favorita roda **somente onde existe `data/` com os arquivos
necessários**, além da referência em `results/baseline_sprint24/`:

```bash
uv run pytest -m regression --no-cov tests/test_regression_favorita.py
```

Ela fica fora do pytest padrão e do CI. Os testes comuns usam dados
sintéticos. Consulte [Sprint 25](docs/sprints/sprint25.md) para resultados,
limitações da auditoria e verificações de preservação do golden.
