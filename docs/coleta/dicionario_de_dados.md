# Dicionário de dados do piloto

Fonte: [`src/motor/io/contracts.py`](../../src/motor/io/contracts.py), contratos
`Sale`, `Item`, `Supplier`, `Stock` e `Entry`. Todos os exemplos em
[`modelos/`](modelos/) são **FICTÍCIOS**; não são premissas comerciais.

“Obrigatório” abaixo significa valor não nulo. Campos “nuláveis” aceitam
`null` no modelo de linha, mas **todas as colunas, inclusive as nuláveis,
precisam existir no DataFrame canônico**. `validate_table` acusa coluna
ausente, extra, tipo incorreto, nulo indevido ou chave duplicada com
`SchemaValidationError`; não cria colunas nem preenche valores. A ingestão
deve materializar colunas desconhecidas como nulas e com o tipo do contrato.
Datas são `date`; listas são listas tipadas, não texto, no canônico.

## Vendas — `sales`, contrato `Sale`

Uma linha por loja, item e dia; chave `(store_id, item_id, date)`.

| Campo | Tipo e restrição | Obrigatório | Significado e ausência |
|---|---|---|---|
| `store_id` | `str` | Sim | Identificador da loja; ausência impede validação |
| `item_id` | `str` | Sim | Identificador existente em items; ausência impede validação |
| `date` | `date` | Sim | Data da venda; ausência impede validação |
| `units_sold` | `float >= 0` | Sim | Venda em unidades ou kg; não registrar devolução como venda negativa |
| `units_returned` | `float >= 0` ou `null` | Não | Devolução separada; nulo = desconhecido, não zero. O loader Favorita exige não nulo nesta coluna |
| `on_promo` | `bool` ou `null` | Não | Promoção observada; nulo = não se sabe, não `false` |
| `price` | `float >= 0` ou `null` | Não | Preço praticado; ausência no Favorita é premissa declarada, não preço inferido aqui |
| `is_operating_day` | `bool` | Sim | Atributo loja-dia, igual para todos os itens da loja; não confundir loja fechada com demanda zero |
| `is_anomaly` | `bool` | Sim | Indica distorção conhecida; obrigatório mesmo quando false |
| `anomaly_reason` | `str` ou `null` | Não | Motivo quando conhecido; nulo não inventa motivo |

Não somar preço unitário ao agregar vendas. Dias sem registro precisam ser
entendidos na adaptação; os CSVs ainda não têm adaptador de ERP neste projeto.

## Cadastro — `items`, contrato `Item`

Uma linha por item; chave `(item_id)`. `pack_multiple` pertence ao SKU.

| Campo | Tipo e restrição | Obrigatório | Significado e ausência |
|---|---|---|---|
| `item_id` | `str` | Sim | Código do item, preservado como texto |
| `ean` | `str` ou `null` | Não | Código de barras; preservar zeros à esquerda |
| `description` | `str` ou `null` | Não | Descrição; a lista não inventa nome quando ausente |
| `category` | `str` | Sim | Categoria; precisa de correspondência com a configuração antes do uso |
| `item_class` | `str` ou `null` | Não | Classe adicional do cadastro, quando disponível |
| `supplier_id` | `str` | Sim | Identificador existente em suppliers |
| `unit_of_sale` | `UnitOfSale`: `unidade` ou `kg` | Sim | Enumeração fechada; “each” não é valor válido |
| `pack_multiple` | `float > 0` ou `null` | Não | Fardo do item; nulo no Favorita. A lista atual usa premissas de fardo por categoria, não automaticamente o fardo real |
| `is_perishable` | `bool` | Sim | Perecível; ausência deve ser resolvida no cadastro, não presumida false |
| `is_anchor` | `bool` ou `null` | Não | Item âncora; sem proxy inventado. A guarda de âncora não está implementada |
| `cost` | `float >= 0` ou `null` | Não no contrato; sim no loader atual | Custo; loader Favorita promove a não nulo via `required_non_null`; não usar ausência como custo zero |
| `price_ref` | `float >= 0` ou `null` | Não no contrato; sim no loader atual | Preço de referência; mesma promoção a não nulo; é usado nas métricas da simulação |
| `economics_origin` | `str` | Sim | Origem do custo/preço, observada ou premissa declarada; não mascarar arbitragem como medição |

## Fornecedores — `suppliers`, contrato `Supplier`

Uma linha por fornecedor; chave `(supplier_id)`. Todos os campos obrigatórios.

| Campo | Tipo e restrição | Significado e ausência |
|---|---|---|
| `supplier_id` | `str` | Código do fornecedor; ausência impede validação |
| `lead_time_days` | `int > 0` | Prazo entre pedido e recebimento; ausência impede validação |
| `order_days` | `list[int]`, ao menos um dia entre 1 e 7 | Dias em que aceita pedido: 1 = segunda, 7 = domingo |
| `review_period_days` | `int > 0` | Cadência de revisão da compra; independente dos dias aceitos |
| `min_order_value` | `float >= 0` | Mínimo em R$; 0 significa sem restrição, não desconhecido |
| `min_order_units` | `float >= 0` | Mínimo em unidades; 0 significa sem restrição, não desconhecido |

`validate_supplier_order_cadence` confere consistência dos dias e da cadência.
As duas restrições de mínimo, quando positivas, precisam ser atingidas.
A lista atual usa mínimo em R$ por categoria de
`purchase_list_supplier_assumptions`, não o mínimo real do cadastro; essa
integração e os fardos reais exigem revisão antes do piloto. Seus overrides
de prazos ainda são 7/14: `null` passa a usar os prazos de cada fornecedor.
Não transformar um dado desconhecido em mínimo zero.

## Estoque — `stock`, contrato `Stock`

Uma linha por loja, item e dia; chave `(store_id, item_id, date)`.

| Campo | Tipo e restrição | Obrigatório | Significado e ausência |
|---|---|---|---|
| `store_id` | `str` | Sim | Loja |
| `item_id` | `str` | Sim | Item existente no cadastro |
| `date` | `date` | Sim | Data do saldo |
| `on_hand` | `float >= 0` | Sim | Estoque disponível; saldo negativo precisa de tratamento explícito na ingestão |
| `in_transit` | `float >= 0` ou `null` | Não | Quantidade em trânsito conhecida; nulo não comprova zero |

A fonte stock é opcional. Sem ela, o experimento declara a premissa de
vendas observadas como demanda; o simulador mantém seu próprio estoque e
pipeline. `load_canonical_tables` exige **quatro arquivos parquet**, portanto
a ingestão deve fornecer `stock.parquet` vazio e tipado se não houver saldos;
arquivo ausente causa erro de I/O. O pipeline simulado não é substituído
automaticamente pelo campo `in_transit` do cadastro. Estoque fica fora das
features atuais de previsão.

## Recebimentos — `entries`, contrato `Entry`

Fonte opcional, uma linha por recebimento. Sem chave primária: dois
recebimentos do mesmo item no mesmo dia são legítimos.

| Campo | Tipo e restrição | Obrigatório | Significado e ausência |
|---|---|---|---|
| `store_id` | `str` | Sim | Loja que recebeu |
| `item_id` | `str` | Sim | Item recebido |
| `received_date` | `date` | Sim | Data do recebimento |
| `quantity` | `float > 0` | Sim | Quantidade recebida; estorno e devolução ao fornecedor não são entrada |
| `order_date` | `date` ou `null` | Não | Data do pedido, se registrada |
| `supplier_id` | `str` ou `null` | Não | Fornecedor do recebimento, se registrado |

`flag_probable_stockout` pode receber entries para verificar entrada recente.
Com `entries=None`, ignora essa condição e registra
`sem_tabela_entries_condicao_de_entrada_ignorada`. Uma tabela vazia tem
semântica diferente: foi fornecida, mas não tem recebimentos.
O carregador das quatro tabelas e os runners atuais não carregam entries
automaticamente. Coletar a tabela não implica integração já pronta.
