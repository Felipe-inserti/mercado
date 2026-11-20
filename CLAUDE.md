Motor de decisão de compra — contexto do projeto

Leia este arquivo inteiro antes de escrever código. Ele define arquitetura, contratos e ordem de construção. Quando houver conflito entre um pedido pontual e as regras aqui, aponte o conflito antes de implementar.

1. O que estamos construindo

Um motor que gera a lista de compra semanal de um supermercado: para cada item, quanto pedir, respeitando as regras do fornecedor.

O produto não é um modelo de previsão. Previsão é um componente interno e substituível. O produto é a decisão de quantidade, e a prova de valor é financeira: a lista gerada teria produzido mais margem, com menos capital parado, que a regra ingênua que um ERP usa hoje.

Consequência arquitetural direta: o simulador é o centro do sistema, não o modelo. Construímos o simulador primeiro, com uma previsão ingênua no lugar, e trocamos o modelo depois sem tocar em nada mais.

2. Stack e convenções
Python 3.12
polars para manipulação de dados (o volume não cabe confortavelmente em pandas). pandas só na fronteira com bibliotecas que exigem.
lightgbm para previsão quantílica
pydantic para configs e contratos de dados
pytest para testes
ruff + mypy (modo strict)

Regras:

Lógica de negócio nunca vive em notebook. Notebooks só para exploração e para gerar os gráficos do relatório final.
Toda premissa numérica (lead time, margem, múltiplo de fardo, custo de capital, α por categoria) vem de config/params.yaml. Nenhum número mágico no código.
Funções puras sempre que possível. O simulador é a única parte com estado mutável, e esse estado é explícito em uma classe.
Type hints obrigatórios em tudo que cruza fronteira de módulo.
Determinismo: seed fixa em qualquer coisa estocástica. Rodar duas vezes produz bytes idênticos.
Docstrings em português, identificadores em inglês.
3. Estrutura do repositório
```text
config/params.yaml        # premissas numéricas
src/motor/
  config.py              # configuração validada
  assumptions.py         # origem e registro das premissas
  inventory.py           # estoque, pipeline e lotes
  selection.py           # seleção do subconjunto
  selection_cache.py     # cache e hash dos parâmetros de seleção
  profiling.py           # perfil do dado canônico
  io/
    contracts.py         # Sale, Item, Supplier, Stock e Entry
    raw.py               # conversão e leitura do bruto
    loaders.py           # bruto -> tabelas canônicas
    canonical.py         # CanonicalTables e leitura dos quatro parquet
    supplier_overrides.py # prazos explícitos ou preservação do cadastro
    quality_report.py    # qualidade do dado de entrada
  features/
    calendar.py          # geografia e calendário de feriados
    build.py             # lags, médias móveis, preço e promoção
    censoring.py         # ruptura provável, só no histórico de previsão
  forecast/
    base.py              # Protocol Forecaster
    naive.py             # média móvel e resíduos
    naive_seasonal.py    # mesma semana anterior e resíduos
    statistical.py       # sazonalidade e nível recente
    quantile_gbm.py      # LightGBM com perda pinball
  policy/
    base.py              # Protocol Policy e DecisionContext
    erp_baseline.py      # regra do ERP
    erp_calibration.py   # calibração do baseline
    basestock.py         # nível-alvo por quantil
    target_level.py      # cálculo de nível-alvo
    guardrails.py        # quatro guardas implementadas
    supplier.py          # fardo, mínimo e calendário
  simulator/
    engine.py            # loop diário
    pair.py              # construção do simulador por par loja-item
  metrics/
    financial.py         # conversão dos eventos para R$
    forecast_quality.py  # qualidade da previsão
  reporting/
    purchase_list.py     # decisão e Excel por fornecedor
  experiments/
    run.py               # braços e manifestos
    shared.py            # reexportações de compatibilidade
    sensitivity.py       # cenários de sensibilidade
    iso_service.py       # comparação iso-serviço
    stale_baseline.py    # baseline desatualizado
    monthly_report.py    # relatório mensal dos experimentos
tests/                   # fixtures sintéticas, arquitetura e golden
notebooks/               # exploração e gráficos
docs/                    # sprints, decisões e coleta do piloto
.github/workflows/ci.yml  # checks em push e pull_request
```

4. Tabelas canônicas

Todo dataset de entrada é normalizado para estas quatro tabelas antes de qualquer coisa. Nenhum módulo abaixo de io/ conhece o formato original.

Os campos e tipos atuais estão em `io/contracts.py` e em
`docs/coleta/dicionario_de_dados.md`. O grão é loja-item-dia em `sales`
(`units_sold`, devoluções separadas), item em `items` (`unit_of_sale` =
`unidade` ou `kg`, `pack_multiple` por SKU), fornecedor em `suppliers`
(prazos, dias de pedido e mínimos) e loja-item-dia em `stock` (saldo e
trânsito). `stock` é opcional como fonte de negócio; o carregador canônico
atual exige um parquet vazio tipado quando não houver dados. O contrato
opcional `Entry` representa recebimentos; não é carregado automaticamente
por `load_canonical_tables`.

Se stock não existir, o sistema opera assumindo que as vendas observadas são a demanda. Isso deve ser registrado explicitamente na saída do experimento como uma premissa ativa, não escondido.

Emenda (Sprint 14, 2026-09-11): as quatro tabelas acima continuam a ÚNICA porta de entrada para lógica de negócio (previsão, política, simulador, métricas). `motor.features.calendar`, porém, abre uma SEGUNDA porta de I/O, deliberada e restrita: lê `holidays_events` e `stores` direto do parquet bruto já convertido (`motor.io.raw.scan_raw`, Sprint 2), fora do canônico. Motivo: cidade/estado da loja e calendário de feriado não têm onde morar nas quatro tabelas de negócio acima — são metadado de geografia/calendário público, não fato de venda, item, fornecedor ou estoque, e forçá-los para dentro de `items`/`suppliers` mudaria o grão dessas tabelas sem necessidade. A regra de vazamento (seção 8) não se aplica a esta porta — feriado de qualquer data é conhecido de antemão, ao contrário de venda —, mas a regra de "nenhum módulo abaixo de `io/` conhece o formato original" continua valendo à risca: só `motor.features.calendar` conhece `RAW_SCHEMAS`/`scan_raw` para esses dois arquivos; nenhum outro módulo lê `holidays_events`/`stores` diretamente.

Emenda (Sprint 15, 2026-09-11): `stock` fica FORA de `motor.features` — decisão explícita, não esquecimento. O dataset público não tem saldo de estoque; uma feature derivada dele (ex.: flag de ruptura) só existiria dentro da simulação (que conhece `InventoryState`), nunca num cliente real sem esse dado — o modelo aprenderia a depender de algo que não generaliza. Não volta sem uma conversa nova.

5. Contratos internos

Estes três protocolos são a espinha dorsal. Não os altere sem avisar.

python
class Forecaster(Protocol):
    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        """history contém apenas linhas com date < as_of. Garantido pelo simulador."""

    def predict_quantiles(
        self, keys: pl.DataFrame, as_of: date, horizon: int, quantiles: list[float]
    ) -> pl.DataFrame:
        """Retorna store_id, item_id, quantile, value — demanda TOTAL acumulada no horizonte."""
python
@dataclass(frozen=True)
class DecisionContext:
    as_of: date
    supplier_id: str
    on_hand: dict[str, float]           # item_id -> unidades
    in_transit: dict[str, float]        # item_id -> unidades já pedidas e não chegadas
    forecast: pl.DataFrame              # saída de predict_quantiles
    item_params: pl.DataFrame
    supplier_params: SupplierParams
    weekly_budget: float | None

class Policy(Protocol):
    def order(self, ctx: DecisionContext) -> dict[str, float]:
        """item_id -> unidades a pedir, antes das regras de guarda."""

Regras sobre os contratos:

A previsão é da demanda acumulada na janela de risco (lead_time + review_period), não da demanda diária. Isso evita somar quantis, que é matematicamente errado.
in_transit é obrigatório em toda decisão. Omitir pipeline faz a política pedir de novo o que já está a caminho — é o bug clássico deste tipo de sistema e ele infla o resultado silenciosamente.

Emenda (Sprint 6, 2026-09-10): os `Forecaster`/`Policy`/`DecisionContext` acima são o contrato do CONSOLIDADOR por fornecedor — `keys`/`item_id` múltiplos, `item_params`, `supplier_params`, `weekly_budget`. Esse grão só existe a partir da sprint que introduz `supplier.py`/consolidação por fornecedor (posterior a esta). O loop diário do simulador (`motor.simulator.engine.Simulator`, `motor.forecast.base`, `motor.policy.base`) opera no grão de UM par loja-item, com protocolos reduzidos:

python
class Forecaster(Protocol):
    def fit(self, history: pl.DataFrame, as_of: date) -> None: ...
    def predict_quantiles(self, as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        """Colunas quantile, value — demanda ACUMULADA no horizonte, para este par. Nunca diária: somar quantis diários é matematicamente errado."""

@dataclass(frozen=True)
class DecisionContext:
    as_of: date
    on_hand: float
    in_transit: float       # sempre posição total menos em mãos — nunca calculado ad-hoc por quem monta o contexto
    forecast: pl.DataFrame  # saída de predict_quantiles

class Policy(Protocol):
    def order(self, ctx: DecisionContext) -> float:
        """Unidades a pedir para este par, antes das regras de guarda."""

O consolidador por fornecedor (sprint futura) ENVOLVE este protocolo por fora — um `Forecaster`/`Policy` que respondem por vários pares expõem, por par, uma instância deste protocolo reduzido — sem alterar o loop diário. As duas regras da lista acima (demanda acumulada, in_transit obrigatório) valem integralmente nos dois grãos.
6. O simulador

Loop diário, na ordem exata abaixo. A ordem importa e não deve ser alterada.

Recebimento — chega o que foi pedido em t - lead_time. Entra como lote novo com data de validade quando aplicável.
Demanda do dia — valor verdadeiro do dia, vindo dos dados.
Atendimento — sales = min(demand, on_hand). O que não foi atendido é venda perdida, não backorder. No varejo alimentar o cliente não espera.
Envelhecimento — consumo FIFO. Lote que passou da validade vira perda e sai do estoque.
Decisão — se t é dia de pedido do fornecedor, monta o DecisionContext com dados estritamente anteriores a t, chama a política, aplica as regras de guarda, agenda a chegada.
Registro — grava o estado e os eventos do dia.

Detalhes obrigatórios:

Período de aquecimento. Os primeiros warmup_days (config) são simulados mas descartados das métricas. Sem isso o estoque inicial arbitrário contamina o resultado.
Estoque inicial igual ao nível-alvo da política baseline, idêntico em todos os braços. Braços com estoque inicial diferente não são comparáveis.
Sem lookahead por construção. O simulador passa para a previsão uma fatia já filtrada (date < as_of). Não confie em o modelo se comportar bem — filtre antes de entregar.
7. Métricas

Toda métrica sai em R$, por item e agregada.

margem_realizada = sales × (price − cost)
ruptura_rs = (demand − sales) × (price − cost) — margem que existia e não foi realizada
perda_rs = expired_units × cost
capital_medio = mean(on_hand × cost) ao longo do período
nivel_servico = sum(sales) / sum(demand) (fill rate por unidade, não por ciclo)
giro = sum(sales × cost) / capital_medio, anualizado

A métrica de decisão final é margem realizada menos perda, por real médio de capital empregado. É ela que ordena os braços.

8. Armadilhas conhecidas

Cada uma destas já foi causa de resultado falso em projetos deste tipo. Verifique explicitamente.

Venda tratada como demanda dentro do simulador. Quando há dado de estoque, dias com saldo zero têm demanda censurada e precisam ser estimados. Sem dado de estoque, declare a premissa em vez de fingir que não existe.
Vazamento por feature global. Média móvel, encoding de categoria e estatística de item calculados sobre o histórico inteiro antes do corte temporal vazam futuro. Toda feature é calculada dentro da janela visível.
Validação cruzada aleatória. Nunca. Só origem móvel.
Backorder em vez de venda perdida. Superestima o desempenho de qualquer política.
Pipeline ignorado. Ver seção 5.
Arredondamento para baixo no fardo. Sempre para cima. Arredondar para baixo gera ruptura sistemática.
Re-treino diário. Inviável computacionalmente e desnecessário. Re-treino semanal, predição a cada decisão.
Baseline estrangulado. O braço ERP tem que ser implementado com honestidade. Se ganharmos dele por implementá-lo mal, não ganhamos nada.
9. Sprints

Cada sprint termina com testes passando e um resultado observável. Não avance com sprint anterior incompleta.

Sprint 0 — Fundação de dados

Carregar o dataset escolhido e normalizar para as quatro tabelas canônicas. Validação de schema com pydantic. Perfil de dados: cobertura temporal, proporção de zeros por item, itens com histórico curto, buracos de calendário.

Selecionar o subconjunto de trabalho: uma loja, 150 a 300 SKUs de demanda regular. Critério de seleção documentado e reprodutível, não escolhido a mão.

Pronto quando: loaders.py produz as tabelas canônicas a partir do bruto, testes de schema passam, e existe um relatório de perfil do subconjunto.

Sprint 1 — Simulador e baseline

InventoryState, o loop diário, e a política erp_baseline (média móvel de 4 semanas × fator, mais mínimo fixo). Previsão ingênua como placeholder.

Teste de aceitação obrigatório: com demanda constante d, lead time L, revisão R e uma política que enche até d × (L + R), o simulador atinge estado estacionário com ruptura zero e estoque médio analiticamente previsível. Se esse teste não fecha, o loop está errado e nada construído em cima dele vale.

Pronto quando: o baseline roda no subconjunto real e produz uma série diária de estado e eventos.

Sprint 2 — Métricas e runner

metrics/financial.py e experiments/run.py. Um braço = uma config. Saída em parquet mais um resumo em JSON, com as premissas ativas embutidas no arquivo de resultado.

Pronto quando: dá para rodar python -m motor.experiments.run --arm erp_baseline e receber as métricas em R$ do período completo.

Sprint 3 — Política de nível-alvo

basestock.py com quantil por categoria, e supplier.py com fardo, pedido mínimo e calendário de entrega. Preenchimento até o pedido mínimo pelos itens de menor cobertura relativa.

guardrails.py: teto de cobertura, limite de variação sobre a compra histórica, restrição de caixa por margem sobre capital, tratamento separado de item novo. Cada regra é uma função isolada e testável, e registra quando dispara.

Pronto quando: o braço 2 (previsão estatística + nível-alvo) roda e é comparável ao baseline nas mesmas métricas.

Emenda (Sprint 17, 2026-09-12): `guardrails.py` (teto de cobertura, limite de variação sobre a compra histórica, restrição de caixa por margem sobre capital, tratamento separado de item novo — quatro regras nesta descrição original; `SupplierOrderPolicyParams`, config.py, comenta "seis regras de guarda" da Sprint 13 sem enumerá-las, então o número exato ficou ambíguo em algum ponto entre sprints) **nunca foi implementado** — não é que as regras existem e não dispararam no período, é que `Params.guardrails`/`GuardrailsParams` (config.py) não é lido por nenhuma função fora da própria declaração (confirmado por busca no código, pelo próprio `graphify-out/GRAPH_REPORT.md`, que já lista esse nó como isolado, e pela docstring de `motor.policy.base.Policy.order`, que já dizia "antes das regras de guarda (sprint futura: ainda não existem)" — a informação sempre esteve no código, só não tinha sido lida em conjunto). `supplier.py` (fardo, pedido mínimo, calendário de entrega) FOI implementado e testado (`motor.policy.supplier.apply_supplier_constraints`, Sprint 10) mas também nunca tinha sido chamado por nenhum código de produção até a Etapa 3.14 (Sprint 17), quando o gerador da lista de compra se tornou o primeiro caller real — o loop diário do simulador opera por par loja-item, sem consolidação por fornecedor, por desenho (seção 5 acima), então não é lá que essas restrições deveriam ter sido chamadas. Sprint 3 nunca deveria ter sido tratada como concluída nesta frente: sua própria condição de "pronto" (linha acima) não testa guardrails, e a frase "cada regra é uma função isolada e testável, e registra quando dispara" descrevia a intenção, não um fato verificado. Consequência para o produto, registrada aqui porque é real: sem as 4 regras de `guardrails.py`, nada impede o motor de sugerir uma quantidade absurda se a previsão quebrar — a lista de compra gerada pela Etapa 3.14 é utilizável como demonstração da política (braço 2 + restrições de fornecedor), não como produto pronto para um cliente real. Sprint 13 (as 4 regras, com as decisões de negócio que cada uma exige) é o próximo bloco de trabalho declarado, não implementado nesta emenda.

Superada na Etapa 3.16: as quatro regras foram implementadas em policy/guardrails.py e são testadas em tests/test_guardrails.py


Sprint 4 — Features e previsão quantílica

features/ com lags, médias móveis, dia da semana, feriado, início de mês, dia de pagamento, preço relativo e flag de promoção. quantile_gbm.py com LightGBM em perda pinball, um modelo por quantil, treinado sobre o painel de itens (modelo global, não um por SKU).

Re-treino semanal dentro da origem móvel. Cache dos modelos por data de treino para não retreinar em reruns.

Pronto quando: o braço 3 roda ponta a ponta e as três curvas de R$ acumulado são comparáveis num único gráfico.

Sprint 5 — Sensibilidade e artefato de venda

Varredura em lead time e na razão custo de faltar / custo de sobrar. Tabela de resultado por cenário.

Gerador da lista de compra: um arquivo por fornecedor, com lista principal e lista de exceções, no formato que um comprador usaria. Esse arquivo é a demo.

Pronto quando: existe um gráfico de R$ acumulado dos três braços, uma tabela de sensibilidade, e um exemplo real de lista de compra gerada.

10. Como quero que você trabalhe
Antes de implementar uma sprint, proponha o desenho dos módulos e espere confirmação. Depois implemente.
Escreva o teste antes da implementação quando o comportamento correto for verificável analiticamente (o caso do simulador, principalmente).
Prefira código explícito e legível a código esperto. Este projeto vai ser lido por um cliente cético e por um recrutador.
Se encontrar uma decisão de modelagem que muda o resultado financeiro, pare e explique o trade-off em vez de escolher sozinho.
Não otimize desempenho antes de o resultado estar correto. Depois que estiver, vetorize o loop diário se ele for gargalo.


## Git

Nunca execute `git add`, `git commit`, `git push` ou qualquer comando que
altere o histórico. Os commits são feitos manualmente pelo desenvolvedor.
Ao terminar uma etapa, liste os arquivos alterados e sugira uma mensagem
de commit em texto, sem executá-la.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

Emenda (Sprint 25, 2026-11-20): nenhum módulo fora de
`src/motor/experiments/` importa `motor.experiments`; a AST e a ausência de
LightGBM ao importar produto são verificadas em `tests/test_architecture.py`.
`purchase_list` em `config/params.yaml` declara alpha, overrides de lead time
e revisão e período do orçamento. Override `null` preserva o prazo do
próprio fornecedor no cadastro; 7/14 são o legado experimental, não os
prazos já medidos de um cliente. O relatório mensal agora fica em
`motor.experiments.monthly_report`, pois relata experimentos. Excel da lista
fixa a criação em `as_of`; o mensal, no fim do período simulado, garantindo
metadados e bytes determinísticos. O piso de cobertura é 85, um ponto abaixo
da medição combinada da Sprint 25, sem outras mudanças de pytest/coverage.
`tests/golden/purchase_list_synthetic.json` caracteriza os sete caminhos da
lista em quatro cenários sintéticos; nunca regenerar `tests/golden/` sem
decisão humana registrada. Decisões de negócio em
`docs/decisoes_em_aberto.md`; coleta em `docs/coleta/`.
