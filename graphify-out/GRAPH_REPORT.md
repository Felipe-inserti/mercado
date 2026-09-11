# Graph Report - mercado  (2026-09-10)

## Corpus Check
- 53 files · ~49,431 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 964 nodes · 2130 edges · 44 communities (32 shown, 5 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 201 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8a2168ce`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- validate_table
- contracts.py
- profiling.py
- Simulador (centro do sistema)
- WindowQuantileForecast
- loaders.py
- apply_supplier_constraints
- test_smoke.py
- Janelas de profiling (12 vs 24 meses)
- motor
- raw.py
- test_run.py
- InventoryState
- NaiveForecaster
- erp_calibration.py
- DecisionContext
- test_simulator.py
- Params
- test_financial.py
- Simulator
- OrderUpToPolicy
- test_contracts.py
- valid_suppliers
- StatisticalForecaster
- run.py
- build_simulator_for_pair
- select_subset
- Forecaster
- run_arm
- SpyForecaster
- TableRow
- _tiny_params
- _Bound
- tests/__init__.py
- AnalyticScenario
- SchemaValidationError
- ._alpha_bate_com_a_grade_de_quantis

## God Nodes (most connected - your core abstractions)
1. `InventoryState` - 42 edges
2. `validate_table()` - 37 edges
3. `Params` - 31 edges
4. `run_arm()` - 26 edges
5. `build_canonical_favorita()` - 26 edges
6. `StatisticalForecaster` - 24 edges
7. `apply_supplier_constraints()` - 24 edges
8. `NaiveForecaster` - 23 edges
9. `WindowQuantileForecast` - 22 edges
10. `ParamsSection` - 21 edges

## Surprising Connections (you probably didn't know these)
- `Referência a 'Sprint 17' (cabeçalho do arquivo)` --references--> `Plano de sprints (0 a 5)`  [AMBIGUOUS]
  config/params.yaml → CLAUDE.md
- `_tiny_params()` --uses--> `SubsetSelectionParams`  [INFERRED]
  tests/test_run.py → src/motor/config.py
- `_tiny_params()` --uses--> `SimulationParams`  [INFERRED]
  tests/test_run.py → src/motor/config.py
- `_tiny_params()` --uses--> `CanonicalParams`  [INFERRED]
  tests/test_run.py → src/motor/config.py
- `_tiny_params()` --uses--> `CanonicalParams`  [INFERRED]
  tests/test_selection.py → src/motor/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Métrica de decisão financeira: margem, capital e guardrails** — claude_metricas_financeiras, config_params_economics, config_params_guardrails_config [INFERRED 0.75]
- **Contratos internos: Forecaster, Policy, DecisionContext, Simulador** — claude_forecaster, claude_policy, claude_decisioncontext, claude_simulador [INFERRED 0.85]
- **Três braços experimentais comparados pelo simulador** — config_params_arm_erp_baseline, config_params_arm_estatistico_basestock, config_params_arm_quantile_gbm_basestock, claude_sprints [INFERRED 0.85]

## Communities (44 total, 5 thin omitted)

### Community 0 - "validate_table"
Cohesion: 0.16
Nodes (8): Valida um DataFrame contra um contrato pydantic, de forma vetorizada. Levanta…, validate_table(), Tolerância de dtype é em uma direção só: int->float ok, float->int não., Upcast seguro: coluna int satisfaz contrato float., TestExemplosValidos, TestViolacoesDeValor, TestViolacoesEstruturais, valid_sales()

### Community 1 - "contracts.py"
Cohesion: 0.14
Nodes (33): _column_presence_violations(), _constraint_violations(), _default_required_columns(), _dtype_for_primitive(), _dtype_is_compatible(), _dtype_violations(), _enum_column_violations(), expected_polars_schema() (+25 more)

### Community 2 - "profiling.py"
Cohesion: 0.09
Nodes (39): count_candidates(), profile_calendar(), profile_fractional_by_item(), profile_fractional_global(), profile_item_volume(), profile_negatives_by_item(), profile_negatives_global(), profile_pair_coverage() (+31 more)

### Community 3 - "Simulador (centro do sistema)"
Cohesion: 0.08
Nodes (37): Armadilhas conhecidas, Política basestock (nível-alvo), DecisionContext (dataclass), Política erp_baseline, Previsão naive (média móvel + quantis empíricos), Previsão quantile_gbm (LightGBM, perda pinball), Previsão estatística (sazonal simples + desvio), Protocol Forecaster (+29 more)

### Community 4 - "WindowQuantileForecast"
Cohesion: 0.07
Nodes (44): _build_policy(), `alpha` só é usado pelo braço `basestock` -- `erp_baseline` não deriva nada de…, BasestockPolicy, Política de nível-alvo, no grão de um par loja-item (Sprint 12).…, Contrato `Policy`: nível-alvo = quantil `alpha` da demanda acumulada na janela…, compute_order_quantity(), Política de nível-alvo (Sprint 11): `compute_order_quantity`. Lógica pura --…, Nível-alvo: `target_level = quantil alpha da demanda acumulada na janela`;… (+36 more)

### Community 5 - "loaders.py"
Cohesion: 0.05
Nodes (91): AnomalyPeriodParams, CanonicalParams, Premissas de fornecedor usadas quando o cadastro não traz o dado.…, Um período de distorção conhecida na série (Sprint 3, D1: ex. terremoto). Marca…, Parâmetros da normalização canônica do Favorita (Sprint 3, `motor.io.loaders`).…, SupplierAssumptionsParams, Item, Uma linha de saldo de estoque no grão loja x item x dia. Esta é a tabela que o… (+83 more)

### Community 6 - "apply_supplier_constraints"
Cohesion: 0.08
Nodes (53): skipif, Uma linha de cadastro no grão fornecedor. `order_days` e `review_period_days`…, Unidade de venda do item: por unidade discreta ou por peso. Esta é a distinção…, Supplier, UnitOfSale, AdjustmentReason, apply_supplier_constraints(), _assert_matching_item_ids() (+45 more)

### Community 7 - "test_smoke.py"
Cohesion: 0.40
Nodes (3): Teste de fumaça: garante que o pacote instala e importa corretamente., Confirma que o pacote `motor` pode ser importado a partir do layout src/., test_import_motor()

### Community 17 - "raw.py"
Cohesion: 0.10
Nodes (32): ArgumentParser, _build_arg_parser(), main(), LazyFrame, Path, PolarsDtype, ValueError, Carregamento bruto do dataset Favorita: CSV -> parquet sem transformar nada.… (+24 more)

### Community 18 - "test_run.py"
Cohesion: 0.17
Nodes (28): Saída de `select_subset`: loja, lista final de itens, e o funil que sustenta a…, SubsetSelectionResult, _cache_path_pre_populado(), _canonical_dir_com_parquets(), _cenario_dois_itens(), _cenario_um_item(), _daterange(), _item_row() (+20 more)

### Community 19 - "InventoryState"
Cohesion: 0.08
Nodes (38): _chave_fefo(), InventoryState, Lote, PedidoEmTransito, date, Avança a data corrente e recebe pedidos em trânsito já chegados. Não expira…, Remove os lotes vencidos na data corrente e devolve o total perdido. Usa `<`…, Registra um pedido em trânsito, com a validade que o lote terá ao chegar.… (+30 more)

### Community 20 - "NaiveForecaster"
Cohesion: 0.10
Nodes (32): _empirical_quantile(), NaiveForecaster, DataFrame, date, Previsão ingênua (`NaiveForecaster`): média móvel de N semanas sobre a demanda…, Erros históricos da própria média móvel. Para cada dia `t` do histórico visível…, Quantil empírico por interpolação linear sobre uma lista JÁ ordenada…, Média móvel de `moving_average_weeks` semanas + quantis empíricos dos resíduos… (+24 more)

### Community 21 - "erp_calibration.py"
Cohesion: 0.11
Nodes (31): CalibrationItem, CalibrationResult, _choose(), GridResult, _precompute_forecasts(), _PrecomputedForecaster, DataFrame, date (+23 more)

### Community 22 - "DecisionContext"
Cohesion: 0.12
Nodes (22): DecisionContext, Tudo que uma política vê para decidir quanto pedir, para um par loja-item.…, Unidades a pedir, antes das regras de guarda (sprint futura: ainda não existem)., ErpBaselinePolicy, Política do braço 1 (ERP baseline, Sprint 7): pedido = média das últimas…, Sem quantil, sem alfa, sem janela de risco derivada -- ver docstring do módulo., `target = mu_daily x moving_average_days x factor`; pedido = `target -…, _ctx() (+14 more)

### Community 23 - "test_simulator.py"
Cohesion: 0.12
Nodes (24): Calendário de revisão: verdadeiro a cada `period_days` dias, a partir de…, Calendário de revisão: dias fixos da semana (ISO, 1=segunda .. 7=domingo)., review_every_n_days(), review_on_weekdays(), build_analytic_scenario(), Monta o cenário d, L, R, S = d x (L + R) + `slack`, pronto para…, _dias(), date (+16 more)

### Community 24 - "Params"
Cohesion: 0.08
Nodes (40): DataParams, EconomicsParams, ErpBaselineParams, ExperimentArmParams, ExperimentsParams, ForecastNaiveParams, ForecastStatisticalParams, GuardrailsParams (+32 more)

### Community 25 - "test_financial.py"
Cohesion: 0.09
Nodes (40): build_item_economics(), compute_financial_metrics(), compute_portfolio_metrics(), ItemEconomics, ItemFinancialMetrics, MissingItemEconomicsError, PortfolioFinancialMetrics, _priced_events() (+32 more)

### Community 26 - "Simulator"
Cohesion: 0.18
Nodes (12): DailyEvent, _in_transit(), DataFrame, date, `demand`: tabela verdade com colunas `date`, `units_sold` -- a demanda real de…, Roda o loop de `start` a `end` (inclusive), um evento por dia. Não há caso…, Monta o `DecisionContext`, chama a política e agenda o pedido, se houver., Um dia de simulação, registrado depois que todos os passos do loop ocorreram.… (+4 more)

### Community 27 - "OrderUpToPolicy"
Cohesion: 0.19
Nodes (15): ConstantForecaster, OrderUpToPolicy, Fakes para os testes do simulador: previsão e política de mentira.…, Previsão de mentira: demanda diária constante, acumulada no horizonte.…, Política de mentira: pede até completar o nível-alvo `S` (order-up-to).…, _demand_constante(), DataFrame, date (+7 more)

### Community 28 - "test_contracts.py"
Cohesion: 0.21
Nodes (8): Verifica integridade referencial entre as tabelas canônicas. Todo `item_id` em…, validate_referential_integrity(), DataFrame, Testes dos contratos das tabelas canônicas (motor.io.contracts). Cada teste de…, TestIntegridadeReferencial, TestRequiredNonNullGancho, valid_items(), valid_stock()

### Community 29 - "valid_suppliers"
Cohesion: 0.24
Nodes (8): max_cyclic_order_gap(), Maior intervalo, em dias, entre dois dias de pedido consecutivos de…, Verifica que `review_period_days` cobre o maior intervalo entre dias de pedido.…, validate_supplier_order_cadence(), parametrize, review_period_days == max_gap é suficiente, não precisa sobrar folga., TestConsistenciaCadenciaFornecedor, valid_suppliers()

### Community 30 - "StatisticalForecaster"
Cohesion: 0.09
Nodes (39): _empirical_quantile(), DataFrame, date, Previsão estatística (`StatisticalForecaster`, Sprint 12): nível recente…, Guarda `history` (já filtrado por `date < as_of` pelo simulador) num dicionário…, Ponto central = soma da previsão diária (nível x índice sazonal) nos `horizon`…, Índice multiplicativo por dia ISO da semana, medido na janela `[cutoff -…, Média dos valores deseasonalizados na janela `[cutoff - level_window_days,… (+31 more)

### Community 31 - "run.py"
Cohesion: 0.15
Nodes (26): ArmRunResult, BasestockCalibrationManifest, _build_manifest(), ErpBaselineCalibrationManifest, FinancialAssumptionsManifest, _find_arm(), _git_commit_hash(), _hash_file() (+18 more)

### Community 32 - "build_simulator_for_pair"
Cohesion: 0.15
Nodes (15): build_simulator_for_pair(), initial_stock_units(), DataFrame, date, Premissas de simulação compartilhadas entre TODOS os braços (Sprint 7, seção 1…, Estoque inicial arbitrado: cobertura de um ciclo de risco (lead_time +…, Monta o `Simulator` de um par loja-item com as premissas compartilhadas desta…, Protocolo `Forecaster`, no grão de um único par loja-item. Este protocolo é… (+7 more)

### Community 33 - "select_subset"
Cohesion: 0.06
Nodes (56): Critério de seleção do subconjunto de trabalho (Sprint 4). Uma loja, 150-300…, Parâmetros do loop diário do simulador (CLAUDE.md, seção 6). `start_date` é…, SimulationParams, SubsetSelectionParams, _assert_no_leakage(), _cap_by_family(), _density_by_item(), _exclude_degenerate_families() (+48 more)

### Community 34 - "Forecaster"
Cohesion: 0.28
Nodes (7): Forecaster, DataFrame, date, Protocol, Previsão de demanda para um único par loja-item., Ajusta o modelo a `history`. `history` contém apenas linhas com `date < as_of`…, Devolve colunas `quantile`, `value`: demanda ACUMULADA nos próximos `horizon`…

### Community 35 - "run_arm"
Cohesion: 0.16
Nodes (16): RuntimeError, _evaluation_start(), _events_to_dataframe(), load_or_select_subset(), DataFrame, date, LazyFrame, Lê `cache_path` se existir e o hash bater; senão roda `select_subset` (que… (+8 more)

### Community 36 - "SpyForecaster"
Cohesion: 0.33
Nodes (5): DataFrame, date, Previsão de mentira que registra cada chamada, para provar a garantia de "sem…, SpyForecaster, test_forecaster_nunca_recebe_historico_com_data_maior_ou_igual_ao_as_of()

### Community 37 - "TableRow"
Cohesion: 0.50
Nodes (4): Classe-base das quatro tabelas canônicas. Imutável (`frozen`), sem colunas além…, Uma linha de venda no grão loja x item x dia. `units_returned` é uma coluna…, Sale, TableRow

### Community 38 - "_tiny_params"
Cohesion: 0.21
Nodes (12): _build_forecaster(), Hash determinístico só dos campos de `Params` que afetam `select_subset` -- não…, _selection_params_hash(), `erp_baseline`/`forecast_naive` não entram no hash -- não afetam…, `params.yaml` real, com `canonical`/`subset_selection`/`simulation` trocados…, test_build_forecaster_desconhecido_levanta_value_error(), test_build_forecaster_statistical_devolve_statistical_forecaster(), test_find_arm_desconhecido_levanta_value_error() (+4 more)

### Community 41 - "AnalyticScenario"
Cohesion: 0.33
Nodes (4): AnalyticScenario, Em regime permanente, cada revisão pede exatamente d x R., d x (R + 1) / 2 em regime permanente. Não é d x R / 2: essa é a aproximação…, Cenário de demanda constante + política order-up-to, com resultado conhecido em…

### Community 42 - "SchemaValidationError"
Cohesion: 0.50
Nodes (3): ValueError, Erro de validação de uma tabela canônica. A mensagem lista todas as violações…, SchemaValidationError

## Ambiguous Edges - Review These
- `Plano de sprints (0 a 5)` → `Referência a 'Sprint 17' (cabeçalho do arquivo)`  [AMBIGUOUS]
  config/params.yaml · relation: references

## Knowledge Gaps
- **10 isolated node(s):** `motor`, `Dataset Favorita`, `Parâmetros de guardrails (teto de cobertura, variação, orçamento)`, `Parâmetros de modelo (quantis, cadência de re-treino)`, `Parâmetros de simulação (warmup_days, seed, datas)` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 350 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Plano de sprints (0 a 5)` and `Referência a 'Sprint 17' (cabeçalho do arquivo)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `InventoryState` connect `InventoryState` to `build_simulator_for_pair`, `SpyForecaster`, `WindowQuantileForecast`, `test_simulator.py`, `Simulator`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `build_simulator_for_pair()` connect `build_simulator_for_pair` to `Forecaster`, `run_arm`, `InventoryState`, `erp_calibration.py`, `test_simulator.py`, `Simulator`, `OrderUpToPolicy`, `run.py`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Why does `StatisticalForecaster` connect `StatisticalForecaster` to `_tiny_params`, `run.py`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Are the 27 inferred relationships involving `InventoryState` (e.g. with `_in_transit()` and `Simulator`) actually correct?**
  _`InventoryState` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `Params` (e.g. with `_build_forecaster()` and `_build_manifest()`) actually correct?**
  _`Params` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `build_canonical_favorita()` (e.g. with `Params` and `Item`) actually correct?**
  _`build_canonical_favorita()` has 4 INFERRED edges - model-reasoned connections that need verification._