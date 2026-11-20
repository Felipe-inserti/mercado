# Sprint 25 — Motor pronto para o dado real

Execução parcial em **20/11/2026**. Rodada 1: **Fases 0 e 1**, commitadas pelo
Rafael em `74383fe`. Rodada 2: **Fases 2 e 3**, commitadas em `fbcfce3`.
Rodada 3: **Fases 4 a 7**, conforme pedido anexado pelo Rafael.
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
