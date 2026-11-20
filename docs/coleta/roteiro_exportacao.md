# Como separar os dados para o piloto

Este roteiro é para a dona do mercado ou o suporte do sistema de caixa.
Os [cinco modelos CSV](modelos/) têm somente duas linhas **FICTÍCIAS** cada,
para mostrar o formato. Não representam um período suficiente de histórico.

1. Escolha uma loja e exporte as vendas diárias por produto, com quantidade,
   devoluções separadas, preço quando disponível e indicação de promoção.
   Precisamos distinguir dia fechado, dia sem venda e dia sem registro;
   explique como o sistema registra cada caso. Não envie cupons individuais.
2. Exporte o cadastro dos produtos: código, descrição, categoria, unidade ou
   kg, fornecedor, fardo, custo, preço de referência e se é perecível. Se o
   sistema não tiver um campo, informe isso; não preencha com zero inventado.
3. Exporte o cadastro dos fornecedores com prazo real de entrega, dias em que
   aceitam pedido, cadência de compra e mínimos em reais/unidades. Se esses
   campos não existirem no sistema, a dona pode informar a rotina em separado
   para validação. Não usar os 7/14 dias do experimento como cadastro real.
4. Se houver, exporte os saldos diários de estoque e as quantidades em
   trânsito. Se só houver saldo atual, diga a data; ele não substitui todo o
   histórico. Informe saldos negativos para revisão, sem corrigi-los em
   silêncio.
5. Se houver, exporte os recebimentos de mercadorias: loja, produto, data e
   quantidade; data do pedido e fornecedor quando disponíveis. Duas entradas
   do mesmo item no mesmo dia devem continuar separadas.

## Qual período pedir

A configuração atual exige **52 semanas (364 dias) antes do início da
simulação**, mais **90 dias de aquecimento**, descartados da avaliação
financeira. São **454 dias anteriores ao primeiro dia avaliado**, e ainda
é preciso acrescentar todo o período de avaliação combinado com a dona e
Felipe. Não basta exportar só três meses. A janela de teste do piloto está
`null`: não há duração escolhida; 8–12 semanas é proposta a confirmar.

Peça vendas, saldos e recebimentos do mesmo período, quando disponíveis,
mais os cadastros correspondentes. Felipe ajustará datas e códigos da loja
na configuração do piloto após conferir a amostra. Os códigos e datas
atuais são do Favorita, não do mercado.

## Formato e conferência

Prefira CSV em UTF-8, com cabeçalho, separador vírgula, datas `AAAA-MM-DD`,
decimais com ponto e códigos como texto para preservar zeros iniciais.
Use `true`/`false` para indicadores conhecidos e célula vazia para informação
desconhecida. O modelo de fornecedores representa dias como lista JSON:
`"[1,4]"` = segunda e quinta. Não remover colunas opcionais do modelo.

Se o sistema só exportar planilha ou CSV com ponto e vírgula, entregue o
formato original e avise o suporte; não editar manualmente milhares de
linhas. Informe a unidade e o significado dos campos disponíveis. O
[dicionário](dicionario_de_dados.md) permite mapear os nomes do sistema.
O adaptador do ERP ainda depende dessa amostra: estes CSVs não são lidos
diretamente pela CLI atual, que consome parquet canônico.

Antes de entregar, confira se todos os produtos têm código estável e se os
fornecedores dos produtos constam no cadastro. Registre campos e períodos
ausentes; não fabricar vendas, saldos, custos ou recebimentos.

## O que não enviar

Não enviar nome ou cadastro de cliente pessoa física, CPF, telefone,
endereço de cliente, cartão ou dados de pagamento. Os dados necessários
estão agregados por loja, produto e dia, sem identificar compradores.

Decisões pendentes, responsáveis e evidência necessária estão em
[`docs/decisoes_em_aberto.md`](../decisoes_em_aberto.md).
