Motor de decisão de compra — contexto do projeto

Leia este arquivo inteiro antes de escrever código. Ele define arquitetura, contratos e ordem de construção. Quando houver conflito entre um pedido pontual e as regras aqui, aponte o conflito antes de implementar.

1. O que estamos construindo

Um motor que gera a lista de compra semanal de um supermercado: para cada item, quanto pedir, respeitando as regras do fornecedor.

O produto não é um modelo de previsão. Previsão é um componente interno e substituível. O produto é a decisão de quantidade, e a prova de valor é financeira: a lista gerada teria produzido mais margem, com menos capital parado, que a regra ingênua que um ERP usa hoje.

Consequência arquitetural direta: o simulador é o centro do sistema, não o modelo. Construímos o simulador primeiro, com uma previsão ingênua no lugar, e trocamos o modelo depois sem tocar em nada mais.

2. Stack e convenções
Python 3.11+
polars para manipulação de dados (o volume não cabe confortavelmente em pandas). pandas só na fronteira com bibliotecas que exigem.
lightgbm para previsão quantílica
pydantic para configs e contratos de dados
pytest para testes
ruff + mypy (modo não estrito)

Regras:

Lógica de negócio nunca vive em notebook. Notebooks só para exploração e para gerar os gráficos do relatório final.
Toda premissa numérica (lead time, margem, múltiplo de fardo, custo de capital, α por categoria) vem de config/params.yaml. Nenhum número mágico no código.
Funções puras sempre que possível. O simulador é a única parte com estado mutável, e esse estado é explícito em uma classe.
Type hints obrigatórios em tudo que cruza fronteira de módulo.
Determinismo: seed fixa em qualquer coisa estocástica. Rodar duas vezes produz bytes idênticos.
Docstrings em português, identificadores em inglês.
3. Estrutura do repositório
config/
  params.yaml            # todas as premissas
src/motor/
  io/
    contracts.py         # schemas pydantic das tabelas canônicas
    loaders.py           # dataset bruto -> tabelas canônicas
  features/
    calendar.py          # feriado, dia da semana, início de mês, dia de pagamento
    build.py             # lags, médias móveis, preço, promoção
  forecast/
    base.py              # Protocol Forecaster
    naive.py             # média móvel + quantis empíricos dos resíduos
    statistical.py       # sazonal simples + desvio
    quantile_gbm.py      # LightGBM com perda pinball
  policy/
    base.py              # Protocol Policy, DecisionContext
    erp_baseline.py      # média móvel 4 semanas + mínimo fixo
    basestock.py         # nível-alvo por quantil
    guardrails.py        # regras de guarda, aplicadas após a política
    supplier.py          # fardo, pedido mínimo, calendário de entrega
  sim/
    state.py             # InventoryState (on hand, pipeline, lotes)
    engine.py            # loop diário
  metrics/
    financial.py         # conversão de eventos para R$
  experiments/
    run.py               # roda um braço completo e salva resultados
tests/
notebooks/
4. Tabelas canônicas

Todo dataset de entrada é normalizado para estas quatro tabelas antes de qualquer coisa. Nenhum módulo abaixo de io/ conhece o formato original.

sales — store_id, item_id, date, units, price, on_promo items — item_id, category, unit (each | kg), cost, supplier_id, is_anchor suppliers — supplier_id, lead_time_days, order_days (dias da semana), min_order_value, pack_multiple stock — store_id, item_id, date, on_hand — opcional, ausente em dado público

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
