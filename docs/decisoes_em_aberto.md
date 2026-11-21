# Decisões em aberto — mercado piloto

Lista única das premissas ainda dependentes do mercado. Estado em
20/11/2026, conferido em `config/params.yaml`. Nenhum valor foi alterado
para fechar esta lista. Felipe valida o método; a dona do mercado valida
as restrições comerciais; dados reais sustentam as escolhas.

| Chave e valor atual | O que controla | Quem decide | Evidência necessária | Se ficar como está |
|---|---|---|---|---|
| `mercado_piloto.censura.media_minima_por_dia: null` | Média mínima anterior para suspeitar de ruptura em dia com venda zero | Felipe, com dado real e confirmação da dona | Vendas diárias, recebimentos e exemplos de falta versus baixa demanda | Com censura desligada, não é usado; ao ativá-la, `MissingParamError` nomeia a chave |
| `mercado_piloto.censura.dias_minimos_com_venda: null` | Regularidade mínima na janela anterior de 28 dias | Felipe, com dado real | Distribuição de dias com venda e validação de casos pela dona; valor não pode exceder a janela | Mesmo bloqueio ao ativar a censura; não existe limiar implícito |
| `mercado_piloto.avaliacao.janela_teste_semanas: null` | Duração da avaliação do piloto | Dona do mercado e Felipe | Histórico disponível, calendário comercial e tempo de acompanhamento; 8–12 semanas é proposta no YAML, não decisão | Consumidor que chamar `require` falha; não há janela de piloto definida, nem backtest 24.7 implementado |
| `quantile_gbm.decay_half_life_days: null` | Meia-vida dos pesos do treino expansivo do braço 3 | Felipe, com dado real | Comparação temporal sem vazamento, sazonalidade e mudanças de regime | Neutro: sem decaimento por idade; não bloqueia o modelo |
| `purchase_list.alpha: 0.66` | Quantil usado na decisão da lista | Felipe e dona do mercado | Relação falta/sobra, margem, serviço e capital no dado real | Mantém o alpha herdado do iso-serviço lt=7/rp=14; não há recalibração automática pelo experimento |
| `purchase_list.lead_time_days_override: 7` | Prazo de entrega aplicado a todos os fornecedores da lista | Dado real, validado pela dona e por Felipe | Cadastro e datas reais de pedido/recebimento por fornecedor | Continua sobrescrevendo o cadastro com 7 dias; **deve virar `null` com cadastro real validado** |
| `purchase_list.review_period_days_override: 14` | Cadência de revisão aplicada a todos os fornecedores da lista | Dona do mercado e Felipe, com dado real | Dias aceitos para pedido, entregas e rotina de compra por fornecedor | Continua sobrescrevendo o cadastro com 14 dias; **deve virar `null` com cadastro real validado** |
| `purchase_list.budget_period_days: 14` | Orçamento por ciclo = `guardrails.weekly_budget_rs × dias / 7` | Dona do mercado, com conferência de Felipe | Caixa disponível, calendário de pagamentos e horizonte real do orçamento | Mantém orçamento de duas semanas; é independente da revisão de cada fornecedor |

O [pacote de coleta](coleta/roteiro_exportacao.md) reúne a evidência a pedir.
Os quatro `null` têm semânticas distintas; preenchê-los exige decisão
registrada, nunca um fallback numérico no código.
