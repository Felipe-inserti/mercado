# Graph Report - mercado  (2026-09-11)

## Corpus Check
- 62 files · ~61,527 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1162 nodes · 2697 edges · 52 communities (39 shown, 6 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 237 edges (avg confidence: 0.94)
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
- convert_raw_to_parquet
- test_run.py
- InventoryState
- NaiveForecaster
- erp_calibration.py
- DecisionContext
- test_simulator.py
- config.py
- test_financial.py
- engine.py
- build_simulator_for_pair
- validate_referential_integrity
- valid_suppliers
- StatisticalForecaster
- test_features_build.py
- test_features_calendar.py
- test_selection.py
- run.py
- select_subset
- SpyForecaster
- BasestockPolicy
- test_erp_baseline.py
- _Bound
- tests/__init__.py
- inventory.py
- _tiny_params
- quantile_gbm.py
- Params
- expected_polars_schema
- features/__init__.py
- test_determinismo_do_cap_por_familia
- run_arm
- load_or_select_subset
- basestock.py
- _assert_no_leakage

## God Nodes (most connected - your core abstractions)
1. `InventoryState` - 42 edges
2. `validate_table()` - 37 edges
3. `Params` - 33 edges
4. `run_arm()` - 33 edges
5. `train_quantile_models()` - 28 edges
6. `build_canonical_favorita()` - 26 edges
7. `ParamsSection` - 25 edges
8. `StatisticalForecaster` - 25 edges
9. `build_features()` - 24 edges
10. `NaiveForecaster` - 24 edges

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

## Communities (52 total, 6 thin omitted)

### Community 0 - "validate_table"
Cohesion: 0.13
Nodes (13): ValueError, Valida um DataFrame contra um contrato pydantic, de forma vetorizada. Levanta…, validate_table(), DataFrame, Testes dos contratos das tabelas canônicas (motor.io.contracts). Cada teste de…, Upcast seguro: coluna int satisfaz contrato float., TestExemplosValidos, TestRequiredNonNullGancho (+5 more)

### Community 1 - "contracts.py"
Cohesion: 0.16
Nodes (28): _column_presence_violations(), _constraint_violations(), _dtype_for_primitive(), _dtype_is_compatible(), _dtype_violations(), _enum_column_violations(), _extract_bounds(), _field_base_and_metadata() (+20 more)

### Community 2 - "profiling.py"
Cohesion: 0.09
Nodes (39): count_candidates(), profile_calendar(), profile_fractional_by_item(), profile_fractional_global(), profile_item_volume(), profile_negatives_by_item(), profile_negatives_global(), profile_pair_coverage() (+31 more)

### Community 3 - "Simulador (centro do sistema)"
Cohesion: 0.08
Nodes (37): Armadilhas conhecidas, Política basestock (nível-alvo), DecisionContext (dataclass), Política erp_baseline, Previsão naive (média móvel + quantis empíricos), Previsão quantile_gbm (LightGBM, perda pinball), Previsão estatística (sazonal simples + desvio), Protocol Forecaster (+29 more)

### Community 4 - "WindowQuantileForecast"
Cohesion: 0.14
Nodes (25): compute_order_quantity(), Nível-alvo: `target_level = quantil alpha da demanda acumulada na janela`;…, Previsão de demanda ACUMULADA na janela de risco (lead_time + ciclo de revisão)…, WindowQuantileForecast, parametrize, Testes de `motor.policy.target_level` (Sprint 11). Lógica pura, sem estatística…, Quantis não se somam nem podem ser desordenados: um q90 menor que o q70 é, por…, Demanda acumulada na janela segue Uniform(50, 250) -- distribuição analítica… (+17 more)

### Community 5 - "loaders.py"
Cohesion: 0.05
Nodes (86): AnomalyPeriodParams, CanonicalParams, Premissas de fornecedor usadas quando o cadastro não traz o dado.…, Um período de distorção conhecida na série (Sprint 3, D1: ex. terremoto). Marca…, Parâmetros da normalização canônica do Favorita (Sprint 3, `motor.io.loaders`).…, SupplierAssumptionsParams, Item, Uma linha de cadastro no grão item. `ean`, `pack_multiple`, `cost` e… (+78 more)

### Community 6 - "apply_supplier_constraints"
Cohesion: 0.08
Nodes (53): skipif, Uma linha de cadastro no grão fornecedor. `order_days` e `review_period_days`…, Unidade de venda do item: por unidade discreta ou por peso. Esta é a distinção…, Supplier, UnitOfSale, AdjustmentReason, apply_supplier_constraints(), _assert_matching_item_ids() (+45 more)

### Community 7 - "test_smoke.py"
Cohesion: 0.40
Nodes (3): Teste de fumaça: garante que o pacote instala e importa corretamente., Confirma que o pacote `motor` pode ser importado a partir do layout src/., test_import_motor()

### Community 17 - "convert_raw_to_parquet"
Cohesion: 0.11
Nodes (34): ArgumentParser, _build_arg_parser(), convert_raw_to_parquet(), main(), LazyFrame, Path, PolarsDtype, ValueError (+26 more)

### Community 18 - "test_run.py"
Cohesion: 0.18
Nodes (27): Saída de `select_subset`: loja, lista final de itens, e o funil que sustenta a…, SubsetSelectionResult, _cache_path_pre_populado(), _canonical_dir_com_parquets(), _cenario_dois_itens(), _cenario_um_item(), _daterange(), _item_row() (+19 more)

### Community 19 - "InventoryState"
Cohesion: 0.15
Nodes (26): InventoryState, Estoque em mãos MAIS tudo que está em trânsito (já pedido, não recebido). Esta…, Apenas o estoque físico disponível agora, sem o que está em trânsito., Posição de estoque de um par loja-item, com pipeline e lotes com validade. Ver…, _dias(), date, Testes de `InventoryState` -- estado isolado, sem simulação, sem dado real.…, Bateria de operações com resultado calculado à mão. D0: recebe 10 (validade… (+18 more)

### Community 20 - "NaiveForecaster"
Cohesion: 0.10
Nodes (32): _empirical_quantile(), NaiveForecaster, DataFrame, date, Previsão ingênua (`NaiveForecaster`): média móvel de N semanas sobre a demanda…, Média de `units_sold` nos dias em `[cutoff - window_days, cutoff)` presentes no…, Erros históricos da própria média móvel. Para cada dia `t` do histórico visível…, Quantil empírico por interpolação linear sobre uma lista JÁ ordenada… (+24 more)

### Community 21 - "erp_calibration.py"
Cohesion: 0.11
Nodes (31): CalibrationItem, CalibrationResult, _choose(), GridResult, _precompute_forecasts(), _PrecomputedForecaster, DataFrame, date (+23 more)

### Community 22 - "DecisionContext"
Cohesion: 0.17
Nodes (10): DecisionContext, Protocolo `Policy` e `DecisionContext`, no grão de um único par loja-item. Ver…, Tudo que uma política vê para decidir quanto pedir, para um par loja-item.…, Unidades a pedir, antes das regras de guarda (sprint futura: ainda não existem)., ErpBaselinePolicy, Política do braço 1 (ERP baseline, Sprint 7): pedido = média das últimas…, Sem quantil, sem alfa, sem janela de risco derivada -- ver docstring do módulo., `target = mu_daily x moving_average_days x factor`; pedido = `target -… (+2 more)

### Community 23 - "test_simulator.py"
Cohesion: 0.13
Nodes (21): Calendário de revisão: verdadeiro a cada `period_days` dias, a partir de…, Calendário de revisão: dias fixos da semana (ISO, 1=segunda .. 7=domingo)., review_every_n_days(), review_on_weekdays(), _dias(), date, Testes do loop diário do simulador (`motor.simulator.engine.Simulator`).…, S + f: a folga aparece como deslocamento no estoque médio (+f exato), não como… (+13 more)

### Community 24 - "config.py"
Cohesion: 0.10
Nodes (28): DataParams, EconomicsParams, ErpBaselineParams, ExperimentsParams, FeatureHistoricoParams, ForecastNaiveParams, ForecastStatisticalParams, GuardrailsParams (+20 more)

### Community 25 - "test_financial.py"
Cohesion: 0.06
Nodes (54): _load_manifest(), main(), Gráfico e tabela do relatório final da Sprint 15: comparação dos três braços…, build_item_economics(), compute_financial_metrics(), compute_portfolio_metrics(), daily_net_margin(), ItemEconomics (+46 more)

### Community 26 - "engine.py"
Cohesion: 0.14
Nodes (18): Forecaster, Protocol, Previsão de demanda para um único par loja-item., Policy, Protocol, Decide quanto pedir para um par loja-item., DailyEvent, _in_transit() (+10 more)

### Community 27 - "build_simulator_for_pair"
Cohesion: 0.13
Nodes (23): build_simulator_for_pair(), initial_stock_units(), DataFrame, date, Premissas de simulação compartilhadas entre TODOS os braços (Sprint 7, seção 1…, Estoque inicial arbitrado: cobertura de um ciclo de risco (lead_time +…, Monta o `Simulator` de um par loja-item com as premissas compartilhadas desta…, ConstantForecaster (+15 more)

### Community 28 - "validate_referential_integrity"
Cohesion: 0.47
Nodes (3): Verifica integridade referencial entre as tabelas canônicas. Todo `item_id` em…, validate_referential_integrity(), TestIntegridadeReferencial

### Community 29 - "valid_suppliers"
Cohesion: 0.20
Nodes (9): max_cyclic_order_gap(), Maior intervalo, em dias, entre dois dias de pedido consecutivos de…, Verifica que `review_period_days` cobre o maior intervalo entre dias de pedido.…, validate_supplier_order_cadence(), parametrize, Tolerância de dtype é em uma direção só: int->float ok, float->int não., review_period_days == max_gap é suficiente, não precisa sobrar folga., TestConsistenciaCadenciaFornecedor (+1 more)

### Community 30 - "StatisticalForecaster"
Cohesion: 0.05
Nodes (62): DataFrame, date, Protocolo `Forecaster`, no grão de um único par loja-item. Este protocolo é…, A janela de risco: `[as_of, as_of + horizon - 1]`, INCLUINDO o próprio `as_of`…, `(início_inclusive, fim_exclusivo)` da mesma janela de `risk_window_dates` --…, Ajusta o modelo a `history`. `history` contém apenas linhas com `date < as_of`…, Devolve colunas `quantile`, `value`: demanda ACUMULADA nos próximos `horizon`…, risk_window_bounds() (+54 more)

### Community 31 - "test_features_build.py"
Cohesion: 0.19
Nodes (27): _build(), _build_synthetic_sales(), _calendar_for(), _items(), _params(), DataFrame, date, Testes de `motor.features.build` (Sprint 14). Cobre os dois casos de borda… (+19 more)

### Community 32 - "test_features_calendar.py"
Cohesion: 0.17
Nodes (29): load_holidays(), load_store_locale(), Path, Lê `stores.parquet` (bruto, Sprint 2) e devolve cidade/estado de `store_id`., Lê `holidays_events.parquet` (bruto, Sprint 2) por inteiro. Sem corte por data:…, _features(), _holiday_row(), _holidays() (+21 more)

### Community 33 - "test_selection.py"
Cohesion: 0.13
Nodes (27): Critério de seleção do subconjunto de trabalho (Sprint 4). Uma loja, 150-300…, Parâmetros do loop diário do simulador (CLAUDE.md, seção 6). `start_date` é…, SimulationParams, SubsetSelectionParams, _cenario_duas_familias(), _daterange(), _item_row(), _item_with_pattern() (+19 more)

### Community 34 - "run.py"
Cohesion: 0.11
Nodes (33): ExperimentArmParams, Um braço de experimento: nome, forecaster e política usados., BasestockCalibrationManifest, _build_manifest(), ErpBaselineCalibrationManifest, _evaluation_start(), FinancialAssumptionsManifest, _find_arm() (+25 more)

### Community 35 - "select_subset"
Cohesion: 0.15
Nodes (22): _cap_by_family(), _density_by_item(), _exclude_degenerate_families(), _exclude_promo_dominated(), _funnel_row(), _lifespan_complete(), _pairs_for_store(), DataFrame (+14 more)

### Community 36 - "SpyForecaster"
Cohesion: 0.33
Nodes (5): DataFrame, date, Previsão de mentira que registra cada chamada, para provar a garantia de "sem…, SpyForecaster, test_forecaster_nunca_recebe_historico_com_data_maior_ou_igual_ao_as_of()

### Community 37 - "BasestockPolicy"
Cohesion: 0.22
Nodes (11): BasestockPolicy, Contrato `Policy`: nível-alvo = quantil `alpha` da demanda acumulada na janela…, _ctx(), DataFrame, Testes de `motor.policy.basestock.BasestockPolicy` (Sprint 12).…, Propaga o erro de `compute_order_quantity` (Sprint 11) sem mascarar --…, Documenta a limitação conhecida (ver docstring de `BasestockPolicy`):…, test_order_com_alpha_ausente_no_forecast_levanta_erro_claro() (+3 more)

### Community 38 - "test_erp_baseline.py"
Cohesion: 0.27
Nodes (13): _ctx(), _policy(), Testes de `motor.policy.erp_baseline.ErpBaselinePolicy` (Sprint 7)., O piso só se aplica quando HÁ pedido -- nunca é gatilho pra pedir sem…, Duas políticas com `horizon_days` diferentes, mas cuja mediana do forecast…, Ignorar `in_transit` é o bug clássico (CLAUDE.md, seção 5) -- este teste falha…, test_forecast_sem_quantile_0_5_levanta_value_error(), test_order_com_apenas_in_transit_ja_desconta_posicao_inteira() (+5 more)

### Community 41 - "inventory.py"
Cohesion: 0.12
Nodes (13): _chave_fefo(), Lote, PedidoEmTransito, date, Estado de estoque de um par loja-item: `InventoryState`. Fonte única de verdade…, Avança a data corrente e recebe pedidos em trânsito já chegados. Não expira…, Remove os lotes vencidos na data corrente e devolve o total perdido. Usa `<`…, Registra um pedido em trânsito, com a validade que o lote terá ao chegar.… (+5 more)

### Community 42 - "_tiny_params"
Cohesion: 0.16
Nodes (16): _build_forecaster(), _build_policy(), `alpha` só é usado pelo braço `basestock` -- `erp_baseline` não deriva nada de…, Hash determinístico só dos campos de `Params` que afetam `select_subset` -- não…, _selection_params_hash(), `erp_baseline`/`forecast_naive` não entram no hash -- não afetam…, `params.yaml` real, com `canonical`/`subset_selection`/`simulation` trocados…, test_build_forecaster_desconhecido_levanta_value_error() (+8 more)

### Community 43 - "quantile_gbm.py"
Cohesion: 0.05
Nodes (90): FeatureCalendarParams, FeaturesParams, QuantileGbmParams, Parâmetros de `motor.features.calendar` (Sprint 14): início de mês, quinzena e…, Parâmetros de `motor.features` (Sprint 14). `active_features` é a lista exata…, Parâmetros de `motor.forecast.quantile_gbm` (Sprint 15): um LightGBM por…, build_features(), build_training_matrix() (+82 more)

### Community 44 - "Params"
Cohesion: 0.19
Nodes (14): model_validator, load_params(), Params, Path, Todas as premissas numéricas do projeto, carregadas de `config/params.yaml`., `compute_order_quantity` (motor.policy.target_level, regra do enunciado)…, Carrega `params.yaml` e valida contra `Params`., Testes do modelo Params e do arquivo config/params.yaml do repositório. (+6 more)

### Community 45 - "expected_polars_schema"
Cohesion: 0.18
Nodes (14): _default_required_columns(), expected_polars_schema(), BaseModel, Uma linha de saldo de estoque no grão loja x item x dia. Esta é a tabela que o…, Deriva o schema polars esperado (coluna -> dtype) a partir do modelo pydantic.…, Colunas que o próprio modelo já declara como não-nuláveis (sem `| None`)., Classe-base das quatro tabelas canônicas. Imutável (`frozen`), sem colunas além…, Uma linha de venda no grão loja x item x dia. `units_returned` é uma coluna… (+6 more)

### Community 48 - "run_arm"
Cohesion: 0.20
Nodes (14): ArmRunResult, _build_quantile_gbm_registry(), _events_to_dataframe(), DataFrame, LazyFrame, Treina o modelo GLOBAL do braço 3 UMA VEZ, fora do loop por item (ver docstring…, Saída de `run_arm`. `item_metrics`: uma linha por item, colunas de métricas…, Arredonda toda coluna `Float64` (exceto `exclude`) em `ndigits` casas.… (+6 more)

### Community 49 - "load_or_select_subset"
Cohesion: 0.40
Nodes (6): load_or_select_subset(), RuntimeError, Lê `cache_path` se existir e o hash bater; senão roda `select_subset` (que…, O cache de subconjunto em disco foi calculado com outros parâmetros de seleção…, StaleSubsetSelectionError, test_load_or_select_subset_levanta_stale_subset_selection_error_quando_hash_diverge()

### Community 50 - "basestock.py"
Cohesion: 0.33
Nodes (4): Política de nível-alvo, no grão de um par loja-item (Sprint 12).…, Política de nível-alvo (Sprint 11): `compute_order_quantity`. Lógica pura --…, Saída de `compute_order_quantity`. `target_level` e `position_used` são…, TargetLevelDecision

### Community 51 - "_assert_no_leakage"
Cohesion: 0.40
Nodes (5): _assert_no_leakage(), LeakageGuardError, ValueError, A fatia de densidade (D3) tem que terminar estritamente antes do loop do…, `subset_selection.density_window_end` alcança ou ultrapassa…

## Ambiguous Edges - Review These
- `Plano de sprints (0 a 5)` → `Referência a 'Sprint 17' (cabeçalho do arquivo)`  [AMBIGUOUS]
  config/params.yaml · relation: references

## Knowledge Gaps
- **10 isolated node(s):** `motor`, `Dataset Favorita`, `Parâmetros de guardrails (teto de cobertura, variação, orçamento)`, `Parâmetros de modelo (quantis, cadência de re-treino)`, `Parâmetros de simulação (warmup_days, seed, datas)` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 407 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Plano de sprints (0 a 5)` and `Referência a 'Sprint 17' (cabeçalho do arquivo)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `NaiveForecaster` connect `NaiveForecaster` to `run.py`, `_tiny_params`, `erp_calibration.py`, `StatisticalForecaster`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Why does `build_simulator_for_pair()` connect `build_simulator_for_pair` to `run.py`, `run_arm`, `InventoryState`, `erp_calibration.py`, `test_simulator.py`, `engine.py`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `InventoryState` connect `InventoryState` to `SpyForecaster`, `WindowQuantileForecast`, `inventory.py`, `test_simulator.py`, `test_financial.py`, `engine.py`, `build_simulator_for_pair`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Are the 27 inferred relationships involving `InventoryState` (e.g. with `_in_transit()` and `Simulator`) actually correct?**
  _`InventoryState` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Params` (e.g. with `_build_forecaster()` and `_build_manifest()`) actually correct?**
  _`Params` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `run_arm()` (e.g. with `Params` and `StoreLocale`) actually correct?**
  _`run_arm()` has 4 INFERRED edges - model-reasoned connections that need verification._