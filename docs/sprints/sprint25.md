# Sprint 25 — Motor pronto para o dado real

Execução parcial em **20/11/2026**. Rodada 1: **Fases 0 e 1**, commitadas pelo
Rafael em `74383fe`. Rodada 2: **Fases 2 e 3**, commitadas em `fbcfce3`.
Rodada 3: **Fases 4 a 7**, commitadas em `0be9b75`.
Rodada 4: **Fases 8, 10, 11 e 13 concluídas localmente**; Fase 9 pendente
por DNS/rede, sem alteração do lock. Fase 12 excluída. Relatório final abaixo.
Especificação: `PROMPT_CODEX_sprint25.md`; `EXECUTAR_FASE_BACKTEST: não`.
O agente não executa commits. O registro da rodada 1 abaixo é histórico;
os resultados das rodadas seguintes são acrescentados ao final.

Vale o contrato de `CLAUDE.md`, exceto graphify (inexistente nesta máquina), e
as regras R1–R14 da especificação. Na rodada 1, o desenho autorizado foi
apenas fixture, golden, testes e este registro, sem alterar produto.
Na rodada 2, vale o desenho explícito das Fases 2 e 3 e os quatro ajustes
adicionais pedidos pelo Rafael.

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
| `experiments/monthly_report.py` (local atual; antes em reporting/) | 105 / 330 | 31,8182% |

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

## Antes e depois da rodada 1

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

## Autorrevisão das regras R1-R14 — rodada 1

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

## Portões G1-G12 — rodada 1, não encerramento da sprint

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

**Ponto de parada da rodada 1: Fases 0 e 1 concluídas.**

## Rodada 2 — preparação

- Primeiro comando: `git branch --show-current` -> `feat/correcoes-motor`.
- Árvore limpa; partida do commit `74383fe` do Rafael, sem reaplicar a rodada 1.
- Relidas as seções 3 (R1-R14) e 4 (D1-D12) da especificação, este registro e
  `CLAUDE.md`. O desenho segue a autorização explícita das Fases 2 e 3.
- Antes de editar: `uv run pytest -q --no-cov tests/test_purchase_list_characterization.py -k matches_complete_golden`
  -> **4 passed, 9 deselected in 10.17s**.
- Golden rastreado, SHA-256 inicial idêntico ao da rodada 1:
  `108bb537631c9bcfed216c41b26e723ea9d0f187a98778c17ea2c1445f42c125`.
- Mantidas as variáveis `UV_NO_SYNC=1`, `UV_NO_CACHE=1` e
  `PYTHONDONTWRITEBYTECODE=1` em todos os comandos `uv run`.

## Fase 2 — configuração explícita da lista

**Concluída antes de iniciar a Fase 3.**

- YAML recebeu somente seis linhas novas: bloco `purchase_list` após
  `purchase_list_supplier_assumptions`, com alpha 0,66, overrides 7/14,
  período de orçamento 14 e comentários de origem. Nenhum valor anterior
  foi alterado. `PurchaseListParams` valida alpha estritamente entre 0 e 1,
  prazos nulos ou inteiros positivos e período de orçamento inteiro positivo.
- Confirmado no caminho real: `CELL_ERP_FACTOR`, mínimo do ERP e cadência
  de retreino não afetam previsão estatística, política de nível-alvo ou
  estoque inicial da lista. Não foram adicionados ao YAML.
- `_decide_item` passa o alpha explícito para política, previsão e quantis do
  simulador. `generate_purchase_list` recebe o `Params` original sem cópia
  não validada; overrides nulos mantêm o cadastro. O orçamento usa
  `budget_period_days`, independente da revisão do fornecedor.
- Excel recebe configuração e cadastro explicitamente; notas mostram alpha,
  prazos efetivos, janela e origem de cada prazo. CLI de estresse deriva
  `Params` com `model_dump()`/`model_validate()`.
- `purchase_list` entrou em `EXCLUDED_PARAMS_SECTIONS`, com justificativa:
  a seção não é lida pelos braços 1 e 2.
- O teste marcado como falha esperada foi substituído por teste positivo com
  YAML intacto e quantidade >= 0. Nenhum outro teste foi removido/afrouxado.
- Novo `tests/test_purchase_list_configuration.py`: rejeição de 13 valores
  inválidos, prazos por fornecedor, notas dos arquivos XLSX, alpha fora da
  grade geral e período de orçamento independente da revisão. As chamadas
  observadas nos testes executam os componentes reais.
- Variante nova `build_supplier_timing_scenario`, sem alterar os quatro
  cenários existentes: `SUP-GROCERY` 2/7 -> janela 9; `SUP-PRODUCE` 5/14 ->
  janela 19; `SUP-EGGS` 3/7 -> janela 10; `SUP-CLOSED` 4/7 -> janela 11.
  Conferidos os argumentos efetivos da previsão e da política por fornecedor
  e as notas dos três XLSX emitidos. `SUP-CLOSED` permanece fora do calendário.
- Teste de consistência com alpha experimental em `test_iso_service.py`:
  divergência explica que atualizar o alpha da lista exige decisão, sem
  recalibração automática.
- O teste de caixa da caracterização passou a ler
  `weekly_budget_rs * budget_period_days / 7`. Golden e cenários originais intactos.

| Comando — fechamento da Fase 2 | Resultado real |
|---|---|
| Testes focados: caracterização, configuração, lista e iso-serviço (`--no-cov`) | **71 passed in 20.83s** |
| `uv run pytest -q` | **482 passed, 1 skipped, 3 deselected in 47.92s**; 0 falhas/erros, 0 falhas esperadas; cobertura total **81%**, lista **92%**, mensal **32%** |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `95 files already formatted` |
| `uv run mypy src/` | `Success: no issues found in 43 source files` |
| `git diff --exit-code tests/golden/` | Vazio, retorno 0; quatro snapshots aprovados na suíte |
| `git diff --numstat config/params.yaml` | `6 0 config/params.yaml` |
| Busca de `model_copy` em reporting / marcadores de falha esperada em testes | Ambas vazias (retorno 1: nenhuma ocorrência) |
| `git diff --stat` dos oito congelados | Vazio |

Arquivos da Fase 2: `config/params.yaml`, `src/motor/config.py`,
`src/motor/reporting/purchase_list.py`, `tests/regression/favorita.py`,
`tests/test_purchase_list.py`, `tests/test_iso_service.py`,
`tests/purchase_list_fixtures.py`, `tests/test_purchase_list_characterization.py`,
novo `tests/test_purchase_list_configuration.py` e este registro.

## Fase 3 — fronteira entre produto e experimento

**Concluída. Nenhum módulo de produto importa `motor.experiments`.**

### Arquivos e implementações transferidas

| Origem | Destino | Implementação |
|---|---|---|
| `experiments/shared.py` | novo `src/motor/simulator/pair.py` | `initial_stock_units`, `build_simulator_for_pair`; arquivo novo idêntico em bytes ao shared original |
| `experiments/run.py` | novo `src/motor/selection_cache.py` | `StaleSubsetSelectionError`, `_selection_params_hash`, `load_or_select_subset`; corpos preservados |
| `experiments/iso_service.py` | novo `src/motor/io/canonical.py` | `CanonicalTables`, `load_canonical_tables`; contratos e leitura preservados |
| `experiments/sensitivity.py` e `experiments/iso_service.py` | novo `src/motor/io/supplier_overrides.py` | Overrides de prazo/revisão e composição `cell_suppliers` |
| `src/motor/reporting/monthly_report.py` | `src/motor/experiments/monthly_report.py` | Único arquivo integralmente movido; conteúdo idêntico em bytes ao original |

Os módulos de origem mantêm reexportações por atribuição aos objetos de
produto. Isso passa no mypy estrito e no Ruff sem novos ignores/noqa.
`iso_service.cell_suppliers` mantém um adaptador mínimo com os defaults
históricos do experimento; a composição pertence ao produto e recebe os
prazos explicitamente (inclusive `None`). Assim, os defaults da célula
continuam fora do produto. Compatibilidade verificada por identidade dos
objetos e igualdade dos frames de saída, incluindo chamadas antigas sem
argumentos opcionais e chamadas com prazos explícitos.

### Imports e referências atualizados

| Arquivo consumidor | Atualização |
|---|---|
| `src/motor/reporting/purchase_list.py` | `iso_service.CanonicalTables/load_canonical_tables` -> `io.canonical`; `run.load_or_select_subset` -> `selection_cache`; `shared.build_simulator_for_pair` -> `simulator.pair`; composição dos overrides -> `io.supplier_overrides.cell_suppliers`; constantes de experimento eliminadas da lista na Fase 2 |
| `src/motor/policy/erp_calibration.py` | `experiments.shared.build_simulator_for_pair` -> `simulator.pair` |
| `src/motor/experiments/run.py` | Simulador -> `simulator.pair`; import do módulo `selection_cache` com reexportações; import local de seleção pura deixou de ser necessário |
| `src/motor/experiments/shared.py` | Importa `motor.simulator.pair` e reexporta as duas funções; imports auxiliares pertencem agora ao módulo de produto |
| `src/motor/experiments/iso_service.py` | Importa módulos `io.canonical` e `io.supplier_overrides` para reexportação/adaptação; `dataclass` e imports indiretos dos overrides saíram da origem |
| `src/motor/experiments/sensitivity.py` | Importa `io.supplier_overrides` e reexporta as duas funções |
| `tests/purchase_list_fixtures.py` | `CanonicalTables` -> `io.canonical`; `_selection_params_hash` -> `selection_cache` |
| `tests/test_purchase_list_characterization.py` | `_selection_params_hash` e `load_or_select_subset` -> `selection_cache` |
| `tests/test_run.py` | Erro, hash e carregamento do cache -> `selection_cache`; imports específicos do runner permanecem em experiments |
| `tests/test_shared.py` | Duas funções -> `simulator.pair`; docstring e comentário atualizados |
| `tests/test_sensitivity.py` | `override_supplier_lead_time` -> `io.supplier_overrides`; funções de experimento permanecem em experiments |
| `tests/test_monthly_report.py` | `motor.reporting.monthly_report` -> `motor.experiments.monthly_report`; docstring atualizada |
| `notebooks/sprint20_apresentacao.py` | Import das sete funções/constante do relatório -> `motor.experiments.monthly_report` |
| `src/motor/assumptions.py` | Referência textual da fórmula do estoque inicial -> `motor.simulator.pair.initial_stock_units` |
| `src/motor/experiments/run.py` | Docstring de `run_arm` e texto de origem no manifesto -> novo caminho do simulador; sem refatorar a lógica de `run_arm` ou `_build_manifest` |
| `docs/sprints/sprint25.md` | Caminho atual do relatório mensal, mapa completo das transferências, imports e comando de CLI abaixo |

Também houve, na Fase 2, import de `Lt` em `config.py` para validar alpha,
e de `ARM2_CHOSEN_ALPHA` em `tests/test_iso_service.py` exclusivamente para
o teste de consistência. A fixture e o teste de caracterização não importam
mais a camada de experimentos. Os módulos novos importam diretamente suas
dependências de produto; os novos testes são listados a seguir.

Novo comando do relatório mensal:

```sh
uv run python -m motor.experiments.monthly_report --output <arquivo.xlsx>
```

`--help` executado com sucesso (retorno 0), sem carregar resultados nem
gravar o relatório. Não foi encontrada outra referência executável ao
caminho antigo em testes, notebooks ou documentação editável.

O grep de `motor.experiments` fora da pasta de experimentos agora retorna
somente docstrings: referências a entrypoints experimentais ainda válidos,
além de referências legadas em `policy/basestock.py` e `metrics/financial.py`.
**Esses dois arquivos estão congelados por R3 e não foram editados**, nem
para trocar documentação. Os caminhos legados continuam válidos pelas
reexportações. Não há exceção ao teste de arquitetura, nem dependência real
de produto para experimento.

### Testes e portões da Fase 3

- Novo `tests/test_architecture.py`: AST de todos os módulos de produto,
  incluindo aliases e imports relativos; subprocesso da lista sem GBM;
  subprocessos independentes de `io.canonical` e `simulator.pair` sem GBM;
  proibição de `model_copy(` em reporting/policy. **5 casos aprovados.**
- Novo `tests/test_product_helpers.py`: compatibilidade das reexportações,
  quatro combinações de overrides independentes e leitura canônica de quatro
  parquets exclusivamente sintéticos em `tmp_path`. **6 casos novos.**
- `monthly_report.py` não ficou com fachada em reporting: foi transferido
  integralmente para experiments. Os testes antigos continuam verificando
  o mesmo conteúdo com o novo import.
- Dois caches `.pyc` antigos e ignorados em `src/motor/reporting/__pycache__/`
  (purchase_list e monthly_report) foram removidos: o grep amplo encontrava
  `model_copy` no bytecode anterior, apesar de não existir mais no fonte.
  Nenhum arquivo rastreado/protegido foi atingido; o grep exato ficou vazio.

| Comando — fechamento da Fase 3 | Resultado real |
|---|---|
| Testes focados de arquitetura, helpers, shared, runner, sensibilidade e mensal (`--no-cov`) | **57 passed in 1.91s** |
| `uv run pytest -q --no-cov tests/test_architecture.py` | **5 passed in 0.45s** |
| `uv run pytest -q` | **493 passed, 1 skipped, 3 deselected in 48.92s**; 0 falhas/erros, 0 falhas esperadas |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `101 files already formatted` |
| `uv run mypy src/` | `Success: no issues found in 47 source files` |
| `uv run python -m motor.experiments.monthly_report --help` | Retorno 0 |

## Antes e depois — rodada 2

| Medida | Partida (rodada 1 commitada) | Fim da rodada 2 |
|---|---:|---:|
| Testes aprovados | 464 | 493 (+29 aprovados: 28 casos novos e um antes com falha esperada) |
| Pulados / falhas esperadas / desmarcados | 1 / 1 / 3 | 1 / 0 / 3 |
| Cobertura total de linhas | 80,2743% (3219/4010) | 81,6728% (3320/4065) |
| Lista de compra | 79,1789% (270/341) | 92,4157% (329/356) |
| Relatório mensal (agora em experiments/) | 31,8182% | 31,8182% (105/330) |
| `type: ignore` em src/ | 39 | 39 |
| Importações de produto para experiments | 6 | 0 |
| `assert` em src/ | 4 | 4 (Fase 5 ainda não executada) |
| Vulnerabilidades | Não auditadas | Não auditadas; Fase 9 fora desta rodada |

O único skip ainda depende do parquet real de fornecedores. Os quatro
parquets Favorita seguem ausentes; regressão não executável nesta máquina.
Leitura dos hashes de todas as seções prévias do Params confirmou igualdade
com `tests/regression/favorita_baseline.json`, sem ler dados reais. Isso não
substitui a regressão financeira a ser executada pelo Felipe:

```sh
uv run pytest -m regression --no-cov tests/test_regression_favorita.py
```

## Autorrevisão solicitada — rodada 2

| Item | Evidência |
|---|---|
| (a) Golden intacto | Quatro snapshots passam na suíte; `git diff --exit-code tests/golden/` vazio/retorno 0; bytes iguais ao HEAD; SHA-256 final `108bb537631c9bcfed216c41b26e723ea9d0f187a98778c17ea2c1445f42c125`. Nunca gravado/regenerado nesta rodada |
| (b) YAML só ganhou linhas | `git diff --numstat config/params.yaml`: **6 adicionadas, 0 removidas**; comparação dos valores antigos com HEAD: todos idênticos |
| (c) Oito congelados intactos | `git diff --stat` dos oito caminhos de R3: vazio; protocolos também intactos |
| (d) Exclusão da regressão | `EXCLUDED_PARAMS_SECTIONS = frozenset({"mercado_piloto", "purchase_list"})`, com comentário de origem; hashes prévios iguais à referência |
| (e) Sem marcadores de falha esperada | Busca AST de atributos `xfail` em todos os testes: lista vazia; suíte sem xfail; menções históricas em Markdown preservadas |
| (f) Sem cópia não validada em reporting | `grep -rn "model_copy" src/motor/reporting`: vazio, retorno 1 (nenhuma ocorrência) |
| (g) Arquitetura | Comando isolado: **5 passed in 0.45s**, sem exceções ou supressões |
| (h) Transferências e imports | Mapa completo acima; relatório mensal movido sem alterações de conteúdo; helpers movidos com compatibilidade |

R1/R2: Git somente de leitura, mesma branch, nenhum add/commit/push/reset ou
alteração de índice/histórico. R3/R4: congelados e protocolos intactos.
R5/R6: só a nova seção YAML, com os valores antigos da lista e origem
declarada; nenhum null preenchido. R7/R8: dependências, `.venv/`, `.claude/`,
`data/` e `results/` intactos; fixtures/Excel em temporários autorizados;
nenhum script auxiliar salvo em disco. R9/R10: só a substituição autorizada
da falha esperada, imports e ajuste do orçamento pedidos; nenhum teste
afrouxado, ignore/noqa/skip novo ou regra de lint desligada. R11/R12: só
dados fictícios; nenhuma nova decisão de negócio. R13/R14: estilo e tipos
verificados, registro atualizado ao concluir cada fase; parada na Fase 3.

## Portões G1-G12 — rodada 2 (parcial)

| Portão | Situação medida |
|---|---|
| G1 | ❌ Execução limpa específica com `-p no:cacheprovider` fica para o fechamento final; a suíte exigida nesta rodada (`uv run pytest -q`) passou com 493 passed, 1 skipped, 3 deselected, 0 xfail |
| G2 | ✅ Lint/formatação limpos, 101 arquivos formatados |
| G3 | ✅ Mypy limpo em 47 arquivos; 39 ignores, sem aumento |
| G4 | ✅ 5 testes de arquitetura; 0 imports proibidos |
| G5 | ✅ Decisão com YAML intacto e quantidade >= 0; grade original preservada |
| G6 | ✅ Golden original passa, diff vazio e SHA-256 preservado |
| G7 | ❌ Não executado: mutações da Fase 4; financial.py intacto |
| G8 | ❌ Total 81,6728%, lista 92,4157%, mensal 31,8182%; metas restantes e fail_under na Fase 7 |
| G9 | ❌ Testes de determinismo da Fase 6 não executados |
| G10 | ❌ Auditorias não executadas; Fase 9 fora desta rodada |
| G11 | ❌ Alinhamento geral/documentação de coleta da Fase 11 não executados |
| G12 | ✅ YAML aditivo, congelados/protocolos/diretórios protegidos intactos; diff/status revisados |

Nenhuma decisão de negócio nova ficou pendente para fechar as Fases 2 e 3.
A revisão do alpha e dos overrides com dado real continua sendo de Felipe e
da dona do mercado, apoiada por histórico e prazos reais de fornecedores;
nenhuma recalibração foi decidida automaticamente. As demais pendências de
negócio existentes continuam para as fases previstas.

Mensagens de commit sugeridas, sem executá-las:

- Fase 2: `fix: explicitar configuração e prazos da lista de compra`.
- Fase 3: `refactor: separar utilitários de produto dos experimentos`.

**Ponto de parada da rodada 2: Fases 2 e 3 concluídas. Fase 4 não iniciada.**

## Estado de partida da rodada 3

- Branch conferida primeiro: `feat/correcoes-motor`; HEAD `fbcfce3`.
- `git status`: `nothing to commit, working tree clean`.
- Relidas R1-R14, `CLAUDE.md`, este registro e o pedido completo da rodada 3.
- Mantidas `UV_NO_SYNC=1`, `UV_NO_CACHE=1`, `PYTHONDONTWRITEBYTECODE=1`.
- Golden inicial: `108bb537631c9bcfed216c41b26e723ea9d0f187a98778c17ea2c1445f42c125`.
- Proteção adicional desta rodada: runner, iso-serviço, shared, sensibilidade,
  stale-baseline e diretórios simulator/policy/forecast/features não podem
  mudar, pois Felipe executa a regressão da rodada 2 em paralelo.
- Inventário de asserts: purchase_list:361, monthly_report:219,
  quality_report:270 e run:403. Há conflito entre incluir todos na Fase 5 e
  a proibição de editar run.py; esclarecimento solicitado ao Rafael,
  enquanto a Fase 4 segue independentemente. Nenhuma exceção presumida.

| Comando de partida | Resultado real |
|---|---|
| `uv run pytest -q --cov=motor --cov-branch --cov-report=term-missing` | **493 passed, 1 skipped, 3 deselected in 53.76s**; total **81%**, purchase_list **92%**, mensal **28%**, raw **62%** (linhas e desvios combinados) |
| `uv run pytest -q --no-cov --durations=15` | **493 passed, 1 skipped, 3 deselected in 27.69s** |

O comando de cobertura emitiu o aviso preexistente de módulo motor importado
antes da medição. Sem supressão. Cobertura de linhas registrada na rodada 2:
total 81,6728%, lista 92,4157%, mensal 31,8182%, raw 63,3333%.

15 durações mais lentas na partida:

```text
9.31s setup test_purchase_list_characterization.py::test_generate_purchase_list_matches_complete_golden[default]
4.16s call  test_purchase_list_configuration.py::test_excel_notes_use_configured_overrides_and_alpha
3.65s call  test_purchase_list_configuration.py::test_null_overrides_use_each_supplier_risk_window_and_excel_note
2.31s call  test_quantile_gbm.py::test_embaralhamento_desempenho_cai_ao_nivel_trivial
2.29s call  test_purchase_list_configuration.py::test_budget_period_is_independent_of_supplier_review
1.82s call  test_quantile_gbm.py::test_cobertura_empirica_por_quantil_no_periodo_simulado
0.38s call  test_censoring.py::test_purchase_list_com_censura_usa_historico_censurado
0.17s call  test_quantile_gbm.py::test_nenhuma_linha_de_treino_usa_informacao_futura_ate_o_fit
0.14s call  test_architecture.py::test_purchase_list_import_does_not_load_lightgbm
0.13s call  test_purchase_list.py::test_item_decision_accepts_unmodified_repository_params
0.12s call  test_quantile_gbm.py::test_cache_mesmo_estado_com_cache_quente
0.11s call  test_architecture.py::test_product_helpers_import_without_lightgbm[motor.io.canonical]
0.11s call  test_architecture.py::test_product_helpers_import_without_lightgbm[motor.simulator.pair]
0.09s call  test_quantile_gbm.py::test_precompute_predictions_bate_exato_com_calculo_item_a_item
0.08s call  test_loaders.py::test_idempotencia
```

## Fase 4 — proteção das fórmulas financeiras

**Concluída.** Apenas acrescentado um teste em `tests/test_financial.py`.
Dois itens, dois dias avaliados e um dia de aquecimento, todos os campos
com valores que distinguem venda, demanda, margem, preço e custo.
Contas manuais no comentário e igualdade exata por item e no agregado:

| Item | Margem realizada | Ruptura | Perda |
|---|---:|---:|---:|
| A (preço 10, custo 7) | (7+4)*3 = 33 | (3+4)*3 = 21 | (2+1)*7 = 21 |
| B (preço 10, custo 8) | (5+2)*2 = 14 | (1+3)*2 = 8 | (1+2)*8 = 24 |
| Total avaliado | 47 | 29 | 45 |

O warmup acrescentaria 210, 250 e 220 respectivamente; não entra nas contas.

Todos os textos exatos dos três mutantes foram encontrados uma única vez.
Para cada um: `cp` para `/tmp/financial_backup.py`, aplicação isolada,
`uv run pytest -q -x --no-cov tests/test_financial.py`, restauração com `cp`
em bloco `finally` e `git diff --exit-code src/motor/metrics/financial.py`
com retorno 0. Também rodado o teste novo isoladamente em cada mutação:
os três retornaram 1 com falha de assert. Nenhum mutante sobreviveu; não foi
necessário executar a suíte inteira mutada. Backup apagado ao concluir.

| Mutante | Primeiro teste que o matou no comando obrigatório | Mensagem/valor da falha |
|---|---|---|
| M1 — ruptura por preço | `test_financial_losses_and_margin_match_exact_manual_totals_excluding_warmup` | Item A: `ruptura_rs: 70.0` em vez de `21.0`; `1 failed, 13 passed in 0.24s` |
| M2 — perda por preço | `test_daily_net_margin_e_margem_menos_perda_por_dia` (preexistente) | `Obtained: -50.0; Expected: -40.0 ± 4.0e-05`; `1 failed, 11 passed in 0.13s`; novo teste isolado também matou M2 |
| M3 — margem por demanda | `test_financial_losses_and_margin_match_exact_manual_totals_excluding_warmup` | Item A: `margem_realizada_rs: 54.0` em vez de `33.0`; `1 failed, 13 passed in 0.13s` |

| Verificação da Fase 4 | Resultado |
|---|---|
| Financeiro sem mutante (`--no-cov`) | 14 passed in 0.24s |
| `uv run pytest -q` | **494 passed, 1 skipped, 3 deselected in 48.67s** |
| `uv run ruff check .` | All checks passed! |
| `uv run ruff format --check .` | 101 files already formatted |
| `uv run mypy src/` | Success: no issues found in 47 source files |


## Esclarecimento de escopo da Fase 5

Rafael respondeu explicitamente: **"Preservar run.py nesta rodada"**.
Portanto o assert de `experiments/run.py:403` será mantido. Serão trocados
os três asserts em arquivos autorizados. O item final (c), grep global
vazio, terá esta exceção de escopo registrada, sem declarar zero ocorrências.

## Fase 5 — exceções explícitas em produto

**Concluída no escopo confirmado pelo Rafael.** Em cada função abaixo,
somente o assert foi substituído por `if not isinstance`, `TypeError` e
mensagem em português. Não houve outra mudança de lógica nessas funções.

| Função | Mensagem verificada pelo teste novo |
|---|---|
| `purchase_list._first_sale_and_days_with_sales` | `A primeira data de venda deve ser uma data válida.` |
| `monthly_report.n_months_no_periodo` | `simulation_window.n_evaluation_days deve ser um inteiro.` |
| `quality_report._active_items` | `sales.date deve conter uma data válida para identificar os itens ativos.` |

`tests/test_product_validation.py` provoca as três exceções e confere as
mensagens exatas. Mypy preserva o estreitamento de tipo. O único assert
restante é `experiments/run.py:403`, preservado por instrução explícita.

| Verificação da Fase 5 | Resultado |
|---|---|
| `uv run pytest -q` | **497 passed, 1 skipped, 3 deselected in 48.29s**; golden aprovado |
| `uv run ruff check .` | All checks passed! |
| `uv run ruff format --check .` | 102 files already formatted |
| `uv run mypy src/` | Success: no issues found in 47 source files |
| Diffs financeiro, golden e runner | Vazios, retorno 0 |
| Grep global de asserts | Uma ocorrência, no runner protegido |

## Fase 6 — determinismo ponta a ponta

**Concluída.** Novo `tests/test_reporting_determinism.py`, com fixture de
escopo module que roda `generate_purchase_list` exatamente duas vezes.
Os dois testes da lista reutilizam essas saídas; não repetem simulações.
Comparações da serialização e das estruturas completas passaram.

Os testes de bytes gravam em diretórios diferentes e separam as gravações
por 1,1 s, evitando aprovação acidental no mesmo segundo do relógio.
Antes da correção: **2 failed, 1 passed in 8.16s**. Nos dois relatórios,
o único membro ZIP divergente era `docProps/core.xml`: campos `created` e
`modified` variavam com o relógio (por exemplo 21:47:22Z -> 21:47:23Z).
Inspeção do código instalado confirmou o fallback de XlsxWriter para
`datetime.now` quando `created` não é um datetime.

Correção autorizada, sem mudar conteúdo de células, texto ou formato:

- Lista: `workbook.set_properties` com `datetime.combine(as_of, time.min)`.
- Mensal: mesma propriedade, derivada do `end` do período simulado já
  carregado em `_ReportData` (não do relógio). Nenhum cálculo foi alterado.
- Nenhuma assinatura de função alterada.

O mensal pôde ser gerado inteiramente com arquivos sintéticos. Novo builder
`tests/monthly_report_fixtures.py`, reutilizável na Fase 7: todos os caminhos
de monthly/stale-baseline são redirecionados em memória para tmp_path, com
restauração automática. O arquivo stale_baseline.py permanece intocado.

| Verificação da Fase 6 | Resultado |
|---|---|
| `uv run pytest -q --no-cov --durations=5 tests/test_reporting_determinism.py` | **3 passed in 7.92s**, abaixo de 30 s; setup 4.76s, bytes mensal 1.15s, bytes lista 1.15s |
| `uv run pytest -q` | **500 passed, 1 skipped, 3 deselected in 59.26s**; total 87%, lista 92%, mensal 98% (linhas) |
| `uv run ruff check .` | All checks passed! |
| `uv run ruff format --check .` | 104 files already formatted |
| `uv run mypy src/` | Success: no issues found in 47 source files |

## Fase 7 — cobertura do relatório e limite contra regressão

**Concluída.** Oito novos testes em `tests/test_monthly_report_workbook.py`,
com builder sintético compartilhado e fixtures de escopo module. O workbook
é gerado uma vez para os testes de células. `tests/xlsx_assertions.py` lê
os XMLs do XLSX com a biblioteca padrão, sem nova dependência.

Arquivos mínimos criados exclusivamente dentro do diretório temporário:

| Caminho sob o tmp_path | Formato/campos efetivamente consumidos |
|---|---|
| `results/sensibilidade_dirigida/{lt3_rp7,lt5_rp7}/erp_baseline/manifest.json` | `erp_baseline_calibration.factor/min_order_units`, fontes da calibração antiga |
| `results/sensibilidade_dirigida/lt7_rp14/erp_baseline/manifest.json` | Calibração com moving_average_weeks; portfolio com serviço, decision_metric e capital; simulation_window com início/fim/dias avaliados |
| Mesmo diretório, `item_metrics.parquet` | Três itens com margem realizada, ruptura e perda |
| `results/baseline_desatualizado/{calibrado_lt3_rp7,calibrado_lt5_rp7}/erp_baseline/{manifest.json,item_metrics.parquet}` | Portfolio e métricas monetárias de cada baseline antigo |
| `results/iso_servico/arm2_alpha_grid.parquet` | alpha, serviço, decision_metric, capital |
| `results/iso_servico/item_decomposition_alpha066.parquet` | item_id, preço, custo, margem percentual, serviço, margem realizada, ruptura e perda |
| `canonical/items.parquet` | item_id, category, unit_of_sale; somente os campos usados pelo drilldown do relatório |
| `config/params.yaml` | Cópia validável dos parâmetros; somente canonical_dir aponta para o diretório sintético |

Nenhuma leitura/escrita em results/ ou data/ reais. O teste da CLI roda com
cwd no diretório temporário, onde os defaults relativos encontram esses
arquivos. Os testes em processo redirecionam as constantes existentes com
MonkeyPatch de contexto e restauram-nas ao sair.

**Assinaturas alteradas: nenhuma.** Não foi necessário acrescentar parâmetros
de caminho. Na Fase 7 não houve alteração no código de monthly_report.py;
as únicas diferenças desse arquivo na rodada são a guarda da Fase 5 e o
metadado da Fase 6. Cálculos, texto e formato foram preservados.

Comportamentos verificados:

- Sete abas, na ordem original, e cabeçalhos legíveis.
- Totais exatos do motor: margem 950, ruptura 150; recalibrado: margem 900,
  ruptura 200; período de 60 dias -> 2 meses.
- Resumo: ruptura evitada mensal 175, aumento de capital mensal 250,
  capital liberado mensal 50, margem adicional mensal 25; serviço e razões
  conferidos em células específicas.
- As duas magnitudes do Andar 1, aumento de capital e sensibilidade
  245/350/455, com os textos de -30%, medida e +30%.
- Andar 2: capital liberado 100 no período, 12,5%, razões e nota de margem.
- Itens ordenados A/B/C por ruptura 100/40/10, apesar da entrada B/C/A;
  percentuais 25%/20%/2%, venda por kg, custo, preço, margem e nota de top 20.
- Premissas por categoria ordenadas, valores/default, notas de aceitação e
  limitações. As notas originais não foram reescritas.
- CLI real: stdout e bytes idênticos ao workbook gerado em processo.

Testes focados do workbook: **8 passed in 1.62s**. Antes de ativar o piso,
medição completa com branch: **508 passed, 1 skipped, 3 deselected in
66.42s**; cobertura combinada exata **86,09515996718622%**. Por isso foi
acrescentado somente `[tool.coverage.report] fail_under = 86`, o valor
arredondado para baixo do mesmo comando de aceitação com desvios.
Nenhuma outra configuração de pytest/coverage ou dependência mudou.

O total já superou 85% após o relatório mensal; não foi necessário ampliar
os testes de raw.py. Esse módulo permanece integralmente congelado.

## Verificação final — rodada 3

`uv run pytest -q --cov=motor --cov-branch --cov-report=term-missing`,
com o fail_under ativo (linhas selecionadas da saída real):

```text
Name                                      Stmts   Miss Branch BrPart  Cover   Missing
src/motor/experiments/monthly_report.py     334      6     46      1    98%   834-840, 844
src/motor/io/raw.py                          90     33     30      2    62%   134, 189-223, 250-266, 270-280, 284
src/motor/reporting/purchase_list.py        359     27     80      1    92%   1086-1140, 1144
TOTAL                                      4074    526    802     50    86%
Required test coverage of 86.0% reached. Total coverage: 86.10%
508 passed, 1 skipped, 3 deselected in 67.36s (0:01:07)
```

Aviso preexistente de módulo importado antes da medição permaneceu visível;
nenhuma supressão. Valores exatos de linhas, separados da cobertura combinada:

| Medida | Partida | Final |
|---|---:|---:|
| Testes aprovados | 493 | 508 (+15) |
| Total de linhas | 81,6728% (3320/4065) | 87,0889% (3548/4074) |
| Lista de compra | 92,4157% (329/356) | 92,4791% (332/359) |
| Relatório mensal | 31,8182% (105/330) | 98,2036% (328/334) |
| Raw | 63,3333% (57/90) | 63,3333% (57/90) |
| type: ignore em src/ | 39 | 39 |
| asserts em src/ | 4 | 1 (runner preservado por decisão do Rafael) |
| Falhas / erros / falhas esperadas | 0 / 0 / 0 | 0 / 0 / 0 |
| Tempo sem cobertura | 27,69 s | 36,23 s |
| Tempo com branch | 53,76 s | 67,36 s |

`uv run pytest -q --no-cov --durations=15`:

```text
============================= slowest 15 durations =============================
9.00s setup    tests/test_purchase_list_characterization.py::test_generate_purchase_list_matches_complete_golden[default]
5.26s call     tests/test_purchase_list_configuration.py::test_excel_notes_use_configured_overrides_and_alpha
4.71s setup    tests/test_reporting_determinism.py::test_purchase_list_decisions_are_identical_across_runs
3.58s call     tests/test_purchase_list_configuration.py::test_null_overrides_use_each_supplier_risk_window_and_excel_note
2.33s call     tests/test_purchase_list_configuration.py::test_budget_period_is_independent_of_supplier_review
2.26s call     tests/test_quantile_gbm.py::test_embaralhamento_desempenho_cai_ao_nivel_trivial
1.89s call     tests/test_quantile_gbm.py::test_cobertura_empirica_por_quantil_no_periodo_simulado
1.14s call     tests/test_reporting_determinism.py::test_monthly_workbook_bytes_are_identical_across_clock_seconds
1.12s call     tests/test_reporting_determinism.py::test_purchase_workbook_bytes_are_identical_across_clock_seconds
0.61s call     tests/test_monthly_report_workbook.py::test_monthly_cli_uses_only_synthetic_default_relative_paths
0.38s call     tests/test_censoring.py::test_purchase_list_com_censura_usa_historico_censurado
0.17s call     tests/test_quantile_gbm.py::test_nenhuma_linha_de_treino_usa_informacao_futura_ate_o_fit
0.13s call     tests/test_purchase_list.py::test_item_decision_accepts_unmodified_repository_params
0.13s call     tests/test_architecture.py::test_purchase_list_import_does_not_load_lightgbm
0.12s call     tests/test_quantile_gbm.py::test_cache_mesmo_estado_com_cache_quente
508 passed, 1 skipped, 3 deselected in 36.23s
```

Outras saídas reais, após a implementação final:

```text
uv run ruff check .
All checks passed!
uv run ruff format --check .
106 files already formatted
uv run mypy src/
Success: no issues found in 47 source files
grep -rn "type: ignore" src | wc -l
      39
```

## Autorrevisão (a)-(j) — rodada 3

| Item | Resultado e evidência |
|---|---|
| (a) Financeiro intacto | ✅ `git diff --exit-code src/motor/metrics/financial.py`: retorno 0 após cada restauração e no fim |
| (b) Mutantes | ✅ M1/M2/M3 mortos, tabela da Fase 4; o novo teste isolado matou os três |
| (c) Grep global de asserts vazio | ❌ Uma ocorrência: `src/motor/experiments/run.py:403`. Exceção de escopo decidida pelo Rafael: "Preservar run.py nesta rodada"; outros três removidos e testados |
| (d) Golden | ✅ Quatro snapshots passam; `git diff --exit-code tests/golden/`: retorno 0. SHA-256 preservado: `108bb537631c9bcfed216c41b26e723ea9d0f187a98778c17ea2c1445f42c125` |
| (e) Congelados/contexto | ✅ Diffs dos oito congelados e dos cinco experimentos protegidos/diretórios simulator, policy, forecast, features: retorno 0. Monthly só com guarda/metadado autorizados |
| (f) Params | ✅ `git diff --exit-code config/params.yaml`: retorno 0 |
| (g) Supressões | ✅ Nenhuma nova; 39 ignores, sem aumento; sem noqa/pragma/skip/xfail/omit novo; pytest/coverage só ganhou fail_under |
| (h) Cobertura/piso | ✅ Lista 92,4791%, mensal 98,2036%, total de linhas 87,0889%, combinado 86,0952%; fail_under 86 ativo e testado |
| (i) Tempo | ✅ 67,36 s com branch e 36,23 s sem cobertura, ambos <= 90 s; determinismo isolado 7,92 s, abaixo de 30 s |
| (j) Temporários | ✅ `/tmp/financial_backup.py` removido em finally; nenhum script auxiliar gravado em /tmp. Arquivos de teste ficam no tmp_path administrado pelo pytest |

O único skip e as três desmarcações são preexistentes (dado real/regressão).
A regressão do Favorita segue sob execução do Felipe, sem alteração local
dos braços protegidos. Nenhuma decisão de negócio foi necessária nesta rodada.
Não há assinatura de produto alterada nem mudança nos valores de params.yaml.

Arquivos por fase:

- Fase 4: `tests/test_financial.py` e este registro; financial.py só foi
  mutado temporariamente e restaurado.
- Fase 5: `src/motor/reporting/purchase_list.py`,
  `src/motor/experiments/monthly_report.py`, `src/motor/io/quality_report.py`,
  novo `tests/test_product_validation.py` e este registro.
- Fase 6: as duas rotinas de Excel acima, novos
  `tests/monthly_report_fixtures.py`, `tests/test_reporting_determinism.py`
  e este registro.
- Fase 7: fixture mensal ampliada para CLI, novos
  `tests/test_monthly_report_workbook.py`, `tests/xlsx_assertions.py`,
  `pyproject.toml` (somente o piso) e este registro.

Mensagens de commit sugeridas, sem executá-las:

- Fase 4: `test: proteger fórmulas financeiras com testes de mutação`.
- Fase 5: `fix: validar explicitamente os tipos nos relatórios`.
- Fase 6: `fix: tornar determinísticos os metadados dos relatórios Excel`.
- Fase 7: `test: cobrir relatório mensal e fixar piso de cobertura em 86`.

**Ponto de parada da rodada 3: Fases 4, 6 e 7 concluídas; Fase 5 concluída
no escopo autorizado, com o assert do runner preservado. Fase 8 não iniciada.
Nenhum commit executado.**

## Rodada 4 — linha de base e escopo final

Rodadas 1–3 commitadas pelo Rafael; partida em `0be9b75`, branch
`feat/correcoes-motor`, `git status --short` vazio. Seção 3 e histórico desta
sprint relidos. Escopo autorizado: Fases 8, 9, 10, 11 e 13; Fase 12 excluída.
Felipe confirmou a regressão da rodada 2, segundo o Rafael. A única edição
agora autorizada no runner é substituir o assert restante por exceção testada.

Linha de base medida **antes de editar**:

```text
uv run pytest -q
TOTAL                                      4074    526    87%
Required test coverage of 86.0% reached. Total coverage: 87.09%
508 passed, 1 skipped, 3 deselected in 60.70s (0:01:00)
grep -rn "type: ignore" src | wc -l
      39
```

Lista: 359 instruções, 27 não executadas (92%); mensal: 334/6 (98%).
Sem xfail. Contagem AST inclusiva (`end_lineno - lineno + 1`):
`_build_supplier_list` 109, `generate_purchase_list` 98,
`write_supplier_workbook` 88. Nenhuma outra função da lista ultrapassa 80.

Mantidos `UV_NO_SYNC=1 UV_NO_CACHE=1 PYTHONDONTWRITEBYTECODE=1` nos checks.
A sincronização da Fase 9 é exceção explícita autorizada nesta rodada à
proibição anterior de tocar no ambiente. Nenhuma premissa será alterada.

## Fase 8 — funções da lista menores, comportamento preservado

Extrações privadas, tipadas e com docstrings em português; textos, aritmética,
arredondamentos, ordem dos fornecedores e aplicação das guardas preservados.

| Função original | Antes desta rodada | Depois (AST inclusiva) |
|---|---:|---:|
| `_build_supplier_list` | 109 | 74 |
| `generate_purchase_list` | 98 | 75 |
| `write_supplier_workbook` | 88 | 71 |

Helpers: `_supplier_category` 14, `_supplier_purchase_rows` 47,
`_preliminary_supplier_lists` 31, `_guardrail_firing_report` 18,
`_write_workbook_notes` 35. Nenhuma função do arquivo acima de 80 linhas.
Na Fase 0 eram três (109/98/83); o aumento do writer para 88 ocorreu nas
rodadas anteriores, com a configuração explícita dos prazos.

Após **cada** função original, comando exigido com os quatro módulos da
lista/determinismo e `--no-cov`: **61 passed in 27.40s**, **61 passed in
27.89s**, **61 passed in 27.61s**, respectivamente. Houve também um check
intermediário de 61 testes (27.58s) antes de extrair a validação da categoria.
Golden sem escrita/regeneração; `git diff --exit-code tests/golden/`: 0.

Pendências autorizadas da rodada 3 atendidas: piso alterado de 86 para 85,
somente com o comentário solicitado; runner com `if ... is None`, ValueError
em português e teste que provoca a ausência das previsões. Teste focado:
**1 passed in 0.78s**. Nenhuma outra edição no runner (diff conferido).

Checks da Fase 8: Ruff `All checks passed!`; format `106 files already
formatted`; mypy `Success: no issues found in 47 source files`. Suíte completa
concluída: **509 passed, 1 skipped, 3 deselected in 61.30s**; total 87,25%,
lista 93%, mensal 98%; piso 85 ativo. **Fase 8 concluída.**

## Fase 9 — atualização e auditoria bloqueadas por rede

Tentativa real de `uv lock --upgrade-package pillow --upgrade-package tornado
--upgrade-package soupsieve` (uv 0.13.9): retorno **2**, depois das tentativas
normais do uv:

```text
error: Request failed after 3 retries in 5.7s
  cause: Failed to fetch: https://pypi.org/simple/pydantic/
  cause: error sending request for url (https://pypi.org/simple/pydantic/)
  cause: client error (Connect)
  cause: dns error
  cause: error resolving DNS
  cause: failed to lookup address information: nodename nor servname provided, or not known
```

`uv sync` também foi tentado, conforme solicitado; retorno **2**:

```text
Resolved 129 packages in 3ms
   Building motor @ file:///Users/rafaelcruxen/Documents/mercado
error: Failed to build `motor @ file:///Users/rafaelcruxen/Documents/mercado`
  cause: Failed to resolve requirements from `build-system.requires`
  cause: No solution found when resolving: `hatchling`
  cause: Request failed after 3 retries in 8.5s
  cause: Failed to fetch: https://pypi.org/simple/hatchling/
  cause: client error (Connect)
  cause: dns error
```

`git diff --stat uv.lock`: **vazio**. `git diff --exit-code uv.lock`: **0**.
Não houve resolução nova nem necessidade de restauração. Versões:

| Pacote | HEAD | Após a tentativa |
|---|---|---|
| pillow | 12.3.0 | 12.3.0 |
| tornado | 6.5.8 | 6.5.8 |
| soupsieve | 2.9.2 | 2.9.2 |

Demais versões de produção intactas: polars 1.44.2, lightgbm 4.7.0,
numpy 2.5.3, pydantic 2.13.5, pyarrow 25.0.1, scipy 1.18.1,
scikit-learn 1.9.0, xlsxwriter 3.2.9, pyyaml 6.0.3. Nenhuma dependência
acrescentada; nenhum uso de pip, curl ou wget.

Os dois `uv export` funcionaram (129 pacotes resolvidos; retorno 0).
A primeira chamada de uvx tentou criar `~/.local/share/uv/tools` e recebeu
`Operation not permitted`; nenhuma escrita autorizada ali. Repetição com
UV_TOOL_DIR/UV_TOOL_BIN_DIR em diretório temporário permitido em /tmp,
sem contornar rede. As duas chamadas de pip-audit retornaram **2**, por DNS
em `https://pypi.org/simple/pip-audit/`. Não há contagem confiável de
vulnerabilidades: **não auditado**, jamais "zero".

Lint, formato e mypy: verdes (106 arquivos formatados; 47 fontes sem erros).
Suíte: **509 passed, 1 skipped, 3 deselected in 60.79s**; cobertura total
87,25%, lista 93%, mensal 98%; golden e determinismo passaram. Bandit
retornou 2 por DNS; sem resultados de análise. /tmp/req.txt e o diretório
temporário do uvx removidos em finally (ausência conferida).

Saída real das auditorias com diretórios temporários permitidos:

```text
$ uvx pip-audit -r /tmp/req.txt
WARN Retry attempt #0. Sleeping 1.226174607s before the next attempt
WARN Retry attempt #1. Sleeping 3.587688763s before the next attempt
WARN Retry attempt #2. Sleeping 3.184178253s before the next attempt
error: Request failed after 3 retries in 8.0s
  cause: Failed to fetch: https://pypi.org/simple/pip-audit/
  cause: error sending request for url (https://pypi.org/simple/pip-audit/)
  cause: client error (Connect)
  cause: dns error
  cause: error resolving DNS
  cause: failed to lookup address information: nodename nor servname provided, or not known
exit_code=2
$ uv export --no-hashes --format requirements-txt
Resolved 129 packages in 5ms
exit_code=0
$ uvx pip-audit -r /tmp/req.txt
WARN Retry attempt #0. Sleeping 1.419855004s before the next attempt
WARN Retry attempt #1. Sleeping 1.407273271s before the next attempt
WARN Retry attempt #2. Sleeping 1.599668162s before the next attempt
error: Request failed after 3 retries in 4.4s
  cause: Failed to fetch: https://pypi.org/simple/pip-audit/
  cause: error sending request for url (https://pypi.org/simple/pip-audit/)
  cause: client error (Connect)
  cause: dns error
  cause: error resolving DNS
  cause: failed to lookup address information: nodename nor servname provided, or not known
exit_code=2
$ uvx bandit -r src -ll
WARN Retry attempt #0. Sleeping 1.814219854s before the next attempt
WARN Retry attempt #1. Sleeping 3.906836902s before the next attempt
WARN Retry attempt #2. Sleeping 4.396164909s before the next attempt
error: Request failed after 3 retries in 10.1s
  cause: Failed to fetch: https://pypi.org/simple/bandit/
  cause: error sending request for url (https://pypi.org/simple/bandit/)
  cause: client error (Connect)
  cause: dns error
  cause: error resolving DNS
  cause: failed to lookup address information: nodename nor servname provided, or not known
exit_code=2
```

**Fase 9 pendente por rede, sem atualização do lock.** As fases independentes
prosseguem conforme a autorização expressa de registrar os comandos para o
Rafael quando não houver rede. G10 não será declarado aprovado.

## Fase 10 — CI e instruções do repositório

Criados `.github/workflows/ci.yml` e `AGENTS.md`. Workflow em push e
pull_request, ubuntu-latest, Python 3.12, sync --locked, Ruff, format, mypy
strict e pytest -q. Addopts continua excluindo `regression`; o CI não exige
Favorita. Tags completas verificadas nas releases oficiais:
[checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) e
[setup-uv v10.4.0](https://github.com/astral-sh/setup-uv/releases/tag/v10.4.0).

Validação YAML pelo comando solicitado: retorno **0**, stdout vazio.
O workflow não foi executado no GitHub nesta sessão; só será disparado após
publicação pelo Rafael. AGENTS.md lido após criação; aponta ao contrato e
à regra Git, checks, camadas e decisão humana para regenerar golden.

`.claude/scheduled_tasks.lock` acrescentado ao .gitignore. O arquivo ainda é
versionado (`git ls-files` confirma); somente Rafael deve executar
`git rm --cached .claude/scheduled_tasks.lock`. Nenhuma edição em .claude/.
Os hooks de `.claude/settings.json` apontam a
`/home/felipe/.local/bin/graphify`; cabe ao Felipe decidir movê-los para
`.claude/settings.local.json`, que já está ignorado. Não foi alterado.

Checks: Ruff limpo, **107 files already formatted**, mypy 47 fontes sem erros;
suíte: **509 passed, 1 skipped, 3 deselected in 63.60s**; total 87,25%, lista
93%, mensal 98%. **Fase 10 concluída localmente**, publicação do CI por Rafael.

## Fase 11 — documentação e coleta

Atualizados CLAUDE.md (Python 3.12, mypy strict, árvore real, contratos,
nota de superação da emenda Sprint 17 e emenda Sprint 25 de 20/11/2026),
README e somente “Pendências antes do piloto” da Sprint 24. A afirmação
antiga sobre o alpha foi corrigida: a lista rodava via model_copy; agora
usa configuração explícita. O arquivo piloto_backtest.py não existe.

Criados `docs/decisoes_em_aberto.md`, `docs/coleta/dicionario_de_dados.md`,
`docs/coleta/roteiro_exportacao.md` e cinco modelos CSV (sales/items/
suppliers/stock/entries), cada qual com duas linhas **FICTÍCIAS**.
A lista única cobre os quatro null e as quatro chaves de purchase_list,
com responsáveis, evidência necessária e consequência do estado atual.
Nenhuma decisão comercial foi tomada nem parâmetro preenchido.

O dicionário distingue valor nulo de coluna ausente; documenta os quatro
parquet obrigatórios no carregador atual, stock vazio tipado, entries
opcional ainda sem carregamento automático e as premissas de fardo/mínimo
por categoria ainda usadas pela lista. O roteiro exige 364 dias de treino
mais 90 de aquecimento antes da avaliação, sem inventar duração do piloto.
Não pede CPF, cartão nem identificação de compradores.

Validação real dos CSVs com schemas derivados dos cinco modelos, casts de
CSV para tipos canônicos e `validate_table`:

```text
sales: cabeçalho exato, 2 linhas, contrato válido
items: cabeçalho exato, 2 linhas, contrato válido
suppliers: cabeçalho exato, 2 linhas, contrato válido
stock: cabeçalho exato, 2 linhas, contrato válido
entries: cabeçalho exato, 2 linhas, contrato válido
Integridade referencial e cadência: válidas
Todas as emendas antigas preservadas literalmente
Backtest 24.7 presente: False
Links locais de README, decisões e coleta: válidos
Sprint 24: só Pendências alterada
Seção Git do contrato preservada
```

Checks: Ruff `All checks passed!`, format `110 files already formatted`,
mypy `Success: no issues found in 47 source files`; diff --check vazio.
Suíte: **509 passed, 1 skipped, 3 deselected in 62.98s**; cobertura total
87,25%, lista 93%, mensal 98%. **Fase 11 concluída.**

## Fase 13 — verificação final da rodada 4

Tudo executado novamente sobre o estado final, sem sincronização implícita
do ambiente. Não houve commit, alteração de índice ou publicação. O skip
preexistente exige suppliers.parquet; três testes regression são excluídos
pelo addopts. **Zero xfail, falhas ou erros na suíte normal.**

Os blocos seguintes contêm a saída real dos comandos; as linhas de
progresso dos dois comandos de pytest foram omitidas; espaços finais em
linhas vazias do diff foram normalizados para manter o Markdown limpo.
As auditorias e seus erros reais estão na Fase 9 acima: não foram
repetidas para contornar a falha de rede já confirmada.

```text
$ uv run pytest -q -p no:cacheprovider
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.16-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
src/motor/__init__.py                         0      0   100%
src/motor/assumptions.py                     37      0   100%
src/motor/config.py                         218      2    99%   388-392
src/motor/experiments/__init__.py             0      0   100%
src/motor/experiments/iso_service.py        112     57    49%   171-172, 188-189, 266, 278-303, 309-346, 358-410, 417
src/motor/experiments/monthly_report.py     334      6    98%   834-840, 844
src/motor/experiments/run.py                285     26    91%   168-220, 406, 764-765, 767, 1006-1043, 1051
src/motor/experiments/sensitivity.py        342    265    23%   174, 195, 231-291, 333, 402-411, 448-461, 490-589, 607-666, 672-677, 691-694, 713-722, 738-746, 764-810, 829-916, 927-1022, 1026-1139, 1147
src/motor/experiments/shared.py               3      0   100%
src/motor/experiments/stale_baseline.py     145     49    66%   167-177, 380-475, 479-501, 505
src/motor/features/__init__.py                1      0   100%
src/motor/features/build.py                  66      4    94%   190-191, 194-195
src/motor/features/calendar.py               53      0   100%
src/motor/features/censoring.py              44      3    93%   114, 138-139
src/motor/forecast/__init__.py                0      0   100%
src/motor/forecast/base.py                   15      0   100%
src/motor/forecast/naive.py                  63      1    98%   141
src/motor/forecast/naive_seasonal.py         27      0   100%
src/motor/forecast/quantile_gbm.py          200     18    91%   150, 188, 211, 273, 327-328, 337-341, 559-563, 626-627, 632-637, 639-644, 659-663
src/motor/forecast/statistical.py            90      1    99%   77
src/motor/inventory.py                       58      0   100%
src/motor/io/__init__.py                      0      0   100%
src/motor/io/canonical.py                    15      0   100%
src/motor/io/contracts.py                   326     11    97%   377-378, 425, 456-458, 465, 469, 493-494, 502
src/motor/io/loaders.py                     158      6    96%   166-167, 169, 638, 666, 773
src/motor/io/quality_report.py              172      2    99%   431-432
src/motor/io/raw.py                          90     33    63%   134, 189-223, 250-266, 270-280, 284
src/motor/io/supplier_overrides.py           13      0   100%
src/motor/metrics/__init__.py                 0      0   100%
src/motor/metrics/financial.py               71      0   100%
src/motor/metrics/forecast_quality.py        52      0   100%
src/motor/policy/__init__.py                  0      0   100%
src/motor/policy/base.py                     13      0   100%
src/motor/policy/basestock.py                12      0   100%
src/motor/policy/erp_baseline.py             42      0   100%
src/motor/policy/erp_calibration.py          93      1    99%   134
src/motor/policy/guardrails.py              164      1    99%   523
src/motor/policy/supplier.py                 97      2    98%   166-167
src/motor/policy/target_level.py             52      0   100%
src/motor/profiling.py                       53      6    89%   47-62, 184-197
src/motor/reporting/__init__.py               0      0   100%
src/motor/reporting/purchase_list.py        370     27    93%   1167-1221, 1225
src/motor/selection.py                       71      0   100%
src/motor/selection_cache.py                 24      0   100%
src/motor/simulator/__init__.py               0      0   100%
src/motor/simulator/engine.py                84      0   100%
src/motor/simulator/pair.py                  22      0   100%
-----------------------------------------------------------------------
TOTAL                                      4087    521    87%
Required test coverage of 85.0% reached. Total coverage: 87.25%
509 passed, 1 skipped, 3 deselected in 61.77s (0:01:01)
```

Retorno: **0**.

```text
$ uv run pytest -q --no-cov --durations=10
============================= slowest 10 durations =============================
9.06s setup    tests/test_purchase_list_characterization.py::test_generate_purchase_list_matches_complete_golden[default]
4.66s setup    tests/test_reporting_determinism.py::test_purchase_list_decisions_are_identical_across_runs
4.14s call     tests/test_purchase_list_configuration.py::test_excel_notes_use_configured_overrides_and_alpha
3.64s call     tests/test_purchase_list_configuration.py::test_null_overrides_use_each_supplier_risk_window_and_excel_note
2.30s call     tests/test_purchase_list_configuration.py::test_budget_period_is_independent_of_supplier_review
2.20s call     tests/test_quantile_gbm.py::test_embaralhamento_desempenho_cai_ao_nivel_trivial
1.77s call     tests/test_quantile_gbm.py::test_cobertura_empirica_por_quantil_no_periodo_simulado
1.17s call     tests/test_reporting_determinism.py::test_monthly_workbook_bytes_are_identical_across_clock_seconds
1.15s call     tests/test_reporting_determinism.py::test_purchase_workbook_bytes_are_identical_across_clock_seconds
0.61s call     tests/test_monthly_report_workbook.py::test_monthly_cli_uses_only_synthetic_default_relative_paths
509 passed, 1 skipped, 3 deselected in 34.82s
```

Retorno: **0**.

```text
$ uv run ruff check .
All checks passed!
```

Retorno: **0**.

```text
$ uv run ruff format --check .
110 files already formatted
```

Retorno: **0**.

```text
$ uv run mypy src/
Success: no issues found in 47 source files
```

Retorno: **0**.

```text
$ grep -rn "type: ignore" src | wc -l
      39
```

Retorno: **0**.

```text
$ grep -rn '^\s*assert ' src
```

Retorno: **1**, saída vazia.

```text
$ grep -rn 'motor.experiments' src/motor --include='*.py' | grep -v '^src/motor/experiments/'
src/motor/forecast/quantile_gbm.py:13:(`train_quantile_models`, chamado por `motor.experiments.run.run_arm` antes
src/motor/metrics/financial.py:6:`motor.experiments.shared` recebe premissas de simulação em vez de `Params`
src/motor/metrics/financial.py:280:    `expired`, `on_hand_end` (saída de `motor.experiments.run`, ou os
src/motor/config.py:193:    loaders`, `motor.experiments.run`/`sensitivity`/`iso_service`, nem por
src/motor/policy/basestock.py:34:    para os dois (`motor.experiments.shared.build_simulator_for_pair` e
src/motor/policy/basestock.py:35:    `motor.experiments.run._build_policy`/`_build_forecaster`, que derivam
src/motor/assumptions.py:16:`motor.experiments.run` embute em TODO manifesto (`RunManifest.assumptions`,
```

Retorno: **0**.

```text
$ git diff --exit-code tests/golden/
```

Retorno: **0**, saída vazia.

```text
$ git diff --stat -- src/motor/inventory.py src/motor/policy/supplier.py src/motor/policy/guardrails.py src/motor/policy/basestock.py src/motor/metrics/financial.py src/motor/io/loaders.py src/motor/io/raw.py src/motor/simulator/engine.py
```

Retorno: **0**, saída vazia.

```text
$ git diff HEAD~3 -- config/params.yaml
diff --git a/config/params.yaml b/config/params.yaml
index 538dfba..3112015 100644
--- a/config/params.yaml
+++ b/config/params.yaml
@@ -285,6 +285,12 @@ purchase_list_supplier_assumptions:
     BOOKS: 2000.0
     "HOME APPLIANCES": 2000.0

+purchase_list:
+  alpha: 0.66 # valor atual: ARM2_CHOSEN_ALPHA (iso-serviço, Etapa 3.12, célula lt=7/rp=14); revisar com o dado real
+  lead_time_days_override: 7 # valor atual: célula da Etapa 3.12. null = usar o lead_time_days do cadastro do fornecedor
+  review_period_days_override: 14 # valor atual: célula da Etapa 3.12. null = usar o review_period_days do cadastro do fornecedor
+  budget_period_days: 14 # valor atual: CELL_REVIEW_PERIOD_DAYS; período do orçamento por ciclo (weekly_budget_rs x dias/7)
+
 economics:
   capital_cost_annual: 0.15 # arbitrado: custo de capital anualizado plausível para varejo pequeno/médio no Brasil
   # Sprint 8: preço único por unidade vendida, aplicado a TODO item -- o Favorita não
```

Retorno: **0**.

```text
$ git diff --exit-code HEAD -- config/params.yaml
```

Retorno: **0**, saída vazia.

```text
$ git diff HEAD~3 --exit-code -- src/motor/forecast/base.py src/motor/policy/base.py
```

Retorno: **0**, saída vazia.

```text
$ git diff HEAD~3 --stat -- src/motor/inventory.py src/motor/policy/supplier.py src/motor/policy/guardrails.py src/motor/policy/basestock.py src/motor/metrics/financial.py src/motor/io/loaders.py src/motor/io/raw.py src/motor/simulator/engine.py
```

Retorno: **0**, saída vazia.

```text
$ git diff --exit-code HEAD~3 -- .claude/ data/ results/
```

Retorno: **0**, saída vazia.

O retorno 1 do grep de asserts significa **nenhuma ocorrência**, não falha de validação. As sete referências acima são docstrings. HEAD~3 inclui as rodadas anteriores: seu diff mostra apenas a adição autorizada do bloco purchase_list na rodada 2. O diff contra HEAD, desta rodada, é vazio.

```text
$ uv run pytest -q --no-cov tests/test_architecture.py tests/test_financial.py tests/test_purchase_list.py::test_item_decision_accepts_unmodified_repository_params
....................                                                     [100%]
20 passed in 0.80s
```

Retorno: **0**.

```text
$ uv run python (leitura da base .coverage pela API Coverage.analysis2)
src/motor/reporting/purchase_list.py 343/370 = 92.702703%
src/motor/experiments/monthly_report.py 328/334 = 98.203593%
TOTAL 3566/4087 = 87.252263%
```

Retorno: **0**.

### G7 — revalidação dos mutantes nesta rodada

Além das mutações temporárias de arquivo já documentadas na Fase 4, os
três mutantes foram **reexecutados nesta rodada somente em memória**.
Comando `uv run python` lê financial.py, substitui uma única expressão,
executa `exec(compile(...), module.__dict__)` em um subprocesso novo para
cada mutante e chama `pytest.main` com `--no-cov -p no:cacheprovider` e o
teste `test_financial_losses_and_margin_match_exact_manual_totals_excluding_warmup`.
O controlador exige retorno 1 E “1 failed”, para não confundir erro de
importação/sintaxe com mutante morto. Nenhuma escrita no módulo congelado.

| Mutante | Falha real no item A | Saída do teste isolado |
|---|---|---|
| Ruptura usa preço | 70,0 em vez de 21,0 | `1 failed in 0.12s`, exit 1 |
| Perda usa preço | 30,0 em vez de 21,0 | `1 failed in 0.06s`, exit 1 |
| Margem usa demanda | 54,0 em vez de 33,0 | `1 failed in 0.06s`, exit 1 |

O comando do controlador terminou com **3/3 mutantes mortos em memória;
nenhum arquivo-fonte alterado**. `git diff --exit-code
src/motor/metrics/financial.py`: vazio, retorno 0. Sem mutação, os 14 testes
financeiros passaram no grupo focado de 20 testes e na suíte completa.

### Portões G1–G12 — somente evidências desta rodada

| Portão | Comando/verificação executado | Resultado real | Estado |
|---|---|---|---|
| G1 Testes | `uv run pytest -q -p no:cacheprovider` | 509 passed, 1 skipped, 3 deselected, 0 xfail; 61,77 s | ✅ |
| G2 Lint/formato | `uv run ruff check .`; `uv run ruff format --check .` | All checks passed!; 110 files already formatted | ✅ |
| G3 Tipos | `uv run mypy src/`; grep type: ignore | 47 fontes sem erros; 39 ignores (piso de partida 39) | ✅ |
| G4 Camadas | pytest focado com `tests/test_architecture.py`, financeiro e positivo | 20 passed in 0.80s, incluindo os 5 casos de arquitetura; zero imports proibidos na AST | ✅ |
| G5 Params reais | Mesmo grupo, `test_item_decision_accepts_unmodified_repository_params` | Passou com YAML sem alterações e grade global intacta | ✅ |
| G6 Golden | Suítes completa e Fase 8; `git diff --exit-code tests/golden/` | Quatro cenários passam; diff vazio, retorno 0; hash preservado | ✅ |
| G7 Financeiro | Controlador Python com três mutantes em memória; pytest financeiro; diff financeiro | 3/3 mortos nesta rodada; 14 testes verdes sem mutação; diff vazio | ✅ |
| G8 Cobertura | Suíte final com `--cov=motor --cov-report=term-missing` do addopts; leitura pela API coverage | Total 87,2523%; lista 92,7027%; mensal 98,2036%; fail_under 85 ativo | ✅ |
| G9 Determinismo | Comando dos quatro módulos exigidos na Fase 8, incluindo `tests/test_reporting_determinism.py`; suíte final | 61 passed in 27.61s no último ciclo; inclui os 3 testes de determinismo, abaixo de 30s até somados aos demais | ✅ |
| G10 Segurança | uv lock/sync; dois uv export + uvx pip-audit; uvx bandit | Exports retornam 0; upgrade/sync/auditores retornam 2 por DNS. Sem contagem de vulnerabilidades ou achados | ❌ |
| G11 Documentação | Releitura D11; validação dos CSVs, emendas, links e diff da Sprint 24 | Cinco contradições esclarecidas, 5 modelos válidos, decisões/coleta prontas; emendas preservadas | ✅ |
| G12 Escopo | git status/stat; diffs de congelados, contratos, params, .claude/data/results; validação dos valores YAML | 8 congelados e 2 protocolos intactos inclusive contra HEAD~3; zero alteração de params nesta rodada; somente +6 linhas históricas da rodada 2 | ✅ |

G10 **não aprovado**: Fase 9 permanece pendente para o Rafael com rede.
CI validado localmente, ainda sem execução remota. Regressão final do
Favorita cabe ao Felipe; a confirmação da rodada 2 veio pelo Rafael,
não representa execução local nem validação deste estado final.

### Antes/depois da sprint inteira — Fase 0 contra estado final

| Medida | Fase 0 | Final |
|---|---:|---:|
| Testes aprovados | 451 | 509 (+58) |
| Skip / deselected / xfail | 1 / 3 / 1 | 1 / 3 / 0 |
| Cobertura total de linhas | 78,7781% (3159/4010) | 87,2523% (3566/4087) |
| Lista de compra, linhas | 63,0499% (215/341) | 92,7027% (343/370) |
| Relatório mensal, linhas | 31,8182% (105/330) | 98,2036% (328/334) |
| type: ignore em src/ | 39 | 39 |
| Imports AST proibidos | 6 | 0 |
| Assert em src/ | 4 | 0 (grep e AST) |
| Funções da lista >80 linhas | 3 (109/98/83) | 0; máximo 75 |
| Tempo pytest -q com cobertura | 10,15 s | 61,77 s (sem cacheprovider) |
| Tempo da suíte sem cobertura | Não medido na Fase 0 | 34,82 s |
| Vulnerabilidades | Pillow/Tornado/SoupSieve sinalizados na avaliação externa, sem contagem auditada | Não auditadas por rede; mesmas versões, correção pendente |

Percentuais acima são de **linhas**, comparáveis aos da Fase 0. A medição
com branch da Fase 0 foi 78% e a da rodada 3 foi 86,0952%; não misturar
essas medidas com o 87,2523% de linhas da rodada final. O piso 85 mantém a
margem pedida em relação à medição combinada anterior.
O tempo aumentou com as simulações reais dos quatro cenários, variantes de
configuração e determinismo. As duas suítes finais estão abaixo de 90 s.

O golden continua cobrindo **7/7**: pedido emitido, fornecedor fora do
calendário (pela ausência), exceção, item novo, variação, teto de cobertura e
restrição de caixa. Nenhum caminho ficou de fora; quatro cenários intactos.
Hash SHA-256: `108bb537631c9bcfed216c41b26e723ea9d0f187a98778c17ea2c1445f42c125`.

### Arquivos desta rodada, por fase

- Pendências da rodada 3: `src/motor/experiments/run.py` (somente a guarda),
  `tests/test_run.py` (novo teste, funções antigas preservadas por comparação
  AST), `pyproject.toml` (somente fail_under 86→85 e comentário).
- Fase 8: `src/motor/reporting/purchase_list.py`, helpers privados; import
  novo `SupplierOrderResult` de `motor.policy.supplier`. No teste do runner,
  acrescentado `from motor.experiments import run as run_module` para
  simular previsões ausentes. Nenhum import de produto para experimento.
- Fase 9: **nenhum arquivo alterado**; uv.lock permanece byte a byte no HEAD.
- Fase 10: `.gitignore`; novos `.github/workflows/ci.yml` e `AGENTS.md`.
- Fase 11: `CLAUDE.md`, `README.md`, `docs/sprints/sprint24.md`;
  novos `docs/decisoes_em_aberto.md`, `docs/coleta/dicionario_de_dados.md`,
  `docs/coleta/roteiro_exportacao.md`, `docs/coleta/modelos/sales.csv`,
  `items.csv`, `suppliers.csv`, `stock.csv`, `entries.csv`.
- Fases 8–13: `docs/sprints/sprint25.md` atualizado em cada fase.
- **Nenhum arquivo movido nesta rodada**, nenhum notebook alterado.
  Total: 9 arquivos rastreados modificados e 10 novos ainda não rastreados;
  git diff --stat não inclui os novos, que estão listados no git status.

### Decisões pendentes e responsáveis

A lista única completa está em `docs/decisoes_em_aberto.md`:

| Decisão | Responsável | O que falta |
|---|---|---|
| Média mínima e dias com venda para censura (dois null) | Felipe + dado real, com validação da dona | Vendas/recebimentos e casos reais de ruptura versus baixa demanda |
| Janela de avaliação (null) | Dona + Felipe | Acordo de acompanhamento e histórico disponível; 8–12 semanas ainda é proposta |
| Meia-vida GBM (null neutro) | Felipe | Comparação temporal dedicada sem vazamento |
| Alpha 0,66 da lista | Felipe + dona | Serviço, margem, falta/sobra e capital no dado real |
| Overrides 7/14 → null | Dona + Felipe + cadastro real | Prazos individuais e rotina de compra verificados |
| Orçamento por ciclo de 14 dias | Dona, com Felipe | Caixa e calendário de pagamentos/compras |
| Adaptador ERP, fardo/mínimos reais e 24.7 ausente | Felipe | Amostra do ERP, mapeamento e escopo confirmado; Fase 12 segue excluída |
| Recomparação de braços/iso-serviço com baseline recalibrado | Felipe | Experimentos e relatórios atualizados antes de divulgação, pendência preservada da Sprint 24 |
| Hook pessoal e regressão final Favorita | Felipe | Decidir configuração local; rodar com data e baseline disponíveis |
| Atualização e auditorias de segurança | Rafael | Rede para PyPI e serviços de vulnerabilidades, seguida de checks |

### Comandos para o Rafael e para o Felipe

Rafael (execução manual, nenhum comando Git mutável foi executado pelo agente):

```bash
git rm --cached .claude/scheduled_tasks.lock
uv lock --upgrade-package pillow --upgrade-package tornado --upgrade-package soupsieve
git diff --stat uv.lock
git diff uv.lock
uv sync
uv run pytest -q -p no:cacheprovider
uv export --no-dev --no-hashes --format requirements-txt > /tmp/req.txt && uvx pip-audit -r /tmp/req.txt
uv export --no-hashes --format requirements-txt > /tmp/req.txt && uvx pip-audit -r /tmp/req.txt
uvx bandit -r src -ll
rm /tmp/req.txt
```

Conferir as versões antes de aceitar o upgrade. Se outro pacote de produção
mudar (inclusive scipy, além dos pins diretos), restaurar **somente uv.lock**
com `git show HEAD:uv.lock > uv.lock`, executar `uv sync` e registrar o motivo.
A auditoria e os testes não podem ser declarados aprovados por antecipação.

Felipe, sobre o estado final e na máquina que tem data/ e a referência:

```bash
uv run pytest -m regression --no-cov tests/test_regression_favorita.py
```

Decidir se os hooks pessoais de `.claude/settings.json` devem ir para
`.claude/settings.local.json` (já ignorado). Sem comando automático para
isso; nada em .claude/ foi editado. Nenhum backtest novo nesta rodada.

### Mensagens de commit sugeridas — não executadas

- Pendências da rodada 3: `fix: validar previsões do runner e ajustar piso de cobertura`.
- Fase 8: `refactor: reduzir funções da lista de compra preservando o golden`.
- Fase 9, **somente após upgrade e auditoria reais**: `chore: atualizar dependências vulneráveis` (não há diff dessa fase agora).
- Fase 10: `ci: verificar qualidade e documentar contrato para agentes`.
- Fase 11: `docs: alinhar contratos e preparar coleta do mercado piloto`.
- Fase 13: `docs: registrar portões finais e pendências da Sprint 25`.

### Autorrevisão final R1–R14 — toda a sprint

| Regra | Evidência e conclusão |
|---|---|
| R1 Git | Apenas comandos de leitura; status mostra zero alterações no índice. Commits das rodadas anteriores feitos pelo Rafael; nenhum pelo agente |
| R2 Branch | Conferida antes do trabalho: feat/correcoes-motor, nunca main |
| R3 Congelados | Diffs vazios dos 8 arquivos nesta rodada e contra HEAD~3. Só mutações temporárias autorizadas na Fase 4; restauradas e hash conferido. Revalidação final exclusivamente em memória |
| R4 Contratos | forecast/base.py e policy/base.py sem diff inclusive contra HEAD~3 |
| R5 Premissas | YAML comparado estruturalmente com HEAD~3: todos os valores antigos iguais. Só +6 linhas do bloco purchase_list da rodada 2; diff contra HEAD vazio; quatro null intactos |
| R6 Números | Alpha, prazos e período do orçamento vêm da configuração. Nenhum novo valor de negócio fixado no produto; CSVs/testes identificados como fictícios |
| R7 Dependências | Nenhuma adição ao pyproject; só piso autorizado e comentário. uv.lock intacto; upgrade limitado tentado, bloqueado por DNS. Sem pip/curl/wget |
| R8 Escopo | Diffs .claude/data/results vazios em toda a sprint. Fase 9 autorizou uv sync (exceção ao bloqueio anterior de .venv). Temporários em /tmp removidos. Tentativa inicial de uvx escrever no diretório pessoal foi bloqueada, sem contornar a restrição; execução seguinte usou diretório temporário permitido |
| R9 Testes | Nenhum teste antigo afrouxado/apagado; imports movidos na Fase 3. Única remoção de xfail substituída por positivo, conforme autorização. Funções antigas de test_run.py idênticas por AST |
| R10 Maquiagem | 39 ignores antes/depois; nenhum noqa, pragma, skip ou xfail novo; nenhum omit/afrouxamento do pytest/coverage. Piso final 85 expressamente pedido; grep xfail em src/tests/pyproject vazio |
| R11 Dados | Fixtures e 10 linhas dos cinco CSVs sintéticas; nenhum dado de cliente ou Favorita adicionado |
| R12 Negócio | Nenhum null preenchido, alpha/cadência/orçamento recalibrado; decisões e responsáveis registrados |
| R13 Estilo | Helpers privados, tipagem e docstrings portuguesas; polars; Ruff e mypy verdes; ordem/cálculos/textos e determinismo preservados pelo golden e XLSX |
| R14 Registro | Este arquivo atualizado por fase; escopo, comandos, resultados e limitações de todas as rodadas preservados |

Desvios/ressalvas, inclusive pequenos, sem esconder o histórico:

1. Na rodada 3, o assert do runner foi preservado por decisão expressa do
   Rafael (“Preservar run.py nesta rodada”), deixando o grep global vermelho.
   A autorização nova permitiu somente a guarda; pendência agora resolvida.
2. Na Fase 3, `iso_service.cell_suppliers` manteve um pequeno adaptador para
   os defaults experimentais 7/14, em vez de reexportação pura, preservando
   chamadores e resultados legados. Os demais nomes continuam reexportados.
3. Referências antigas em docstrings de basestock/financial não foram
   atualizadas porque esses módulos são congelados. O grep final retorna
   sete linhas de docstrings, nenhuma importação; a AST valida zero violações.
4. Na rodada 2 foram apagados dois bytecodes ignorados e obsoletos sob
   reporting/__pycache__, para não contaminar o grep de model_copy. Nenhum
   arquivo de fonte ou diretório proibido foi apagado nessa limpeza.
5. R8 teve a exceção explícita de sincronização pedida na Fase 9. A tentativa
   inicial de uvx usar ~/.local/share/uv/tools foi negada pelo filesystem;
   não foi uma aprovação concedida nem uma escrita bem-sucedida. Temporários
   permitidos foram usados depois, sem bypass de rede. `ps` de diagnóstico
   também foi negado pelo sandbox; sem efeito sobre o trabalho.
6. Fase 9 e G10 não concluídos por DNS. Não houve correção nem auditoria de
   vulnerabilidades, nem mudança no lock. Esse limite é a alternativa
   expressamente autorizada no pedido; não foi mascarado como verde.
7. Piso inicialmente 86 na rodada 3 e agora 85, com comentário, por pedido
   explícito. Nenhuma outra configuração ou dependência alterada. As
   supressões/skip preexistentes e as três desmarcações foram mantidas.
8. Fase 12 continua fora do escopo; não é implementação concluída. Não houve
   regeneração do golden após a Fase 1, mudança permanente dos congelados,
   decisão comercial oculta ou comando Git mutável em nenhuma rodada.

<!-- SPRINT25_STATUS_START -->

```text
$ git status --untracked-files=all
On branch feat/correcoes-motor
Your branch is up to date with 'origin/feat/correcoes-motor'.

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   .gitignore
	modified:   CLAUDE.md
	modified:   README.md
	modified:   docs/sprints/sprint24.md
	modified:   docs/sprints/sprint25.md
	modified:   pyproject.toml
	modified:   src/motor/experiments/run.py
	modified:   src/motor/reporting/purchase_list.py
	modified:   tests/test_run.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	.github/workflows/ci.yml
	AGENTS.md
	docs/coleta/dicionario_de_dados.md
	docs/coleta/modelos/entries.csv
	docs/coleta/modelos/items.csv
	docs/coleta/modelos/sales.csv
	docs/coleta/modelos/stock.csv
	docs/coleta/modelos/suppliers.csv
	docs/coleta/roteiro_exportacao.md
	docs/decisoes_em_aberto.md

no changes added to commit (use "git add" and/or "git commit -a")

$ git diff --stat
 .gitignore                           |   1 +
 CLAUDE.md                            |  95 +++--
 README.md                            |  65 +++-
 docs/sprints/sprint24.md             |   3 +-
 docs/sprints/sprint25.md             | 711 ++++++++++++++++++++++++++++++++++-
 pyproject.toml                       |   3 +-
 src/motor/experiments/run.py         |   4 +-
 src/motor/reporting/purchase_list.py | 143 +++++--
 tests/test_run.py                    |  24 ++
 9 files changed, 991 insertions(+), 58 deletions(-)
```

<!-- SPRINT25_STATUS_END -->

**Ponto final da rodada 4:** Fases 8, 10, 11 e 13 concluídas localmente;
Fase 9 bloqueada por rede, G10 pendente; Fase 12 excluída. Regressão final
Favorita e publicação/commits ficam com Rafael/Felipe. Nenhum commit feito.
