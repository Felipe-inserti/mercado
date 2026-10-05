# Motor de decisão de compra para supermercados pequenos e médios

Documento de definição — versão 2

> **Nota da versão 2.** A versão 1 foi escrita antes de qualquer medição. O MVP (seção 6) rodou, e a medição derrubou boa parte da tese original: a vantagem não está concentrada na cauda de itens irregulares (Spearman 0,275 — distribuída pelo portfólio, levemente maior nos itens de venda regular), e o ganho do modelo de ML sobre o estatístico é pequeno demais para justificar a complexidade extra numa v1. O que sobrou é menor e mais sólido: a correção de calibração do próprio ERP do cliente vale a maior parte do dinheiro, e o motor entrega um refinamento real por cima disso. As seções 1, 2, 4, 6 e 9 foram revisadas para refletir o que foi de fato medido; as seções 3, 5, 7 e 8 permanecem como na v1. Nenhum número novo abaixo foi estimado — todos vêm de medição do MVP; onde a medição não existe, o texto diz isso explicitamente.

---

## 1. O problema

Supermercado pequeno e médio não ganha dinheiro com margem, ganha com **giro de capital**. A margem de mercearia fica entre 15% e 22%, e em itens âncora (arroz, leite, óleo, refrigerante) cai para menos de 8%. O que decide o resultado do mês é quantas vezes o dinheiro girou, não quanto foi marcado na etiqueta.

O dono tem caixa limitado e milhares de itens concorrendo por ele. Cada real parado em um item é um real que faltou em outro. A compra, portanto, é um problema de alocação de capital escasso — mas hoje é feita por memória, por olhada na gôndola e por pressão de representante.

Três consequências, todas em dinheiro:

- **Ruptura.** O item acaba antes da próxima entrega. A margem existia e não foi realizada. Não aparece em nenhum relatório do ERP, porque o ERP só registra o que foi vendido.
- **Excesso.** Capital preso em item de giro lento, comprado por desconto de fornecedor ou por medo de faltar. Em perecível, vira perda direta.
- **Cauda ignorada.** O comprador acompanha bem os 200 itens de maior giro. Os outros 2.000 a 4.000 não são analisados por ninguém — não porque seja ali que a ineficiência mais pesa (o MVP mediu o contrário, ver seção 9), mas porque não sobra atenção humana para revisar milhares de itens toda semana. É argumento de cobertura operacional, não de onde o ganho financeiro está concentrado.

O ERP não resolve isso. Ele é sistema de registro: guarda venda, entrada, custo, saldo. Quando tem sugestão de compra, é regra fixa (média das últimas semanas × fator, ou mínimo/máximo cadastrado à mão e nunca revisado). Nenhuma delas considera incerteza, lead time real, custo de faltar versus custo de sobrar, ou restrição de caixa.

---

## 2. O produto

**Uma lista de compra semanal, separada por fornecedor, com quantidade definida, pronta para enviar.**

Não é dashboard. Não é previsão. Não é relatório. É a decisão pronta. O motor decide a quantidade; o comprador aprova antes de enviar.

As sugestões chegam separadas em duas faixas:

- **Aprovação em bloco** — itens de demanda regular, histórico longo, sugestão dentro do padrão histórico de compra. O comprador confere o total e aceita.
- **Exceções** — item novo, demanda errática, desvio grande da compra média, promoção prevista, ou qualquer regra de guarda acionada. Lista curta, revisada linha a linha.

O objetivo é que ele revise dezenas de linhas, não centenas. A proporção de itens na faixa de aprovação em bloco cresce conforme o histórico de acerto se acumula.

### De onde vem o valor: dois andares

O valor medido no MVP (seção 6) não vem de um lugar só, e separar isso importa para o que se promete no contrato — inclusive para o que se cobra por ele (seção 3).

**Andar 1 — correção de calibração.** O ERP de um cliente típico tem um fator de reposição calibrado para o lead time que o fornecedor tinha quando alguém setou o mínimo/máximo — não para o de hoje. Ninguém volta para atualizar o cadastro quando o fornecedor muda de prazo. Só corrigir esse número, sem nenhum modelo, levou o nível de serviço medido de 60–66% para ~95% no MVP, e eliminou cerca de 87% da ruptura (em R$ de margem não realizada). A conta tem dois lados: sair de 60% para 95% de serviço também exige guardar mais estoque, não menos — no MVP, o capital médio empregado foi de ×3,84 (+284%) sobre o do baseline desatualizado (magnitude de 3 dias de lead time de defasagem; a de 5 dias está na aba Andar 1 do relatório mensal). O cliente precisa saber dos dois lados antes de assinar, não depois. Em R$ (**ilustrativo — preço uniforme de R$ 10, margem arbitrada**, aplicados a dado de uma loja do Equador; não sustentam valor absoluto, só os relativos acima): R$ 189.962/mês de margem recuperada em ruptura (faixa de sensibilidade de ±30%: R$ 132.973 a R$ 246.951/mês) e ~R$ 53.861/mês a mais de capital empregado.

**Andar 2 — refinamento estatístico.** Sobre um baseline JÁ recalibrado (mesmo nível de serviço do Andar 1), o motor entrega **−2,8% de capital médio empregado** e **+2,9% de margem por real investido**, no mesmo nível de serviço. É um ganho real, mas menor — e é daqui, não da cauda de itens irregulares, que ele vem (ver seção 9).

O Andar 1 abre a conta; o Andar 2 e a operação semanal da lista (reposição contínua) são o que a mantêm.

### O que o sistema nunca faz

Não escreve no ERP. Não emite pedido sozinho. Não substitui PDV, fiscal, NF-e, contas a pagar, movimentação de estoque ou cadastro mestre. Leitura na entrada, recomendação na saída, execução humana. Isso mantém o produto fora do território do ERP e elimina responsabilidade operacional.

---

## 3. Como é entregue

### Ciclo semanal

| Quando | O quê |
|---|---|
| Segunda, manhã | Extração do ERP: vendas até domingo, saldo de estoque, entradas, cadastro, preço e custo |
| Segunda, manhã | Motor roda: reconstrução de demanda, previsão, política, restrições |
| Segunda, tarde | Comprador recebe um arquivo por fornecedor, com lista principal e lista de exceções |
| Segunda/terça | Comprador revisa, ajusta, envia ao fornecedor |
| Contínuo | Registro do que foi sugerido versus o que foi efetivamente pedido |

O formato de entrega é o que ele já usa hoje — planilha ou PDF por fornecedor. Não obrigue ninguém a aprender interface nova na versão 1.

### Ciclo mensal

Relatório em R$, sempre contra baseline:

- Ruptura evitada (margem recuperada)
- Capital liberado (redução de estoque médio sem perda de nível de serviço)
- Perda evitada
- Itens sangrando margem (custo errado, preço abaixo do custo, margem negativa não intencional)
- Taxa de aceitação das sugestões

Este relatório é o que renova o contrato. Ele substitui a necessidade de vender de novo todo mês.

### Onboarding: modo sombra

Nas primeiras 4 a 8 semanas o motor roda em paralelo e **não altera nenhum pedido**. Registra o que teria sugerido e compara com o que o comprador fez. Isso entrega três coisas: o baseline real medido com dado do próprio cliente, prova de valor em número dele, e confiança. Ninguém entrega a compra do mês para um fornecedor novo na primeira semana.

### Cobrança

Mensalidade fixa por loja. Não cobrar percentual sobre ganho: é difícil de auditar, gera disputa sobre qual era o baseline, e trava a venda.

---

## 4. A política de decisão

### Janela de risco

O estoque que chega precisa cobrir **lead time + ciclo de revisão**, não apenas o lead time. Fornecedor que entrega em 4 dias e só aceita pedido semanal exige cobertura de 11 dias. Cobrir só o lead time é o erro mais comum e a principal causa de ruptura sistemática.

### Nível-alvo

O nível até o qual se enche a posição não é a demanda média da janela, é um **quantil** dela. O quantil vem de uma conta de negócio:

```
α = custo de faltar / (custo de faltar + custo de sobrar)
```

- Custo de faltar = margem não realizada
- Custo de sobrar = custo de carregar capital + risco de perda

| Categoria | α sugerido | Racional |
|---|---|---|
| Mercearia seca, alto giro | 0,92 – 0,97 | Sobrar é barato, faltar custa margem e imagem |
| Mercearia, giro médio | 0,85 – 0,92 | Capital começa a pesar |
| Perecível de validade média | 0,80 – 0,88 | Sobrar gera remarcação |
| Perecível de validade curta | 0,70 – 0,82 | Sobrar vira perda total |

É a mesma fórmula com um parâmetro diferente. É exatamente por isso que a previsão precisa ser **em quantis**, não em média: o valor usado é a cauda, não o centro.

### Quantidade

```
pedido = nível-alvo − (estoque em mãos + em trânsito)
pedido = arredonda para cima no múltiplo de fardo
```

Se o total do fornecedor não atinge o pedido mínimo, completa com os itens de **menor cobertura relativa** — nunca com o mais barato, nunca com o de maior desconto.

### Regras de guarda

Estas valem mais que o modelo. Quatro das seis são restrição, não estatística.

1. **Teto de cobertura.** Nenhum item ultrapassa X dias de estoque, mesmo que a conta peça. Protege contra modelo quebrado e pico sazonal mal lido.
2. **Limite de variação.** Sugestão muito acima da compra histórica média vai para exceções, não para a lista principal. Um erro de escala destrói a confiança de uma vez.
3. **Restrição de caixa.** Se a soma estoura o orçamento da semana, não corta proporcionalmente: prioriza por margem gerada por real investido. O que ficar de fora entra na semana seguinte.
4. **Calendário do varejo popular.** Venda concentra em início de mês e em dias de pagamento. Modelo que não captura isso rompe justamente no pico.
5. **Item novo ou sem histórico** sai por regra separada, nunca por modelo.
6. **Item com promoção prevista** tem demanda de outra natureza. Sem informação de promoção, o pedido sai errado — trate como exceção.

Adicional: itens âncora com margem baixa ou negativa intencional (arroz, leite, açúcar, refrigerante) devem ser marcados como tal. Recomendar descontinuar um âncora sem análise de cesta é o erro que faz o dono concluir que você não entende varejo.

**Limitação de desenho, medida no MVP:** o teto de cobertura (regra 1) só é uma guarda ATIVA quando a validade do produto é menor que a janela de risco (lead time + ciclo de revisão). Em categoria perecível com ciclo de revisão longo — a janela de risco maior que a própria validade —, o teto vira estruturalmente inoperante: não existe quantidade que viole um teto que a janela de risco já ultrapassa por conta própria. Proteção real, nesse caso, exige ciclo de revisão POR FORNECEDOR, não um valor único para o portfólio inteiro — o simulador do MVP não suporta isso hoje. Isto é débito de arquitetura, não bug: o teto continua correto como validade física; só não é a guarda ativa que se esperava dele justamente nas categorias mais sensíveis.

---

## 5. Dados necessários do cliente

Mínimo viável, extraível de qualquer ERP de varejo:

| Dado | Granularidade | Uso |
|---|---|---|
| Vendas | item × dia | Base da previsão |
| Saldo de estoque | item × dia | Posição atual e detecção de ruptura |
| Entradas / compras | item × data | Lead time real, em trânsito |
| Cadastro | item | EAN, categoria, unidade, fornecedor |
| Preço de venda e custo | item × data | Margem, conversão para R$ |
| Regras de fornecedor | fornecedor | Lead time, dia de entrega, pedido mínimo, múltiplo |

As regras de fornecedor quase nunca estão no ERP. São coletadas na entrevista de onboarding e mantidas manualmente.

Espere sujeira: EAN duplicado, item cadastrado duas vezes, custo desatualizado, unidade de compra diferente da de venda. A limpeza consome mais esforço que o modelo, e a auditoria de cadastro é a primeira vitória entregável — ela acha dinheiro na primeira semana sem modelo nenhum.

---

## 6. O MVP com dado público

O MVP não é o produto. É a **prova de que a lista funciona**, feita antes de existir cliente.

**O que ele precisa provar:** não que o modelo erra pouco, mas que a lista gerada teria dado mais dinheiro que a regra que o ERP usa hoje.

**Como:** simulador de política. Reproduz o histórico dia a dia — previsão → política → estoque simulado → atendimento → métricas — e acumula resultado em R$ ao longo de um período de operação simulado.

**Validação:** nada de split 80/10/10 em linhas. Os primeiros ~80% do histórico servem para construir features e escolher modelo. Os últimos 6 a 12 meses viram período de simulação com origem móvel: re-treino semanal, decisão semanal, cada decisão usando apenas dados anteriores a ela.

**Escopo computacional:** uma loja, 150 a 300 SKUs de demanda regular. Escopo maior não impressiona e faz perder o prazo.

**Braços de comparação:**

1. Baseline ERP — média móvel de 4 semanas + fator, implementado de forma honesta, não estrangulado; recalibrado por célula de lead time/ciclo de revisão (medido: recalibrar sozinho, sem nenhum modelo, é a maior parte do ganho — ver Andar 1, seção 2).
2. Previsão estatística + ponto de pedido com nível de serviço.
3. Previsão ML quantílica (LightGBM) + nível-alvo com α por categoria.
4. Baseline ERP desatualizado — o mesmo braço 1, mas com o fator calibrado numa célula antiga e aplicado sem recalibrar na célula real; representa o ERP do cliente de verdade, não um espantalho. Não estava na v1 — foi adicionado depois da primeira rodada de medição, porque comparar só contra um baseline já recalibrado escondia de onde vem a maior parte do valor.

**Métricas reportadas:** margem realizada, ruptura em R$, perda em R$, estoque médio (capital), nível de serviço, giro.

**Premissas a arbitrar** (dado público não tem): margem por categoria, lead time, ciclo de revisão, múltiplo de fardo, custo de capital, estoque inicial. Declarar todas e rodar sensibilidade em lead time e razão de custo.

**Limitação a declarar abertamente:** dado público não tem saldo de estoque, então ruptura não é observável nele. A correção de demanda censurada é projetada no MVP mas só é validável com dado de cliente.

**O que foi de fato medido (atualização pós-MVP):** a validação rodou numa única célula real (lead time = 7 dias, ciclo de revisão = 14 dias) — generalizar para outras combinações é hipótese, não resultado (ver seção 9). A comparação entre braços foi feita sempre no MESMO nível de serviço (metodologia iso-serviço): comparar `decision_metric` bruto entre braços em níveis de serviço diferentes se mostrou enganoso na prática — o braço 4 (ERP desatualizado) chegou a parecer mais "eficiente" que os outros só porque sub-abastecia a loja (60–66% de serviço), carregando menos estoque às custas de vender menos. O braço 3 (LightGBM) bate o braço 1 recalibrado, mas por uma margem pequena sobre o braço 2 (estatístico) — pequena demais, dada até a imprecisão da grade de calibração usada para o braço 3, para justificar o custo extra de complexidade (retreino periódico, menos auditável) numa v1. Isso é lido como vantagem de desenho, não como fracasso do modelo: entregar o braço estatístico simples, auditável e sem retreino é um produto mais defensável para a primeira venda.

---

## 7. Fora de escopo na versão 1

Remarcação de perecível, elasticidade e canibalização de promoção, sugestão de sortimento, compra antecipada por desconto de fornecedor, análise de cesta, multi-loja com transferência, multi-tenant e self-service.

Vendendo serviço em vez de software, também ficam fora: autenticação robusta, uptime garantido, onboarding automatizado. Isso corta a maior parte do escopo de engenharia sem custar nada em valor entregue.

---

## 8. Decisão em aberto

Base de dados do MVP: **M5 (Walmart)** ou **Corporación Favorita**. M5 tem benchmark público conhecido; Favorita é supermercado real, com promoção marcada e vendas fracionárias em kg, o que torna a narrativa da demo ("quantos kg de arroz comprar") natural.

---

## 9. Riscos

- **Qualidade de cadastro no cliente** pode inviabilizar a análise antes de qualquer modelo. Mitigação: auditoria de cadastro como primeira entrega.
- **Comprador humano é bom nos itens de alto giro.** Não posicionar como "eu bato o comprador" — e não posicionar a cobertura de cauda como fonte do ganho medido: o MVP mediu vantagem distribuída pelo portfólio, levemente maior nos itens de venda REGULAR, não nos irregulares (correlação fraca, Spearman 0,275 — contraria a tese original desta seção na v1). O argumento que se sustenta é de cobertura operacional: ele revisa bem 200 itens, o motor cobre 3.000 — ninguém troca isso por atenção humana a mais, mas o dinheiro não vem primariamente daí.
- **Perda não foi demonstrada.** O dado público não tem saldo de estoque — ruptura não é observável nele (é inferida pelo simulador, não medida), e perda por validade/vencimento não é modelada em nenhum braço (R$ 0,00 sempre, no MVP inteiro). O que o MVP prova é melhor alocação de capital e margem recuperada em ruptura, não redução de perda — perda evitada, como métrica do relatório mensal (seção 3), continua sem validação até haver dado real de estoque do cliente.
- **Validade restrita a uma célula.** Todo número desta versão (Andares 1 e 2, seção 2) foi medido numa única combinação de lead time e ciclo de revisão (7 e 14 dias). Generalizar para outras combinações — outro fornecedor, outro prazo de entrega — é hipótese, não resultado medido.
- **Consultoria de margem se esgota** — e isso agora vale também para o Andar 1 (seção 2): se a maior parte do valor medido está em corrigir uma calibração errada, essa é uma correção que se faz uma vez, não um serviço recorrente. A porta de entrada fica mais barata de entregar e mais fácil de provar — mas se esgota do mesmo jeito que a consultoria de margem sempre se esgotou. A recorrência continua onde sempre esteve: na reposição semanal (Andar 2 + operação da lista), não no diagnóstico inicial. Diagnóstico é porta de entrada; reposição é o contrato.
- **Falta de informação de promoção** degrada a previsão exatamente nos itens de maior volume.
