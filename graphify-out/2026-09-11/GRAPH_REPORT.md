# Graph Report - mercado  (2026-09-11)

## Corpus Check
- 58 files · ~54,632 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1061 nodes · 2387 edges · 49 communities (35 shown, 7 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 209 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5a541be1`
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
- run.py
- InventoryState
- NaiveForecaster
- erp_calibration.py
- DecisionContext
- test_simulator.py
- config.py
- build_analytic_scenario
- Simulator
- build_simulator_for_pair
- test_contracts.py
- valid_suppliers
- StatisticalForecaster
- test_features_build.py
- test_features_calendar.py
- test_selection.py
- Forecaster
- select_subset
- SpyForecaster
- BasestockPolicy
- test_erp_baseline.py
- _Bound
- tests/__init__.py
- fakes.py
- SchemaValidationError
- FeatureCalendarParams
- Params
- Item
- features/__init__.py
- test_determinismo_do_cap_por_familia
- test_determinismo_do_cap_desempate_dentro_da_familia

## God Nodes (most connected - your core abstractions)
1. `InventoryState` - 42 edges
2. `validate_table()` - 37 edges
3. `Params` - 31 edges
4. `run_arm()` - 26 edges
5. `build_canonical_favorita()` - 26 edges
6. `ParamsSection` - 24 edges
7. `StatisticalForecaster` - 24 edges
8. `apply_supplier_constraints()` - 24 edges
9. `NaiveForecaster` - 23 edges
10. `WindowQuantileForecast` - 22 edges

## Surprising Connections (you probably didn't know these)
- `Referência a 'Sprint 17' (cabeçalho do arquivo)` --references--> `Plano de sprints (0 a 5)`  [AMBIGUOUS]
  config/params.yaml → CLAUDE.md
- `_tiny_params()` --uses--> `SubsetSelectionParams`  [INFERRED]
  tests/test_run.py → src/motor/config.py
- `_tiny_params()` --uses--> `SimulationParams`  [INFERRED]
  tests/test_run.py → src/motor/config.py
- `_params()` --uses--> `FeatureCalendarParams`  [INFERRED]
  tests/test_features_build.py → src/motor/config.py
- `_params()` --uses--> `FeatureHistoricoParams`  [INFERRED]
  tests/test_features_build.py → src/motor/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Métrica de decisão financeira: margem, capital e guardrails** — claude_metricas_financeiras, config_params_economics, config_params_guardrails_config [INFERRED 0.75]
- **Contratos internos: Forecaster, Policy, DecisionContext, Simulador** — claude_forecaster, claude_policy, claude_decisioncontext, claude_simulador [INFERRED 0.85]
- **Três braços experimentais comparados pelo simulador** — config_params_arm_erp_baseline, config_params_arm_estatistico_basestock, config_params_arm_quantile_gbm_basestock, claude_sprints [INFERRED 0.85]

## Communities (49 total, 7 thin omitted)

### Community 0 - "validate_table"
Cohesion: 0.19
Nodes (7): Valida um DataFrame contra um contrato pydantic, de forma vetorizada. Levanta…, validate_table(), Tolerância de dtype é em uma direção só: int->float ok, float->int não., Upcast seguro: coluna int satisfaz contrato float., TestViolacoesDeValor, TestViolacoesEstruturais, valid_sales()

### Community 1 - "contracts.py"
Cohesion: 0.12
Nodes (36): _column_presence_violations(), _constraint_violations(), _default_required_columns(), _dtype_for_primitive(), _dtype_is_compatible(), _dtype_violations(), _enum_column_violations(), expected_polars_schema() (+28 more)

### Community 2 - "profiling.py"
Cohesion: 0.09
Nodes (39): count_candidates(), profile_calendar(), profile_fractional_by_item(), profile_fractional_global(), profile_item_volume(), profile_negatives_by_item(), profile_negatives_global(), profile_pair_coverage() (+31 more)

### Community 3 - "Simulador (centro do sistema)"
Cohesion: 0.08
Nodes (37): Armadilhas conhecidas, Política basestock (nível-alvo), DecisionContext (dataclass), Política erp_baseline, Previsão naive (média móvel + quantis empíricos), Previsão quantile_gbm (LightGBM, perda pinball), Previsão estatística (sazonal simples + desvio), Protocol Forecaster (+29 more)

### Community 4 - "WindowQuantileForecast"
Cohesion: 0.12
Nodes (28): compute_order_quantity(), Política de nível-alvo (Sprint 11): `compute_order_quantity`. Lógica pura --…, Nível-alvo: `target_level = quantil alpha da demanda acumulada na janela`;…, Previsão de demanda ACUMULADA na janela de risco (lead_time + ciclo de revisão)…, Saída de `compute_order_quantity`. `target_level` e `position_used` são…, TargetLevelDecision, WindowQuantileForecast, parametrize (+20 more)

### Community 5 - "loaders.py"
Cohesion: 0.05
Nodes (84): AnomalyPeriodParams, CanonicalParams, Premissas de fornecedor usadas quando o cadastro não traz o dado.…, Um período de distorção conhecida na série (Sprint 3, D1: ex. terremoto). Marca…, Parâmetros da normalização canônica do Favorita (Sprint 3, `motor.io.loaders`).…, SupplierAssumptionsParams, _apply_anomalies(), build_canonical_favorita() (+76 more)

### Community 6 - "apply_supplier_constraints"
Cohesion: 0.08
Nodes (54): skipif, StrEnum, Uma linha de cadastro no grão fornecedor. `order_days` e `review_period_days`…, Unidade de venda do item: por unidade discreta ou por peso. Esta é a distinção…, Supplier, UnitOfSale, AdjustmentReason, apply_supplier_constraints() (+46 more)

### Community 7 - "test_smoke.py"
Cohesion: 0.40
Nodes (3): Teste de fumaça: garante que o pacote instala e importa corretamente., Confirma que o pacote `motor` pode ser importado a partir do layout src/., test_import_motor()

### Community 17 - "raw.py"
Cohesion: 0.10
Nodes (32): ArgumentParser, _build_arg_parser(), main(), LazyFrame, Path, PolarsDtype, ValueError, Carregamento bruto do dataset Favorita: CSV -> parquet sem transformar nada.… (+24 more)

### Community 18 - "run.py"
Cohesion: 0.05
Nodes (88): RuntimeError, ExperimentArmParams, Um braço de experimento: nome, forecaster e política usados., ArmRunResult, BasestockCalibrationManifest, _build_forecaster(), _build_manifest(), _build_policy() (+80 more)

### Community 19 - "InventoryState"
Cohesion: 0.08
Nodes (39): _chave_fefo(), InventoryState, Lote, PedidoEmTransito, date, Estado de estoque de um par loja-item: `InventoryState`. Fonte única de verdade…, Avança a data corrente e recebe pedidos em trânsito já chegados. Não expira…, Remove os lotes vencidos na data corrente e devolve o total perdido. Usa `<`… (+31 more)

### Community 20 - "NaiveForecaster"
Cohesion: 0.10
Nodes (32): _empirical_quantile(), NaiveForecaster, DataFrame, date, Previsão ingênua (`NaiveForecaster`): média móvel de N semanas sobre a demanda…, Erros históricos da própria média móvel. Para cada dia `t` do histórico visível…, Quantil empírico por interpolação linear sobre uma lista JÁ ordenada…, Média móvel de `moving_average_weeks` semanas + quantis empíricos dos resíduos… (+24 more)

### Community 21 - "erp_calibration.py"
Cohesion: 0.11
Nodes (31): CalibrationItem, CalibrationResult, _choose(), GridResult, _precompute_forecasts(), _PrecomputedForecaster, DataFrame, date (+23 more)

### Community 22 - "DecisionContext"
Cohesion: 0.15
Nodes (10): DecisionContext, Protocolo `Policy` e `DecisionContext`, no grão de um único par loja-item. Ver…, Tudo que uma política vê para decidir quanto pedir, para um par loja-item.…, Unidades a pedir, antes das regras de guarda (sprint futura: ainda não existem)., ErpBaselinePolicy, Política do braço 1 (ERP baseline, Sprint 7): pedido = média das últimas…, Sem quantil, sem alfa, sem janela de risco derivada -- ver docstring do módulo., `target = mu_daily x moving_average_days x factor`; pedido = `target -… (+2 more)

### Community 23 - "test_simulator.py"
Cohesion: 0.15
Nodes (19): Calendário de revisão: verdadeiro a cada `period_days` dias, a partir de…, review_every_n_days(), _dias(), date, Testes do loop diário do simulador (`motor.simulator.engine.Simulator`).…, S + f: a folga aparece como deslocamento no estoque médio (+f exato), não como…, Lead time (10) maior que o período de revisão (5): na segunda revisão, o pedido…, Lead time = 1: o pedido feito na revisão do dia 0 chega no dia 1 e atende, no… (+11 more)

### Community 24 - "config.py"
Cohesion: 0.10
Nodes (28): DataParams, EconomicsParams, ErpBaselineParams, ExperimentsParams, FeatureHistoricoParams, ForecastNaiveParams, ForecastStatisticalParams, GuardrailsParams (+20 more)

### Community 25 - "build_analytic_scenario"
Cohesion: 0.08
Nodes (44): build_item_economics(), compute_financial_metrics(), compute_portfolio_metrics(), ItemEconomics, ItemFinancialMetrics, MissingItemEconomicsError, PortfolioFinancialMetrics, _priced_events() (+36 more)

### Community 26 - "Simulator"
Cohesion: 0.14
Nodes (17): Policy, Protocol, Decide quanto pedir para um par loja-item., DailyEvent, _in_transit(), DataFrame, date, Loop diário do simulador, para um único par loja-item (CLAUDE.md, seção 6).… (+9 more)

### Community 27 - "build_simulator_for_pair"
Cohesion: 0.15
Nodes (22): build_simulator_for_pair(), initial_stock_units(), DataFrame, date, Premissas de simulação compartilhadas entre TODOS os braços (Sprint 7, seção 1…, Estoque inicial arbitrado: cobertura de um ciclo de risco (lead_time +…, Monta o `Simulator` de um par loja-item com as premissas compartilhadas desta…, ConstantForecaster (+14 more)

### Community 28 - "test_contracts.py"
Cohesion: 0.21
Nodes (8): Verifica integridade referencial entre as tabelas canônicas. Todo `item_id` em…, validate_referential_integrity(), DataFrame, Testes dos contratos das tabelas canônicas (motor.io.contracts). Cada teste de…, TestIntegridadeReferencial, TestRequiredNonNullGancho, valid_items(), valid_stock()

### Community 29 - "valid_suppliers"
Cohesion: 0.24
Nodes (8): max_cyclic_order_gap(), Maior intervalo, em dias, entre dois dias de pedido consecutivos de…, Verifica que `review_period_days` cobre o maior intervalo entre dias de pedido.…, validate_supplier_order_cadence(), parametrize, review_period_days == max_gap é suficiente, não precisa sobrar folga., TestConsistenciaCadenciaFornecedor, valid_suppliers()

### Community 30 - "StatisticalForecaster"
Cohesion: 0.09
Nodes (39): _empirical_quantile(), DataFrame, date, Previsão estatística (`StatisticalForecaster`, Sprint 12): nível recente…, Guarda `history` (já filtrado por `date < as_of` pelo simulador) num dicionário…, Ponto central = soma da previsão diária (nível x índice sazonal) nos `horizon`…, Índice multiplicativo por dia ISO da semana, medido na janela `[cutoff -…, Média dos valores deseasonalizados na janela `[cutoff - level_window_days,… (+31 more)

### Community 31 - "test_features_build.py"
Cohesion: 0.12
Nodes (44): FeaturesParams, Parâmetros de `motor.features` (Sprint 14). `active_features` é a lista exata…, build_features(), build_training_matrix(), _days_since_last_promo(), _days_since_last_sale(), _lag_feature(), DataFrame (+36 more)

### Community 32 - "test_features_calendar.py"
Cohesion: 0.11
Nodes (42): build_calendar_features(), _days_to_payday(), _effective_holiday_dates(), _last_day_of_month(), load_holidays(), load_store_locale(), DataFrame, date (+34 more)

### Community 33 - "test_selection.py"
Cohesion: 0.12
Nodes (28): Critério de seleção do subconjunto de trabalho (Sprint 4). Uma loja, 150-300…, Parâmetros do loop diário do simulador (CLAUDE.md, seção 6). `start_date` é…, SimulationParams, SubsetSelectionParams, _cenario_duas_familias(), _daterange(), _item_row(), _item_with_pattern() (+20 more)

### Community 34 - "Forecaster"
Cohesion: 0.22
Nodes (8): Forecaster, DataFrame, date, Protocol, Protocolo `Forecaster`, no grão de um único par loja-item. Este protocolo é…, Previsão de demanda para um único par loja-item., Ajusta o modelo a `history`. `history` contém apenas linhas com `date < as_of`…, Devolve colunas `quantile`, `value`: demanda ACUMULADA nos próximos `horizon`…

### Community 35 - "select_subset"
Cohesion: 0.14
Nodes (24): _assert_no_leakage(), _cap_by_family(), _density_by_item(), _exclude_degenerate_families(), _exclude_promo_dominated(), _funnel_row(), LeakageGuardError, _lifespan_complete() (+16 more)

### Community 36 - "SpyForecaster"
Cohesion: 0.33
Nodes (5): DataFrame, date, Previsão de mentira que registra cada chamada, para provar a garantia de "sem…, SpyForecaster, test_forecaster_nunca_recebe_historico_com_data_maior_ou_igual_ao_as_of()

### Community 37 - "BasestockPolicy"
Cohesion: 0.19
Nodes (12): BasestockPolicy, Política de nível-alvo, no grão de um par loja-item (Sprint 12).…, Contrato `Policy`: nível-alvo = quantil `alpha` da demanda acumulada na janela…, _ctx(), DataFrame, Testes de `motor.policy.basestock.BasestockPolicy` (Sprint 12).…, Propaga o erro de `compute_order_quantity` (Sprint 11) sem mascarar --…, Documenta a limitação conhecida (ver docstring de `BasestockPolicy`):… (+4 more)

### Community 38 - "test_erp_baseline.py"
Cohesion: 0.27
Nodes (13): _ctx(), _policy(), Testes de `motor.policy.erp_baseline.ErpBaselinePolicy` (Sprint 7)., O piso só se aplica quando HÁ pedido -- nunca é gatilho pra pedir sem…, Duas políticas com `horizon_days` diferentes, mas cuja mediana do forecast…, Ignorar `in_transit` é o bug clássico (CLAUDE.md, seção 5) -- este teste falha…, test_forecast_sem_quantile_0_5_levanta_value_error(), test_order_com_apenas_in_transit_ja_desconta_posicao_inteira() (+5 more)

### Community 41 - "fakes.py"
Cohesion: 0.25
Nodes (5): AnalyticScenario, Fakes para os testes do simulador: previsão e política de mentira.…, Em regime permanente, cada revisão pede exatamente d x R., d x (R + 1) / 2 em regime permanente. Não é d x R / 2: essa é a aproximação…, Cenário de demanda constante + política order-up-to, com resultado conhecido em…

### Community 42 - "SchemaValidationError"
Cohesion: 0.50
Nodes (3): ValueError, Erro de validação de uma tabela canônica. A mensagem lista todas as violações…, SchemaValidationError

### Community 43 - "FeatureCalendarParams"
Cohesion: 0.33
Nodes (4): model_validator, FeatureCalendarParams, Parâmetros de `motor.features.calendar` (Sprint 14): início de mês, quinzena e…, `compute_order_quantity` (motor.policy.target_level, regra do enunciado)…

### Community 44 - "Params"
Cohesion: 0.28
Nodes (12): load_params(), Params, Path, Todas as premissas numéricas do projeto, carregadas de `config/params.yaml`., Carrega `params.yaml` e valida contra `Params`., Testes do modelo Params e do arquivo config/params.yaml do repositório., test_params_aceita_alpha_que_bate_com_a_grade_de_quantis(), test_params_rejeita_category_alpha_fora_da_grade_de_quantis() (+4 more)

### Community 45 - "Item"
Cohesion: 0.20
Nodes (8): Item, Uma linha de saldo de estoque no grão loja x item x dia. Esta é a tabela que o…, Uma linha de cadastro no grão item. `ean`, `pack_multiple`, `cost` e…, Stock, load_stock(), Tabela `stock` vazia, no schema canônico (D9). O Favorita não tem saldo de…, TestExemplosValidos, test_d9_stock_vazio_valida_contra_schema()

## Ambiguous Edges - Review These
- `Plano de sprints (0 a 5)` → `Referência a 'Sprint 17' (cabeçalho do arquivo)`  [AMBIGUOUS]
  config/params.yaml · relation: references

## Knowledge Gaps
- **10 isolated node(s):** `motor`, `Dataset Favorita`, `Parâmetros de guardrails (teto de cobertura, variação, orçamento)`, `Parâmetros de modelo (quantis, cadência de re-treino)`, `Parâmetros de simulação (warmup_days, seed, datas)` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 378 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Plano de sprints (0 a 5)` and `Referência a 'Sprint 17' (cabeçalho do arquivo)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `InventoryState` connect `InventoryState` to `SpyForecaster`, `WindowQuantileForecast`, `test_simulator.py`, `build_analytic_scenario`, `Simulator`, `build_simulator_for_pair`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `build_simulator_for_pair()` connect `build_simulator_for_pair` to `Forecaster`, `run.py`, `InventoryState`, `erp_calibration.py`, `test_simulator.py`, `Simulator`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `Params` connect `Params` to `test_selection.py`, `select_subset`, `loaders.py`, `FeatureCalendarParams`, `run.py`, `config.py`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Are the 27 inferred relationships involving `InventoryState` (e.g. with `_in_transit()` and `Simulator`) actually correct?**
  _`InventoryState` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `Params` (e.g. with `_build_forecaster()` and `_build_manifest()`) actually correct?**
  _`Params` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `build_canonical_favorita()` (e.g. with `Params` and `Item`) actually correct?**
  _`build_canonical_favorita()` has 4 INFERRED edges - model-reasoned connections that need verification._