# Sprints 21–23 — Preparar o repositório para o investidor

Continuação do plano de 18 sprints e das Sprints 18–20 já feitas no repositório. Mesma regra: cada sprint tem um objetivo único, uma condição de pronto verificável, e não se avança com a anterior aberta.

O princípio que ordena estas três: **primeiro deixar os números honestos, depois provar que o motor roda com dado de mercado de verdade, e só por último escrever a vitrine.** O README e o relatório visual descrevem o que existe; se forem escritos antes, descrevem o que existia na semana passada e precisam ser reescritos.

Estado de partida (verificado em 05/10/2026): 367 testes passando, 1 pulado, 76% de cobertura; simulador, política e guardas entre 98% e 100%. Nenhuma lógica do motor precisa mudar nestas sprints, só as bordas: entrada de dados, relatórios e documentação.

---

## Sprint 21 — Números honestos e repositório coerente

Corrigir tudo o que um leitor cético encontraria em cinco minutos. Nenhuma funcionalidade nova.

Está sozinha e vem primeiro porque toda peça posterior (README, relatório visual, deck) cita números. Se a fonte dos números estiver errada, o erro se espalha por todas elas.

**1. Valores absolutos em R$.** O "R$ 189.962/mês" e o "R$ 53.861/mês" saem de preço uniforme de R$ 10 (`params.yaml`, `uniform_unit_price`) e de margens arbitradas, aplicados a uma loja do Equador. O valor absoluto não se sustenta; os relativos sim. Mudanças:
- `monthly_report.py`: a aba "Resumo executivo" passa a abrir pelos indicadores relativos (nível de serviço 60% → 95%, capital −2,8%, margem por real +2,9%). Os valores em R$ continuam, rotulados como "ilustrativo — preço uniforme de R$ 10, margem arbitrada".
- `notebooks/sprint20_apresentacao.py`: lâminas 2 e 3 trocam o número grande em R$ pelo relativo; o R$ vai para o rodapé com o mesmo rótulo.
- `docs/documento_negocio_v2.md`, seção 2: mesma troca.

**2. Contradição sobre as guardas.** A emenda da Sprint 17 no `CLAUDE.md` diz que `guardrails.py` "nunca foi implementado". O código (Etapa 3.16, 98% de cobertura), a lista de compra e o PDF mostram 4 guardas ativas. Acrescentar uma emenda datada dizendo que as 4 foram implementadas na Etapa 3.16 e que `promocao_prevista` e `item_ancora` continuam fora. Não apagar a emenda antiga: o histórico de decisões é parte do valor do arquivo.

**3. Limpeza.**
- `.claude/settings.json` tem caminhos da máquina local (`/home/felipe/.local/bin/graphify`). Remover do repositório e adicionar ao `.gitignore`.
- Renomear os notebooks por função, não por sprint: `sprint20_apresentacao.py` → `gerar_apresentacao.py`, `sprint17_iso_servico.py` → `comparacao_iso_servico.py`, `sprint15_comparacao_bracos.py` → `comparacao_bracos.py`. Atualizar as referências em docstrings.
- Regenerar `docs/entregaveis/` (PDF e relatório mensal) com as mudanças acima.

**Pronto quando:**
- Uma busca por `189` e `53.861` em `docs/` e `notebooks/` só encontra ocorrências ao lado do rótulo "ilustrativo".
- O PDF e o relatório regenerados abrem com os números relativos na frente.
- `CLAUDE.md` não afirma mais nada que o código contradiz.
- `pytest`, `ruff` e `mypy` passam como antes.

---

## Sprint 22 — Dado de mercado real: loader do cliente e auditoria de cadastro

Provar que o motor sai do Kaggle. É a sprint de maior impacto na reunião.

Está sozinha porque é a primeira vez que a promessa da Sprint 1 é testada: "o contrato define o que o sistema precisa, e isso torna o motor portável para o ERP de um cliente sem reescrever nada acima de `io/`". Se essa promessa falhar, é melhor descobrir agora do que na frente do investidor.

**Ponto a favor, já verificado:** o braço 2 (`forecast/statistical.py`) não usa `features/calendar.py`, que lê feriados direto do Favorita. A lista de compra, portanto, roda com dado de cliente sem resolver o calendário brasileiro. O calendário só importa para o braço 3 (LightGBM), que está fora da v1.

**1. `io/loaders_cliente.py`.** Da exportação do cliente para as quatro tabelas canônicas. Duas entradas:
- **Exportação de relatórios (CSV/Excel)**, se o cliente tiver ERP: vendas por produto e dia, cadastro, posição de estoque.
- **XML de nota fiscal**, se não tiver ou como complemento: NFC-e de venda vira `sales`; NF-e de entrada vira custo real, `supplier_id` e lead time observado.

`suppliers` (dia de pedido, prazo, pedido mínimo, fardo) vem da entrevista e entra por um arquivo YAML ou CSV preenchido à mão. `stock` continua opcional, como hoje.

Decisões a documentar, no mesmo estilo D1–D9 da Sprint 3: o que fazer com cancelamento e devolução, com venda em código genérico ("diversos"), com item cadastrado duas vezes, e com unidade de compra diferente da de venda (caixa com 12 → fardo 12).

**2. `profiling` para o cliente.** O mesmo perfil da Sprint 2, sobre o dado dele: período coberto, número de itens, proporção de dias com venda, **proporção do faturamento em código genérico** (se for alta, o dado não serve para reposição, e isso é um resultado).

**3. `reporting/auditoria_cadastro.py`.** A primeira entrega que acha dinheiro sem modelo (documento de negócio, seção 5). Um xlsx com:
- itens com preço abaixo do custo (margem negativa);
- EAN duplicado e item cadastrado duas vezes;
- custo de cadastro diferente do custo da última nota de entrada;
- itens sem venda há mais de N dias com estoque positivo (se houver `stock`).

**4. Descrição do produto na lista de compra.** `purchase_list.py` só mostra código e categoria porque `Item.description` é nulo no Favorita. Com dado de cliente ela existe: acrescentar a coluna "descrição" quando preenchida.

**Se ainda não houver dado de cliente:** a sprint é feita do mesmo jeito, contra arquivos de exemplo construídos à mão (um CSV de vendas, dois ou três XMLs de nota), igual à fixture da Sprint 3. O loader fica pronto para o primeiro cliente e a portabilidade fica provada por teste. Nesse caso a auditoria é demonstrada sobre o exemplo, e isso precisa ser dito como tal.

**Pronto quando:**
- Um teste constrói um caso pequeno (vendas, cadastro, XML de entrada) com problemas conhecidos (devolução, EAN duplicado, item com margem negativa) e verifica que o loader produz as tabelas canônicas que passam em `validate_table` e que a auditoria aponta exatamente os problemas plantados.
- `purchase_list` roda sobre as tabelas do cliente e gera um xlsx com descrição.
- Nenhum arquivo acima de `io/` foi alterado para isso, exceto a coluna nova de `purchase_list.py`. Se outro foi, a promessa da Sprint 1 falhou em algum ponto, e isso vira uma nota no `CLAUDE.md`.
- Dado do cliente nunca entra no git (`data/` já está no `.gitignore`; conferir que exportações e XMLs ficam lá dentro).

---

## Sprint 23 — Vitrine: README e relatório que se lê em 10 segundos

Fazer o projeto se explicar sozinho para quem nunca o viu: investidor, cliente ou recrutador.

Está por último porque descreve o que as duas anteriores produziram. Escrever antes é escrever duas vezes.

**1. README.md reescrito.** Hoje são 20 linhas de instalação. Passa a ser a primeira página do projeto:
- o problema em três linhas (compra no olho, ruptura invisível no ERP, grande varejo já resolveu e o pequeno ficou de fora);
- o que o sistema entrega: a lista de compra semanal por fornecedor e o relatório mensal, com imagem de cada um;
- diagrama das quatro partes: dados → previsão → decisão → entrega, com o simulador validando por fora (Mermaid, que o GitHub renderiza);
- o que foi medido, só em números relativos, com a célula (lead time 7 / revisão 14) e o mesmo nível de serviço ao lado;
- como se sabe que funciona: o teste de aceitação com resposta analítica, a comparação iso-serviço, o baseline honesto, e o número de testes e a cobertura;
- de onde vêm os dados: Favorita no MVP, exportação do ERP ou nota fiscal para cliente (Sprint 22);
- limitações, copiadas do documento de negócio, não suavizadas;
- como rodar.

**2. Aba "Resumo visual" no relatório mensal.** Primeira aba de `relatorio_mensal.xlsx`: três números grandes (nível de serviço, capital, margem por real) e um gráfico simples, legível no celular. As abas atuais continuam atrás dela.

**3. Gráfico para o README.** Gerado por notebook (regra da seção 2 do `CLAUDE.md`: gráfico vive em notebook, não em `src/`), salvo em `docs/img/`.

**Pronto quando:**
- Alguém que nunca viu o projeto lê o README e consegue responder em dois minutos: o que é, para quem, o que foi medido e quais são as limitações. Teste com uma pessoa de verdade (um colega), não por autoavaliação.
- O relatório mensal abre na aba visual.
- Todo número do README tem a origem ao lado.

---

## Fora destas sprints

- **Deck do investidor.** Não é código e não mora no repositório. É feito à parte depois da Sprint 21, reaproveitando as lâminas 5 a 8 do PDF atual, e acrescentando mercado, modelo de negócio, situação do cliente e próximos passos.
- **Dashboard.** Não na v1 (ver documento de negócio, seção 2: "não é dashboard").
- **Melhorar o modelo de ML.** O MVP mediu que o braço 3 não compensa a complexidade na v1.
- **Refatorações grandes.** Nada abaixo de `io/` e acima de `reporting/` muda.

## Se o tempo até a reunião apertar

A ordem de corte é a inversa do impacto: se só der para fazer uma, faça a 21 (é rápida e evita o pior risco, um número que cai na primeira pergunta). Se der para fazer duas e o cliente tiver mandado dados, faça a 22 em seguida, porque achados no dado dele valem mais que qualquer README.
