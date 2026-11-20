# Sprint 25 — Motor pronto para o dado real

Execução parcial em **20/11/2026**. Rodada 1: **Fases 0 e 1**, commitadas pelo
Rafael em `74383fe`. Rodada 2: **Fases 2 e 3**, autorizadas na nova mensagem.
Especificação: `PROMPT_CODEX_sprint25.md`; `EXECUTAR_FASE_BACKTEST: não`.
O agente não executa commits. O registro da rodada 1 abaixo é histórico;
os resultados da rodada 2 são acrescentados ao final.

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
