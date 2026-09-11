# Graph Report - mercado  (2026-09-10)

## Corpus Check
- 45 files · ~39,878 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 797 nodes · 1748 edges · 40 communities (27 shown, 6 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 130 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- validate_table
- contracts.py
- profiling.py
- Simulador (centro do sistema)
- select_subset
- test_loaders.py
- test_profiling.py
- test_smoke.py
- Janelas de profiling (12 vs 24 meses)
- motor
- LazyFrame
- run.py
- InventoryState
- NaiveForecaster
- erp_calibration.py
- DecisionContext
- test_simulator.py
- config.py
- build_analytic_scenario
- Simulator
- expected_polars_schema
- valid_suppliers
- SchemaValidationError
- inventory.py
- loaders.py
- load_suppliers
- test_selection.py
- Forecaster
- Params
- .em_maos
- _Bound
- tests/__init__.py
- _assert_no_leakage

## God Nodes (most connected - your core abstractions)
1. `InventoryState` - 40 edges
2. `validate_table()` - 37 edges
3. `Params` - 27 edges
4. `build_canonical_favorita()` - 26 edges
5. `run_arm()` - 25 edges
6. `NaiveForecaster` - 23 edges
7. `load_sales()` - 20 edges
8. `select_subset()` - 20 edges
9. `ParamsSection` - 19 edges
10. `_build_manifest()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `Referência a 'Sprint 17' (cabeçalho do arquivo)` --references--> `Plano de sprints (0 a 5)`  [AMBIGUOUS]
  config/params.yaml → CLAUDE.md
- `test_colisao_de_supplier_id_levanta_erro()` --uses--> `SupplierAssumptionsParams`  [INFERRED]
  tests/test_loaders.py → src/motor/config.py
- `test_d8_suppliers_valores_vem_de_params_nao_hardcoded()` --uses--> `SupplierAssumptionsParams`  [INFERRED]
  tests/test_loaders.py → src/motor/config.py
- `_tiny_params()` --uses--> `SupplierAssumptionsParams`  [INFERRED]
  tests/test_loaders.py → src/motor/config.py
- `_tiny_params()` --uses--> `CanonicalParams`  [INFERRED]
  tests/test_loaders.py → src/motor/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Métrica de decisão financeira: margem, capital e guardrails** — claude_metricas_financeiras, config_params_economics, config_params_guardrails_config [INFERRED 0.75]
- **Contratos internos: Forecaster, Policy, DecisionContext, Simulador** — claude_forecaster, claude_policy, claude_decisioncontext, claude_simulador [INFERRED 0.85]
- **Três braços experimentais comparados pelo simulador** — config_params_arm_erp_baseline, config_params_arm_estatistico_basestock, config_params_arm_quantile_gbm_basestock, claude_sprints [INFERRED 0.85]

## Communities (40 total, 6 thin omitted)

### Community 0 - "validate_table"
Cohesion: 0.12
Nodes (13): ValueError, Valida um DataFrame contra um contrato pydantic, de forma vetorizada. Levanta…, Uma linha de venda no grão loja x item x dia. `units_returned` é uma coluna…, Sale, validate_table(), Tolerância de dtype é em uma direção só: int->float ok, float->int não., Upcast seguro: coluna int satisfaz contrato float., TestExemplosValidos (+5 more)

### Community 1 - "contracts.py"
Cohesion: 0.17
Nodes (25): _column_presence_violations(), _constraint_violations(), _dtype_is_compatible(), _dtype_violations(), _enum_column_violations(), _extract_bounds(), _field_base_and_metadata(), _list_column_violations() (+17 more)

### Community 2 - "profiling.py"
Cohesion: 0.14
Nodes (24): profile_calendar(), profile_fractional_by_item(), profile_fractional_global(), profile_item_volume(), profile_negatives_by_item(), profile_negatives_global(), profile_pair_coverage(), profile_promo_availability() (+16 more)

### Community 3 - "Simulador (centro do sistema)"
Cohesion: 0.08
Nodes (37): Armadilhas conhecidas, Política basestock (nível-alvo), DecisionContext (dataclass), Política erp_baseline, Previsão naive (média móvel + quantis empíricos), Previsão quantile_gbm (LightGBM, perda pinball), Previsão estatística (sazonal simples + desvio), Protocol Forecaster (+29 more)

### Community 4 - "select_subset"
Cohesion: 0.19
Nodes (19): _cap_by_family(), _density_by_item(), _exclude_degenerate_families(), _exclude_promo_dominated(), _funnel_row(), _lifespan_complete(), _pairs_for_store(), DataFrame (+11 more)

### Community 5 - "test_loaders.py"
Cohesion: 0.06
Nodes (76): ArgumentParser, AnomalyPeriodParams, Um período de distorção conhecida na série (Sprint 3, D1: ex. terremoto). Marca…, load_sales(), date, Reindex do bruto (`train`) para a grade diária canônica de `sales`. LazyFrame…, _build_arg_parser(), convert_raw_to_parquet() (+68 more)

### Community 6 - "test_profiling.py"
Cohesion: 0.20
Nodes (15): count_candidates(), Quantos pares loja-item sobrevivem a cada corte de `density_window`. Uma linha…, _coverage_sintetica(), _items_sinteticos(), LazyFrame, Testes de motor.profiling -- todo frame é sintético, construído à mão. Nenhum…, Um único par, loja já aberta bem antes da janela (denominador da densidade da…, Loja que abre no meio da janela: o denominador de density_window usa o lifespan… (+7 more)

### Community 7 - "test_smoke.py"
Cohesion: 0.40
Nodes (3): Teste de fumaça: garante que o pacote instala e importa corretamente., Confirma que o pacote `motor` pode ser importado a partir do layout src/., test_import_motor()

### Community 17 - "LazyFrame"
Cohesion: 0.22
Nodes (9): _apply_anomalies(), _pair_lifespan_bounds(), LazyFrame, Por par (`store_nbr`, `item_nbr`) retido: data de entrada e de saída do reindex…, Grade diária `(store_nbr, item_nbr, date)`, de `entry_date` a `exit_date`, por…, Pares `(store_nbr, date)`, dentro da janela, em que ao menos uma linha existe…, Marca `is_anomaly`/`anomaly_reason` (D1) sem remover nenhuma linha. Apagar dado…, _reindex_spine() (+1 more)

### Community 18 - "run.py"
Cohesion: 0.05
Nodes (81): RuntimeError, ExperimentArmParams, Um braço de experimento: nome, forecaster e política usados., ArmRunResult, _build_forecaster(), _build_manifest(), _build_policy(), ErpBaselineCalibrationManifest (+73 more)

### Community 19 - "InventoryState"
Cohesion: 0.19
Nodes (24): InventoryState, Posição de estoque de um par loja-item, com pipeline e lotes com validade. Ver…, _dias(), date, Testes de `InventoryState` -- estado isolado, sem simulação, sem dado real.…, Bateria de operações com resultado calculado à mão. D0: recebe 10 (validade…, Um lote de validade longa que CHEGOU primeiro não deve furar a fila: o de…, test_avancar_para_com_data_anterior_ou_igual_a_corrente_levanta_value_error() (+16 more)

### Community 20 - "NaiveForecaster"
Cohesion: 0.10
Nodes (32): _empirical_quantile(), NaiveForecaster, DataFrame, date, Previsão ingênua (`NaiveForecaster`): média móvel de N semanas sobre a demanda…, Erros históricos da própria média móvel. Para cada dia `t` do histórico visível…, Quantil empírico por interpolação linear sobre uma lista JÁ ordenada…, Média móvel de `moving_average_weeks` semanas + quantis empíricos dos resíduos… (+24 more)

### Community 21 - "erp_calibration.py"
Cohesion: 0.11
Nodes (31): CalibrationItem, CalibrationResult, _choose(), GridResult, _precompute_forecasts(), _PrecomputedForecaster, DataFrame, date (+23 more)

### Community 22 - "DecisionContext"
Cohesion: 0.11
Nodes (23): DecisionContext, Protocolo `Policy` e `DecisionContext`, no grão de um único par loja-item. Ver…, Tudo que uma política vê para decidir quanto pedir, para um par loja-item.…, Unidades a pedir, antes das regras de guarda (sprint futura: ainda não existem)., ErpBaselinePolicy, Política do braço 1 (ERP baseline, Sprint 7): pedido = média das últimas…, Sem quantil, sem alfa, sem janela de risco derivada -- ver docstring do módulo., `target = mu_daily x moving_average_days x factor`; pedido = `target -… (+15 more)

### Community 23 - "test_simulator.py"
Cohesion: 0.07
Nodes (46): build_simulator_for_pair(), initial_stock_units(), DataFrame, date, Premissas de simulação compartilhadas entre TODOS os braços (Sprint 7, seção 1…, Estoque inicial arbitrado: cobertura de um ciclo de risco (lead_time +…, Monta o `Simulator` de um par loja-item com as premissas compartilhadas desta…, Calendário de revisão: verdadeiro a cada `period_days` dias, a partir de… (+38 more)

### Community 24 - "config.py"
Cohesion: 0.12
Nodes (22): DataParams, EconomicsParams, ErpBaselineParams, ExperimentsParams, ForecastNaiveParams, GuardrailsParams, ModelParams, ParamsSection (+14 more)

### Community 25 - "build_analytic_scenario"
Cohesion: 0.07
Nodes (47): build_item_economics(), compute_financial_metrics(), compute_portfolio_metrics(), ItemEconomics, ItemFinancialMetrics, MissingItemEconomicsError, _priced_events(), DataFrame (+39 more)

### Community 26 - "Simulator"
Cohesion: 0.14
Nodes (17): Policy, Protocol, Decide quanto pedir para um par loja-item., DailyEvent, _in_transit(), DataFrame, date, Loop diário do simulador, para um único par loja-item (CLAUDE.md, seção 6).… (+9 more)

### Community 27 - "expected_polars_schema"
Cohesion: 0.31
Nodes (9): _default_required_columns(), _dtype_for_primitive(), expected_polars_schema(), _polars_dtype_for_field(), BaseModel, PolarsDtype, Deriva o schema polars esperado (coluna -> dtype) a partir do modelo pydantic.…, Colunas que o próprio modelo já declara como não-nuláveis (sem `| None`). (+1 more)

### Community 28 - "valid_suppliers"
Cohesion: 0.14
Nodes (14): max_cyclic_order_gap(), Verifica integridade referencial entre as tabelas canônicas. Todo `item_id` em…, Maior intervalo, em dias, entre dois dias de pedido consecutivos de…, Verifica que `review_period_days` cobre o maior intervalo entre dias de pedido.…, validate_referential_integrity(), validate_supplier_order_cadence(), DataFrame, parametrize (+6 more)

### Community 30 - "inventory.py"
Cohesion: 0.12
Nodes (13): _chave_fefo(), Lote, PedidoEmTransito, date, Estado de estoque de um par loja-item: `InventoryState`. Fonte única de verdade…, Avança a data corrente e recebe pedidos em trânsito já chegados. Não expira…, Remove os lotes vencidos na data corrente e devolve o total perdido. Usa `<`…, Registra um pedido em trânsito, com a validade que o lote terá ao chegar.… (+5 more)

### Community 31 - "loaders.py"
Cohesion: 0.11
Nodes (29): Item, Uma linha de saldo de estoque no grão loja x item x dia. Esta é a tabela que o…, Uma linha de cadastro no grão item. `ean`, `pack_multiple`, `cost` e…, Uma linha de cadastro no grão fornecedor. `order_days` e `review_period_days`…, Unidade de venda do item: por unidade discreta ou por peso. Esta é a distinção…, Classe-base das quatro tabelas canônicas. Imutável (`frozen`), sem colunas além…, Stock, Supplier (+21 more)

### Community 32 - "load_suppliers"
Cohesion: 0.24
Nodes (10): Premissas de fornecedor usadas quando o cadastro não traz o dado.…, SupplierAssumptionsParams, _build_family_to_supplier_id(), load_suppliers(), Slug determinístico de `family` para `supplier_id` (D8). Maiúsculas; qualquer…, Mapeia cada `family` distinta a um `supplier_id`, com checagem de colisão (D8).…, Uma linha por `family` distinta em `items_raw`, valores de…, _slugify_supplier_id() (+2 more)

### Community 33 - "test_selection.py"
Cohesion: 0.13
Nodes (22): _cenario_duas_familias(), _daterange(), _item_row(), _item_with_pattern(), DataFrame, date, LazyFrame, Testes de motor.selection -- seleção do subconjunto de trabalho (Sprint 4).… (+14 more)

### Community 34 - "Forecaster"
Cohesion: 0.22
Nodes (8): Forecaster, DataFrame, date, Protocol, Protocolo `Forecaster`, no grão de um único par loja-item. Este protocolo é…, Previsão de demanda para um único par loja-item., Ajusta o modelo a `history`. `history` contém apenas linhas com `date < as_of`…, Devolve colunas `quantile`, `value`: demanda ACUMULADA nos próximos `horizon`…

### Community 35 - "Params"
Cohesion: 0.14
Nodes (23): CanonicalParams, load_params(), Params, Path, Parâmetros da normalização canônica do Favorita (Sprint 3, `motor.io.loaders`).…, Todas as premissas numéricas do projeto, carregadas de `config/params.yaml`., Carrega `params.yaml` e valida contra `Params`., Critério de seleção do subconjunto de trabalho (Sprint 4). Uma loja, 150-300… (+15 more)

### Community 43 - "_assert_no_leakage"
Cohesion: 0.40
Nodes (5): _assert_no_leakage(), LeakageGuardError, ValueError, A fatia de densidade (D3) tem que terminar estritamente antes do loop do…, `subset_selection.density_window_end` alcança ou ultrapassa…

## Ambiguous Edges - Review These
- `Plano de sprints (0 a 5)` → `Referência a 'Sprint 17' (cabeçalho do arquivo)`  [AMBIGUOUS]
  config/params.yaml · relation: references

## Knowledge Gaps
- **10 isolated node(s):** `motor`, `Dataset Favorita`, `Parâmetros de guardrails (teto de cobertura, variação, orçamento)`, `Parâmetros de modelo (quantis, cadência de re-treino)`, `Parâmetros de simulação (warmup_days, seed, datas)` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 285 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Plano de sprints (0 a 5)` and `Referência a 'Sprint 17' (cabeçalho do arquivo)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `build_simulator_for_pair()` connect `test_simulator.py` to `Forecaster`, `run.py`, `InventoryState`, `erp_calibration.py`, `Simulator`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Why does `InventoryState` connect `InventoryState` to `.em_maos`, `test_simulator.py`, `build_analytic_scenario`, `Simulator`, `inventory.py`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Why does `NaiveForecaster` connect `NaiveForecaster` to `run.py`, `erp_calibration.py`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `InventoryState` (e.g. with `_in_transit()` and `Simulator`) actually correct?**
  _`InventoryState` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `Params` (e.g. with `_build_forecaster()` and `_build_manifest()`) actually correct?**
  _`Params` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `build_canonical_favorita()` (e.g. with `Params` and `Item`) actually correct?**
  _`build_canonical_favorita()` has 4 INFERRED edges - model-reasoned connections that need verification._