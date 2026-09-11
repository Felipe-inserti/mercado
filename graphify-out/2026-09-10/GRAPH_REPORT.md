# Graph Report - mercado  (2026-09-10)

## Corpus Check
- 47 files · ~42,801 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 848 nodes · 1877 edges · 43 communities (30 shown, 6 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 150 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- validate_table
- contracts.py
- profiling.py
- Simulador (centro do sistema)
- select_subset
- test_loaders.py
- apply_supplier_constraints
- test_smoke.py
- Janelas de profiling (12 vs 24 meses)
- motor
- raw.py
- run.py
- InventoryState
- NaiveForecaster
- erp_calibration.py
- ErpBaselinePolicy
- test_simulator.py
- config.py
- build_analytic_scenario
- Simulator
- OrderUpToPolicy
- valid_suppliers
- SchemaValidationError
- engine.py
- loaders.py
- build_simulator_for_pair
- test_selection.py
- Forecaster
- Params
- SpyForecaster
- TableRow
- test_determinismo_do_cap_por_familia
- _Bound
- tests/__init__.py
- test_determinismo_do_cap_desempate_dentro_da_familia
- _assert_no_leakage

## God Nodes (most connected - your core abstractions)
1. `InventoryState` - 40 edges
2. `validate_table()` - 37 edges
3. `Params` - 27 edges
4. `build_canonical_favorita()` - 26 edges
5. `run_arm()` - 25 edges
6. `apply_supplier_constraints()` - 24 edges
7. `NaiveForecaster` - 23 edges
8. `ParamsSection` - 20 edges
9. `load_sales()` - 20 edges
10. `select_subset()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `Referência a 'Sprint 17' (cabeçalho do arquivo)` --references--> `Plano de sprints (0 a 5)`  [AMBIGUOUS]
  config/params.yaml → CLAUDE.md
- `_tiny_params()` --uses--> `SubsetSelectionParams`  [INFERRED]
  tests/test_run.py → src/motor/config.py
- `_tiny_params()` --uses--> `SubsetSelectionParams`  [INFERRED]
  tests/test_selection.py → src/motor/config.py
- `_tiny_params()` --uses--> `SimulationParams`  [INFERRED]
  tests/test_run.py → src/motor/config.py
- `_tiny_params()` --uses--> `SimulationParams`  [INFERRED]
  tests/test_selection.py → src/motor/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Métrica de decisão financeira: margem, capital e guardrails** — claude_metricas_financeiras, config_params_economics, config_params_guardrails_config [INFERRED 0.75]
- **Contratos internos: Forecaster, Policy, DecisionContext, Simulador** — claude_forecaster, claude_policy, claude_decisioncontext, claude_simulador [INFERRED 0.85]
- **Três braços experimentais comparados pelo simulador** — config_params_arm_erp_baseline, config_params_arm_estatistico_basestock, config_params_arm_quantile_gbm_basestock, claude_sprints [INFERRED 0.85]

## Communities (43 total, 6 thin omitted)

### Community 0 - "validate_table"
Cohesion: 0.19
Nodes (7): Valida um DataFrame contra um contrato pydantic, de forma vetorizada. Levanta…, validate_table(), Tolerância de dtype é em uma direção só: int->float ok, float->int não., Upcast seguro: coluna int satisfaz contrato float., TestViolacoesDeValor, TestViolacoesEstruturais, valid_sales()

### Community 1 - "contracts.py"
Cohesion: 0.15
Nodes (30): _column_presence_violations(), _constraint_violations(), _default_required_columns(), _dtype_for_primitive(), _dtype_is_compatible(), _dtype_violations(), _enum_column_violations(), _extract_bounds() (+22 more)

### Community 2 - "profiling.py"
Cohesion: 0.09
Nodes (39): count_candidates(), profile_calendar(), profile_fractional_by_item(), profile_fractional_global(), profile_item_volume(), profile_negatives_by_item(), profile_negatives_global(), profile_pair_coverage() (+31 more)

### Community 3 - "Simulador (centro do sistema)"
Cohesion: 0.08
Nodes (37): Armadilhas conhecidas, Política basestock (nível-alvo), DecisionContext (dataclass), Política erp_baseline, Previsão naive (média móvel + quantis empíricos), Previsão quantile_gbm (LightGBM, perda pinball), Previsão estatística (sazonal simples + desvio), Protocol Forecaster (+29 more)

### Community 4 - "select_subset"
Cohesion: 0.19
Nodes (19): _cap_by_family(), _density_by_item(), _exclude_degenerate_families(), _exclude_promo_dominated(), _funnel_row(), _lifespan_complete(), _pairs_for_store(), DataFrame (+11 more)

### Community 5 - "test_loaders.py"
Cohesion: 0.06
Nodes (67): AnomalyPeriodParams, CanonicalParams, Premissas de fornecedor usadas quando o cadastro não traz o dado.…, Um período de distorção conhecida na série (Sprint 3, D1: ex. terremoto). Marca…, Parâmetros da normalização canônica do Favorita (Sprint 3, `motor.io.loaders`).…, SupplierAssumptionsParams, _apply_anomalies(), _build_family_to_supplier_id() (+59 more)

### Community 6 - "apply_supplier_constraints"
Cohesion: 0.09
Nodes (51): StrEnum, Uma linha de cadastro no grão fornecedor. `order_days` e `review_period_days`…, Unidade de venda do item: por unidade discreta ou por peso. Esta é a distinção…, Supplier, UnitOfSale, AdjustmentReason, apply_supplier_constraints(), _assert_matching_item_ids() (+43 more)

### Community 7 - "test_smoke.py"
Cohesion: 0.40
Nodes (3): Teste de fumaça: garante que o pacote instala e importa corretamente., Confirma que o pacote `motor` pode ser importado a partir do layout src/., test_import_motor()

### Community 17 - "raw.py"
Cohesion: 0.10
Nodes (32): ArgumentParser, _build_arg_parser(), main(), LazyFrame, Path, PolarsDtype, ValueError, Carregamento bruto do dataset Favorita: CSV -> parquet sem transformar nada.… (+24 more)

### Community 18 - "run.py"
Cohesion: 0.06
Nodes (80): RuntimeError, ExperimentArmParams, Um braço de experimento: nome, forecaster e política usados., ArmRunResult, _build_forecaster(), _build_manifest(), ErpBaselineCalibrationManifest, _evaluation_start() (+72 more)

### Community 19 - "InventoryState"
Cohesion: 0.08
Nodes (39): _chave_fefo(), InventoryState, Lote, PedidoEmTransito, date, Estado de estoque de um par loja-item: `InventoryState`. Fonte única de verdade…, Avança a data corrente e recebe pedidos em trânsito já chegados. Não expira…, Remove os lotes vencidos na data corrente e devolve o total perdido. Usa `<`… (+31 more)

### Community 20 - "NaiveForecaster"
Cohesion: 0.10
Nodes (32): _empirical_quantile(), NaiveForecaster, DataFrame, date, Previsão ingênua (`NaiveForecaster`): média móvel de N semanas sobre a demanda…, Erros históricos da própria média móvel. Para cada dia `t` do histórico visível…, Quantil empírico por interpolação linear sobre uma lista JÁ ordenada…, Média móvel de `moving_average_weeks` semanas + quantis empíricos dos resíduos… (+24 more)

### Community 21 - "erp_calibration.py"
Cohesion: 0.11
Nodes (31): CalibrationItem, CalibrationResult, _choose(), GridResult, _precompute_forecasts(), _PrecomputedForecaster, DataFrame, date (+23 more)

### Community 22 - "ErpBaselinePolicy"
Cohesion: 0.15
Nodes (19): _build_policy(), ErpBaselinePolicy, Sem quantil, sem alfa, sem janela de risco derivada -- ver docstring do módulo., `target = mu_daily x moving_average_days x factor`; pedido = `target -…, _ctx(), _policy(), parametrize, Testes de `motor.policy.erp_baseline.ErpBaselinePolicy` (Sprint 7). (+11 more)

### Community 23 - "test_simulator.py"
Cohesion: 0.12
Nodes (23): _in_transit(), Calendário de revisão: verdadeiro a cada `period_days` dias, a partir de…, Calendário de revisão: dias fixos da semana (ISO, 1=segunda .. 7=domingo)., Unidades em trânsito: posição total menos o que já está em mãos.…, review_every_n_days(), review_on_weekdays(), _dias(), date (+15 more)

### Community 24 - "config.py"
Cohesion: 0.11
Nodes (24): DataParams, EconomicsParams, ErpBaselineParams, ExperimentsParams, ForecastNaiveParams, GuardrailsParams, ModelParams, ParamsSection (+16 more)

### Community 25 - "build_analytic_scenario"
Cohesion: 0.07
Nodes (48): build_item_economics(), compute_financial_metrics(), compute_portfolio_metrics(), ItemEconomics, ItemFinancialMetrics, MissingItemEconomicsError, PortfolioFinancialMetrics, _priced_events() (+40 more)

### Community 26 - "Simulator"
Cohesion: 0.23
Nodes (9): DailyEvent, DataFrame, date, `demand`: tabela verdade com colunas `date`, `units_sold` -- a demanda real de…, Roda o loop de `start` a `end` (inclusive), um evento por dia. Não há caso…, Monta o `DecisionContext`, chama a política e agenda o pedido, se houver., Um dia de simulação, registrado depois que todos os passos do loop ocorreram.…, Loop diário do simulador, para um único par loja-item. (+1 more)

### Community 27 - "OrderUpToPolicy"
Cohesion: 0.19
Nodes (15): ConstantForecaster, OrderUpToPolicy, Fakes para os testes do simulador: previsão e política de mentira.…, Previsão de mentira: demanda diária constante, acumulada no horizonte.…, Política de mentira: pede até completar o nível-alvo `S` (order-up-to).…, _demand_constante(), DataFrame, date (+7 more)

### Community 28 - "valid_suppliers"
Cohesion: 0.18
Nodes (10): Verifica integridade referencial entre as tabelas canônicas. Todo `item_id` em…, validate_referential_integrity(), DataFrame, Testes dos contratos das tabelas canônicas (motor.io.contracts). Cada teste de…, TestExemplosValidos, TestIntegridadeReferencial, TestRequiredNonNullGancho, valid_items() (+2 more)

### Community 29 - "SchemaValidationError"
Cohesion: 0.17
Nodes (10): max_cyclic_order_gap(), ValueError, Erro de validação de uma tabela canônica. A mensagem lista todas as violações…, Maior intervalo, em dias, entre dois dias de pedido consecutivos de…, Verifica que `review_period_days` cobre o maior intervalo entre dias de pedido.…, SchemaValidationError, validate_supplier_order_cadence(), parametrize (+2 more)

### Community 30 - "engine.py"
Cohesion: 0.19
Nodes (9): DecisionContext, Policy, Protocol, Protocolo `Policy` e `DecisionContext`, no grão de um único par loja-item. Ver…, Tudo que uma política vê para decidir quanto pedir, para um par loja-item.…, Decide quanto pedir para um par loja-item., Unidades a pedir, antes das regras de guarda (sprint futura: ainda não existem)., Política do braço 1 (ERP baseline, Sprint 7): pedido = média das últimas… (+1 more)

### Community 31 - "loaders.py"
Cohesion: 0.14
Nodes (24): expected_polars_schema(), Item, Uma linha de saldo de estoque no grão loja x item x dia. Esta é a tabela que o…, Uma linha de cadastro no grão item. `ean`, `pack_multiple`, `cost` e…, Deriva o schema polars esperado (coluna -> dtype) a partir do modelo pydantic.…, Stock, build_canonical_favorita(), CanonicalManifest (+16 more)

### Community 32 - "build_simulator_for_pair"
Cohesion: 0.31
Nodes (8): build_simulator_for_pair(), initial_stock_units(), DataFrame, date, Premissas de simulação compartilhadas entre TODOS os braços (Sprint 7, seção 1…, Estoque inicial arbitrado: cobertura de um ciclo de risco (lead_time +…, Monta o `Simulator` de um par loja-item com as premissas compartilhadas desta…, test_initial_stock_units_usa_so_os_dias_do_warmup_nao_o_historico_inteiro()

### Community 33 - "test_selection.py"
Cohesion: 0.12
Nodes (26): Critério de seleção do subconjunto de trabalho (Sprint 4). Uma loja, 150-300…, Parâmetros do loop diário do simulador (CLAUDE.md, seção 6). `start_date` é…, SimulationParams, SubsetSelectionParams, _cenario_duas_familias(), _daterange(), _item_row(), _item_with_pattern() (+18 more)

### Community 34 - "Forecaster"
Cohesion: 0.22
Nodes (8): Forecaster, DataFrame, date, Protocol, Protocolo `Forecaster`, no grão de um único par loja-item. Este protocolo é…, Previsão de demanda para um único par loja-item., Ajusta o modelo a `history`. `history` contém apenas linhas com `date < as_of`…, Devolve colunas `quantile`, `value`: demanda ACUMULADA nos próximos `horizon`…

### Community 35 - "Params"
Cohesion: 0.24
Nodes (11): load_params(), Params, Path, Todas as premissas numéricas do projeto, carregadas de `config/params.yaml`., Carrega `params.yaml` e valida contra `Params`., Testes do modelo Params e do arquivo config/params.yaml do repositório., test_params_rejeita_chave_desconhecida(), test_params_rejeita_fracao_fora_do_intervalo() (+3 more)

### Community 36 - "SpyForecaster"
Cohesion: 0.33
Nodes (5): DataFrame, date, Previsão de mentira que registra cada chamada, para provar a garantia de "sem…, SpyForecaster, test_forecaster_nunca_recebe_historico_com_data_maior_ou_igual_ao_as_of()

### Community 37 - "TableRow"
Cohesion: 0.50
Nodes (4): Classe-base das quatro tabelas canônicas. Imutável (`frozen`), sem colunas além…, Uma linha de venda no grão loja x item x dia. `units_returned` é uma coluna…, Sale, TableRow

### Community 43 - "_assert_no_leakage"
Cohesion: 0.40
Nodes (5): _assert_no_leakage(), LeakageGuardError, ValueError, A fatia de densidade (D3) tem que terminar estritamente antes do loop do…, `subset_selection.density_window_end` alcança ou ultrapassa…

## Ambiguous Edges - Review These
- `Plano de sprints (0 a 5)` → `Referência a 'Sprint 17' (cabeçalho do arquivo)`  [AMBIGUOUS]
  config/params.yaml · relation: references

## Knowledge Gaps
- **10 isolated node(s):** `motor`, `Dataset Favorita`, `Parâmetros de guardrails (teto de cobertura, variação, orçamento)`, `Parâmetros de modelo (quantis, cadência de re-treino)`, `Parâmetros de simulação (warmup_days, seed, datas)` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 304 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Plano de sprints (0 a 5)` and `Referência a 'Sprint 17' (cabeçalho do arquivo)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `build_simulator_for_pair()` connect `build_simulator_for_pair` to `Forecaster`, `run.py`, `InventoryState`, `erp_calibration.py`, `test_simulator.py`, `Simulator`, `OrderUpToPolicy`, `engine.py`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Why does `InventoryState` connect `InventoryState` to `build_simulator_for_pair`, `SpyForecaster`, `test_simulator.py`, `build_analytic_scenario`, `Simulator`, `engine.py`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Why does `NaiveForecaster` connect `NaiveForecaster` to `run.py`, `erp_calibration.py`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `InventoryState` (e.g. with `_in_transit()` and `Simulator`) actually correct?**
  _`InventoryState` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `Params` (e.g. with `_build_forecaster()` and `_build_manifest()`) actually correct?**
  _`Params` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `build_canonical_favorita()` (e.g. with `Params` and `Item`) actually correct?**
  _`build_canonical_favorita()` has 4 INFERRED edges - model-reasoned connections that need verification._