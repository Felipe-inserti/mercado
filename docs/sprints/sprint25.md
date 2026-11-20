# Sprint 25 — Motor pronto para o dado real

Execução parcial em **20/11/2026**, limitada às **Fases 0 e 1**, conforme pedido
do Rafael. Especificação: `PROMPT_CODEX_sprint25.md`. Fases 2 a 13 fora desta
rodada; `EXECUTAR_FASE_BACKTEST: não`. Nenhum commit executado.

Vale o contrato de `CLAUDE.md`, exceto graphify (inexistente nesta máquina), e
as regras R1–R14 da especificação. A autorização explícita para executar as
Fases 0 e 1 já define o desenho: apenas fixture, golden, testes e este registro;
nenhum módulo de produto será alterado.

## Estado de partida — Fase 0

- Branch conferida antes das demais ações desta rodada: `feat/correcoes-motor`.
- `git status --short` inicial: vazio (árvore limpa).
- Leitura obrigatória concluída, na ordem da seção 2 da especificação:
  `CLAUDE.md`, Sprint 24, configuração, módulos indicados e regressão,
  `pyproject.toml` e `.gitignore`.
- Comandos `uv run` usam `UV_NO_SYNC=1`, `UV_NO_CACHE=1` e
  `PYTHONDONTWRITEBYTECODE=1`: ambiente existente, sem sincronizar/escrever em
  `.venv/`, nem alterar dependências. As flags não alteram a seleção de testes.

| Comando | Resultado real |
|---|---|
| `uv run pytest -q --cov=motor --cov-branch --cov-report=term-missing` | **451 passed, 1 skipped, 3 deselected, 1 xfailed in 10.78s**; 0 falhas/erros |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `91 files already formatted` |
| `uv run mypy src/` | `Success: no issues found in 43 source files` |
| `uv run pytest -q` (fechamento da Fase 0) | **451 passed, 1 skipped, 3 deselected, 1 xfailed in 10.15s**; cobertura de linhas **79% / 63% / 32%** (total / lista / mensal) |

O comando com `--cov-branch` reportou **78% total**, **61% purchase_list.py**
e **28% monthly_report.py** (linhas e desvios combinados). Para comparar com
as metas de linhas, leitura da mesma base `.coverage` pela API do coverage:

| Cobertura de linhas | Executadas / total | Percentual |
|---|---:|---:|
| Total | 3159 / 4010 | 78,7781% |
| `reporting/purchase_list.py` | 215 / 341 | 63,0499% |
| `reporting/monthly_report.py` | 105 / 330 | 31,8182% |

Inventário de partida: **39 linhas com `type: ignore` em `src/`**, **6
importações AST de produto para `motor.experiments`**, **4 instruções `assert`
em `src/`**. Vulnerabilidades não auditadas nesta rodada (Fase 9 fora do escopo).
O pytest emitiu `CoverageWarning: Module motor was previously imported, but
not measured`; resultado registrado sem suprimir o aviso.

**Regressão do Favorita: não executável nesta máquina (Felipe roda).**
Verificada a ausência dos quatro arquivos `sales.parquet`, `items.parquet`,
`suppliers.parquet`, `stock.parquet` em `data/canonical/favorita/`.
Nenhum dado foi criado nem alterado.

**Fase 0 concluída.** Os quatro comandos obrigatórios passaram. O teste
preexistente pulado exige `suppliers.parquet`; o `xfail` preexistente é a
pendência do alpha, a ser tratada somente na Fase 2.

## Fase 1 — Caracterização da lista de compra

**Concluída, antes de qualquer refatoração de produto.**

### Desenho e arquivos criados

- Fase 0: `docs/sprints/sprint25.md` (este registro, atualizado na Fase 1).
- Fase 1: `tests/purchase_list_fixtures.py`: quatro fornecedores, doze itens
  fictícios, categorias `GROCERY I`, `PRODUCE`, `EGGS`, `BEVERAGES`;
  **5.640 linhas de vendas em memória**, 470 dias por item. São 364 dias de
  treino antes de `simulation.start_date`, mais 106 dias de simulação
  disponíveis antes da decisão de **28/11/2016**; warmup de 90 dias completo.
  Tabelas com schemas derivados dos contratos, validadas inclusive por chave
  primária, integridade referencial e cadência de fornecedor. `stock` vazio,
  tipado pelo contrato. Cache válido escrito só em `tmp_path`, com
  `_selection_params_hash`; os testes verificam sua leitura sem regravação.
- Fase 1: `tests/golden/purchase_list_synthetic.json`: saída integral de
  `generate_purchase_list`, fornecedores e linhas ordenados, floats
  arredondados a seis casas, textos de ajustes preservados, contagens das
  quatro guardas, regras não implementadas e eventual alerta dos pisos.
- Fase 1: `tests/test_purchase_list_characterization.py`: **13 testes novos**
  (contando parametrizações), incluindo quatro comparações integrais com o
  golden e asserções explícitas dos caminhos abaixo. Cada cenário roda uma
  vez por módulo; nenhum mock de previsão, política, simulação ou guardas.

Não houve arquivo existente de código/teste alterado, nem arquivo movido.

### Cenários congelados

| Cenário | Entrada específica | Resultado caracterizado |
|---|---|---|
| `default` | `load_params` intacto | Lista principal, exceções, duas substituições de item novo, variação, teto e mínimo inatingível |
| `cash_limited` | Orçamento sintético R$ 3.500/semana (R$ 7.000/ciclo) | Cortes com pisos por categoria preservados, sem alerta |
| `cash_below_floors` | Orçamento sintético R$ 2.000/semana (R$ 4.000/ciclo) | Cortes e alerta: pisos de R$ 5.313,60; insuficiência de R$ 1.313,60 |
| `minimum_filled` | Só vendas sintéticas de `E-ONE`/`E-TWO` passam a 13 un./dia | Preenchimento bem-sucedido do mínimo: 126 e 120 unidades, R$ 2.041,80 |

Os dois orçamentos são exclusivamente valores de teste. Objetos derivados
com `Params.model_validate(payload)` após `model_dump()`, sem
`model_copy(update=...)`. Um teste revalida todos os objetos e verifica que
repor o orçamento original recupera exatamente o `Params` carregado do YAML.
Todos os demais campos, inclusive os quatro `null`, permanecem intactos.

| Caminho da meta da Fase 1 | Evidência no golden e nos asserts | Coberto |
|---|---|---|
| Pedido emitido | `SUP-GROCERY`, linha principal `G-REGULAR`: 72 un., 6 fardos, R$ 590,40 | Sim |
| Fornecedor fora do calendário | `SUP-CLOSED` só aceita terça; decisão segunda: ausente nos quatro snapshots, incluindo seus dois itens | Sim |
| Linha de exceção | `G-NEW`/`G-SURGE`, separação de principal/exceções e motivos; mínimo adiado em `SUP-EGGS` | Sim |
| Item novo | `G-NEW`: mediana 52,50 -> 60 un. por fardo; `P-NEVER`: sem vendas, mediana pós-teto -> 185 un. | Sim |
| Limite de variação | `G-SURGE`: 286,78 un., 6,8x a compra média; sinalização sem corte, depois fardo -> 288 un. | Sim |
| Teto de cobertura | `P-TREND`: corte real de 350 para 298,55 un., depois fardo -> 299; conflito validade/janela também registrado | Sim |
| Restrição de caixa | Dois estresses: itens zerados e movidos para exceções; piso protegido e alerta de insuficiência | Sim |

**Meta: 7 de 7 caminhos, acima do mínimo de 5. Nenhum dos sete ficou sem
cobertura.** O fornecedor fora do calendário é caracterizado pela ausência
na saída, conforme o comportamento atual do gerador, e não por uma linha
artificial de `FORA_DO_CALENDARIO`.

Cobertura adicional: fardo, preenchimento do mínimo com sucesso e com
adiamento, demanda recente zero (`coverage_days_after_order = null`), item
que nunca vendeu, preservação do piso e orçamento abaixo da soma dos pisos.

Limites explícitos deste golden: não exercita censura ligada (o padrão está
desligado), overrides `null` (ainda não existem antes da Fase 2), mediana
global de categoria sem referência, venda por kg, pipeline positivo na data
escolhida (o saldo em trânsito final é zero), Excel/CLI ou relatório mensal.
Esses casos não pertencem aos sete caminhos mínimos; não foram contados como
cobertos. XLSX e seu determinismo ficam para as fases específicas.

### Proveniência e preservação do golden

- HEAD de partida: `d68e3cd9376c1875a71236126e280a3820d8da1e`.
- Gerado em **uma única gravação**, com abertura exclusiva (`open('x')`),
  executando os quatro cenários com o produto original. A comparação não
  tem modo de atualização automática. Nenhum golden foi regenerado.
- SHA-256 inicial e final, **conferido idêntico no fechamento**:
  `108bb537631c9bcfed216c41b26e723ea9d0f187a98778c17ea2c1445f42c125`.
- Comando de comparação nas próximas fases:
  `uv run pytest -q --no-cov tests/test_purchase_list_characterization.py -k matches_complete_golden`.
- `git diff --exit-code -- src config tests/test_purchase_list.py`: passou
  antes da geração e depois dos testes. Logo, a referência foi capturada
  antes de alterar o comportamento atual.
- Como o golden é novo e permanece não rastreado (R1), `git diff` sozinho
  não comprova sua preservação. O SHA-256 registrado permite conferi-la
  sem adicionar nada ao índice.

### Verificações da Fase 1

| Comando | Resultado real |
|---|---|
| Testes de comportamento antes da gravação: `uv run pytest -q --no-cov tests/test_purchase_list_characterization.py -k 'not compara_saida_integral'` | **9 passed, 4 deselected in 10.26s**; nomes dos testes posteriormente padronizados em inglês |
| `uv run pytest -q` | **464 passed, 1 skipped, 3 deselected, 1 xfailed in 28.39s**; os quatro snapshots passaram |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `94 files already formatted` |
| `uv run mypy src/` | `Success: no issues found in 43 source files` |
| `uv run pytest -q -p no:cacheprovider` (conferência final, após padronizar nomes) | **464 passed, 1 skipped, 3 deselected, 1 xfailed in 28.12s**; 0 falhas/erros |

Lint, formatação e mypy também foram repetidos após a padronização dos nomes,
com os mesmos resultados acima. O golden completo foi relido e seu SHA-256
final permaneceu idêntico ao inicial.

## Antes e depois desta rodada

| Medida | Antes | Depois |
|---|---:|---:|
| Testes aprovados | 451 | 464 (+13) |
| Pulados / xfail / desmarcados por `not regression` | 1 / 1 / 3 | 1 / 1 / 3 |
| Cobertura total de linhas | 78,7781% (3159/4010) | 80,2743% (3219/4010) |
| Cobertura de linhas da lista | 63,0499% (215/341) | 79,1789% (270/341) |
| Cobertura de linhas do relatório mensal | 31,8182% (105/330) | 31,8182% (105/330) |
| Linhas com `type: ignore` em `src/` | 39 | 39 |
| Importações AST de produto para `experiments/` | 6 | 6 |
| Instruções `assert` em `src/` | 4 | 4 |
| Vulnerabilidades | Não auditadas | Não auditadas (Fase 9 fora da rodada) |

As metas finais de 85%/90%/85%, a remoção do `xfail`, a separação das camadas
e as demais correções ainda não foram implementadas. Esta entrega congela
o comportamento atual para permitir essas mudanças nas próximas rodadas.

## Autorrevisão das regras R1-R14

| Regra | Verificação desta rodada |
|---|---|
| R1 — Git | Só comandos de leitura; sem add, commit, push, reset, checkout, switch, stash ou rm; índice e histórico preservados |
| R2 — Branch | Primeiro comando desta rodada: `git branch --show-current` -> `feat/correcoes-motor` |
| R3 — Congelados | Nenhum arquivo em `src/` modificado; inclui os oito módulos congelados |
| R4 — Contratos | `forecast/base.py` e `policy/base.py` intactos |
| R5 — Premissas | `config/params.yaml` intacto, incluindo os três `null` do piloto e o decaimento; orçamento sintético só em `Params` validado |
| R6 — Números | Nenhuma substituição de 0,66, 7 ou 14 no produto; valores adicionais apenas nos cenários sintéticos declarados |
| R7 — Dependências | `pyproject.toml`/`uv.lock` intactos; sem instalação, upgrade, pip, curl ou wget |
| R8 — Escopo | Só quatro arquivos novos no repositório; nada em `.claude/`, `data/`, `results/` ou `.venv/`; caches da fixture em temporários permitidos pela Fase 1; nenhum script auxiliar salvo fora do repo |
| R9 — Testes | Nenhum teste existente alterado, removido ou afrouxado; `xfail` original preservado até a Fase 2 |
| R10 — Sem maquiagem | Nenhum ignore/noqa/pragma/skip/xfail novo; todos os testes novos têm asserts de resultado |
| R11 — Dados | Exclusivamente dados fictícios, pequenos, gerados em memória; sem arquivo de cliente |
| R12 — Negócio | Nenhuma premissa financeira de produção escolhida; estresses exclusivamente de teste |
| R13 — Estilo | Docstrings/comentários em português, identificadores novos em inglês, polars, tipagem e perfis determinísticos; checks de estilo e tipos verdes |
| R14 — Progresso | Este arquivo atualizado ao concluir cada fase; execução encerrada na Fase 1 |

`git status` e `git diff --stat` executados na autorrevisão. O status mostra
**somente os quatro arquivos novos listados acima**, todos não rastreados.
`git diff --stat` ficou vazio porque não inclui arquivos não rastreados;
`git diff --no-index --stat -- /dev/null <arquivo>` confirmou as adições sem
tocar no índice: fixture 193 linhas, testes 251 linhas e golden 900 linhas,
além deste relatório. Os diffs completos dos arquivos novos foram revistos.
`git diff --exit-code` e `git diff --cached --exit-code` passaram; HEAD e
branch permanecem idênticos aos da partida. Inventário final confirmado:
39 `type: ignore`, 4 `assert` em `src/`, 6 importações proibidas preexistentes.
A inspeção AST confirmou `assert` nas nove funções novas de teste (13 casos
por parametrização); busca de supressões nos arquivos novos retornou vazia.

## Portões G1-G12 — situação parcial, não encerramento da sprint

✅ significa verificado nesta sessão. ❌ significa critério completo ainda
não atingido ou não executado por estar fora das Fases 0 e 1, conforme
detalhado na coluna de resultado. Nenhum portão futuro foi declarado verde
por inferência.

| Portão | Comando/verificação | Resultado real nesta rodada | Estado |
|---|---|---|---|
| G1 | `uv run pytest -q -p no:cacheprovider` | 464 passed, 1 skipped, 3 deselected, 1 xfailed in 28.12s; 0 falhas/erros, +13 aprovados; falta remover o xfail na Fase 2 | ❌ |
| G2 | `uv run ruff check .`; `uv run ruff format --check .` | `All checks passed!`; `94 files already formatted` | ✅ |
| G3 | `uv run mypy src/`; contagem de ignores | 43 arquivos, 0 erros; 39 ignores antes/depois | ✅ |
| G4 | Inventário AST das importações | 6 preexistentes; testes de arquitetura da Fase 3 ainda não criados | ❌ |
| G5 | Teste positivo com YAML intacto | O gerador inteiro passa, mas a correção de `_decide_item` e remoção do xfail pertencem à Fase 2 | ❌ |
| G6 | Quatro comparações integrais do golden dentro da suíte; SHA-256 inicial/final | Quatro aprovadas, conteúdo idêntico desde a primeira gravação; produto intacto | ✅ |
| G7 | `git diff --exit-code -- src/motor/metrics/financial.py` | Arquivo intacto (também coberto pelo diff global); mutações da Fase 4 não executadas | ❌ |
| G8 | `uv run pytest -q` (cobertura ativa por padrão) | Total 80%, lista 79%, mensal 32%; valores exatos acima; `fail_under` ainda não ativado (Fase 7) | ❌ |
| G9 | Testes de determinismo da Fase 6 | Não executados; nenhum XLSX gerado nesta rodada | ❌ |
| G10 | `pip-audit` e `bandit` | Não executados (Fase 9/final fora desta rodada); nenhuma afirmação de segurança feita | ❌ |
| G11 | Documentação/coleta da Fase 11 | Não executada; somente registro desta rodada criado | ❌ |
| G12 | `git status`, `git diff --stat`, diffs global e do índice | Só os quatro arquivos novos de documentação/teste; produto, congelados, YAML, dependências e diretórios protegidos intactos | ✅ |

## Pendências e comandos para retomada

Nenhuma decisão de negócio foi necessária para as Fases 0 e 1. Permanecem
as decisões já existentes (limiares de censura, janela de teste,
decaimento e futura revisão do alpha/prazos com dado real), a serem tratadas
nas fases previstas. Os valores de estresse não são recomendações de negócio.

Felipe, quando os insumos estiverem disponíveis:

```sh
uv run pytest -m regression --no-cov tests/test_regression_favorita.py
```

Comandos para Rafael previstos na especificação **para fases futuras**, não
necessários para aprovar esta entrega parcial: auditorias/atualizações da
Fase 9 e `git rm --cached .claude/scheduled_tasks.lock` da Fase 10. Não foram
executados. Não foi solicitado backtest nem executada a Fase 12.

Mensagens de commit sugeridas (não executadas):

- Fase 0: `docs: registrar linha de base da sprint 25`.
- Fase 1: `test: caracterizar lista de compra com cenários sintéticos e golden`.

**Ponto de parada: Fases 0 e 1 concluídas; próxima fase é a 2, somente em
nova rodada autorizada.**
