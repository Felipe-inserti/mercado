# Sprint 24 — Motor pronto para o primeiro dado real

Deixar o motor pronto para receber o dado do mercado piloto **antes de o dado existir**. Tudo nesta sprint trabalha sobre as tabelas canônicas (Favorita + dado sintético). A única peça que depende do formato real — o adaptador de entrada — fica de fora de propósito.

Origem: documento "Mudanças no código antes de rodar" (itens B a H), com as correções da revisão de 21/10/2026.

**Objetivo único:** quando a primeira amostra do mercado chegar, escrever só o adaptador e rodar o backtest. Nada acima de `io/` muda depois desta sprint.

**Estado de partida:** 368 testes, 0 pulados, 76% de cobertura (22/10/2026). Vale o `CLAUDE.md` inteiro: premissas em `params.yaml`, funções puras, polars, determinismo, docstrings em português e identificadores em inglês. Comandos sempre com `uv run` (`uv run pytest`, `uv run ruff`, `uv run mypy`).

---

## Regras da sprint

1. **Uma etapa por vez, nesta ordem.** Não começar a próxima com a anterior vermelha.
2. **Ao fim de cada etapa:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` e `uv run mypy src/` passam; o diff inteiro é lido; o commit é feito pelo usuário (o Claude sugere a mensagem e não executa `git add`/`git commit`).
3. **Não alterar:** `inventory.py`, `policy/supplier.py`, `policy/guardrails.py`, `policy/basestock.py`, `metrics/financial.py`, `io/loaders.py` e `io/raw.py`. `simulator/engine.py` só ganha a chamada da censura (24.4).
4. **Nenhum valor escondido.** Parâmetro que depende do dado real fica `null` no `params.yaml` e o código falha com mensagem clara se ele for usado vazio. Teste pode usar valores provisórios; o `params.yaml`, não.
5. **Regressão do Favorita** antes e depois das etapas que tocam o histórico (24.4 e 24.5). Mudou sem explicação, para.
6. **Dado de cliente nunca entra no git.** Toda fixture desta sprint é sintética.

---

## 24.0 — Linha de base

- Rodar a suíte e anotar: número de testes, pulados, cobertura.
- Rodar o experimento atual do Favorita e salvar o manifesto e os resultados em `results/baseline_sprint24/` (fora do git, se `results/` já estiver no `.gitignore`).
- Criar `tests/test_regression_favorita.py` (ou equivalente) que compara o resultado atual com esse manifesto. É ele que segura as etapas 24.4 e 24.5.

- Referência congelada em `tests/regression/favorita_baseline.json`. Comando (lento, fora do pytest padrão): `uv run pytest -m regression --no-cov tests/test_regression_favorita.py`.

**Pronto quando:** o teste de regressão passa no código sem nenhuma mudança.

---

## 24.1 — Configuração (`config/params.yaml`, `config.py`, `tests/test_params.py`)

Adicionar:

```yaml
mercado_piloto:
  censura:
    ativa: false
    janela_dias: 28
    media_minima_por_dia: null        # decidir com o dado real
    dias_minimos_com_venda: null      # decidir com o dado real
    dias_sem_entrada_antes: 3
    alerta_percentual_dias_censurados: 0.15
  qualidade:
    limite_percentual_critico: 0.02
    cadastro_minimo_completo: 0.90
    janela_regularidade_dias: 28
    percentual_dias_com_venda_regular: 0.80
  avaliacao:
    janela_teste_semanas: null        # decidir com a dona: 8 a 12
    quantis_cobertura: [0.8, 0.9, 0.95]   # subconjunto de model.quantiles (validado em Params)
```

- Modelos Pydantic correspondentes em `config.py`. Campos `null` são `Optional`, mas um acessor (ex.: `require(campo)`) levanta erro dizendo **qual** chave está vazia e onde preencher.
- `censura.ativa` com padrão `false`, para ligar e desligar sem mexer em código.

- `Params` rejeita qualquer valor de `avaliacao.quantis_cobertura` que não esteja em `model.quantiles` (que não tem quantil abaixo da mediana, por isso a cobertura é unilateral por quantil, e não um intervalo).

**Testes:** as chaves novas carregam; usar um campo `null` levanta erro com o nome da chave; `censura.ativa: false` é o padrão; `quantis_cobertura` fora de `model.quantiles` é rejeitado.

**Pronto quando:** o `params.yaml` carrega e nenhum teste antigo muda.

---

## 24.2 — Métricas de previsão (`src/motor/metrics/forecast_quality.py`)

Funções puras sobre arrays/Series alinhados. Todas aceitam `mask` opcional (booleano; `False` = observação excluída), usada para tirar os dias censurados da avaliação.

- `relative_mae(actual, forecast, naive_forecast, mask=None) -> float | None` — MAE do método ÷ MAE do naive sazonal **na mesma janela de teste**. Abaixo de 1 = melhor que o naive. Docstring diz explicitamente que não é o MASE clássico.
- `wape_weighted(actual, forecast, unit_value, mask=None) -> float | None` — Σ|erro|×valor ÷ Σreal×valor.
- `bias(actual, forecast, mask=None) -> float | None` — Σ(previsão − real) ÷ Σreal. Positivo = superestima.
- `quantile_coverage(actual, forecast_q, mask=None) -> float | None` — fração das observações com real ≤ quantil previsto. Calculada para cada quantil de `avaliacao.quantis_cobertura`, com o nível nominal (o próprio quantil) reportado ao lado.
- Observação com `None` em `forecast` ou `naive_forecast` é excluída das duas contas.
- Denominador zero → `None`. Nunca `inf` nem `NaN`.

O `Forecaster` devolve demanda **acumulada no horizonte**. As métricas comparam o acumulado previsto com o acumulado real da mesma janela.

**Testes** (`tests/test_forecast_quality.py`): cada função com um exemplo de 4 pontos calculado à mão (o cálculo escrito no comentário do teste); denominador zero → `None`; máscara exclui o ponto certo; `None` na previsão exclui o ponto das duas séries.

---

## 24.3 — Naive sazonal (`src/motor/forecast/naive_seasonal.py`)

`NaiveSeasonalForecaster` implementando o `Forecaster` de `forecast/base.py`.

- **Regra:** a previsão de um dia `d` do horizonte é a venda do **último mesmo dia da semana anterior a `as_of`**. Nunca `d − 7` quando isso cai em `d ≥ as_of`.
- `predict_quantiles` devolve o acumulado dos dias do horizonte, só para `quantile = 0.5`. Pedido de outros quantis levanta erro claro.
- Se algum dia de referência não existir no histórico, o acumulado é `None` (não zero, não soma parcial).

**Testes** (`tests/test_naive_seasonal.py`): série de 3 semanas conhecida, horizonte 7 → bate com a soma à mão; horizonte 14 → usa a última semana antes de `as_of` duas vezes, nunca dado posterior (usar o espião de `tests/fakes.py`); dia faltando → `None`; quantil ≠ 0,5 → erro.

---

## 24.4 — Censura de ruptura provável

A mudança de maior efeito no resultado. Pode ser dividida em três sessões (24.4a, 24.4b, 24.4c), cada uma com seu commit.

**24.4a — Contrato de entradas (`io/contracts.py`).** Novo modelo `Entry`: `store_id`, `item_id`, `received_date`, `quantity` (> 0), `order_date` (opcional), `supplier_id` (opcional). Mesma mecânica de `validate_table` dos outros modelos. Teste no `test_contracts.py`.

**24.4b — `src/motor/features/censoring.py`.**

- `flag_probable_stockout(sales, entries: pl.DataFrame | None, params) -> pl.DataFrame` → colunas `store_id`, `item_id`, `date`, `is_censored`, `reason`.
- Um dia é marcado quando, ao mesmo tempo:
  - venda do dia = 0;
  - média dos `janela_dias` anteriores ≥ `media_minima_por_dia`;
  - dias com venda nos `janela_dias` anteriores ≥ `dias_minimos_com_venda`;
  - nenhuma entrada do item nos `dias_sem_entrada_antes` dias anteriores.
- Se `entries is None`: a última condição é ignorada e `reason` registra isso. É o caso do Favorita.
- Saldo de estoque fica fora até haver dado real com saldo; reabrir com nova conversa (Emenda da Sprint 15 do `CLAUDE.md`: `stock` fora de `motor.features`). Por isso a função não recebe `stock`.
- A janela olha só o passado do dia (sem vazamento).
- `drop_censored(history, flags) -> pl.DataFrame` remove as linhas marcadas.
- `censoring_summary(flags) -> pl.DataFrame`: dias marcados por item e total, com alerta acima de `alerta_percentual_dias_censurados`.

**24.4c — Pontos de chamada.** A censura só mexe no histórico usado para **prever**. A demanda usada para medir atendimento na simulação não muda.

| Arquivo | Onde |
|---|---|
| `simulator/engine.py` | `_decide`: `history = self._demand_table.filter(...)` |
| `policy/erp_calibration.py` | `_precompute_forecasts`: `history = demand.filter(...)` |
| `features/build.py` | `build_features`: `history = sales.filter(...)` |
| `reporting/purchase_list.py` | os dois `history = demand.filter(pl.col("date") < as_of)` |
| `experiments/shared.py` | conferir o `warmup_slice`; aplicar se ele alimenta previsão |

Antes de editar: `grep -rn 'pl.col("date") <' src/` e listar todo ponto encontrado, aplicado ou não, com o motivo. As flags são calculadas uma vez e passadas para dentro; com `censura.ativa: false` (ou flags vazias) o comportamento é o mesmo de hoje.

**Testes** (`tests/test_censoring.py`):
- item regular, um zero sem entrada perto → marcado;
- mesmo zero com entrada nos 3 dias anteriores → não marcado;
- item intermitente → nenhum dia marcado;
- `entries=None` → regra aplicada sem a condição de entrada, `reason` diz isso;
- flags vazias → `drop_censored` devolve o histórico idêntico;
- simulador com censura ligada: demanda e `unmet_demand` registradas iguais às de sem censura; só o pedido pode mudar;
- `purchase_list` com censura ligada usa histórico censurado.

**Pronto quando:** regressão do Favorita idêntica com censura desligada; com ela ligada (limiares provisórios só no teste), o número de dias marcados é reportado.

---

## 24.5 — Linha de base desacoplada (`policy/erp_baseline.py`)

- `ErpBaselinePolicy` passa a receber a média diária (`daily_average: Callable[[date], float]`, ou o que mexer menos no protocolo `Policy`). Sai `_median_forecast` e a dependência do quantil 0,5. Atualizar a docstring do módulo (registrar a mudança, não apagar o raciocínio).
- Helper puro `moving_average_daily(history, as_of, weeks) -> float` calculado pelo chamador sobre o histórico **já censurado**.
- Atualizar todos os usos (`grep -rn ErpBaselinePolicy`): `policy/erp_calibration.py`, `experiments/run.py`, `experiments/stale_baseline.py`, `tests/test_erp_baseline.py`.

**Testes:** pedido não muda quando o forecaster é trocado; pedido bate com cálculo à mão num caso simples; testes antigos de `test_erp_baseline.py` continuam valendo.

**Pronto quando:** braço 1 do Favorita idêntico ao manifesto da 24.0. Se mudar, a diferença é explicada no commit antes de seguir.

---

## 24.6 — Relatório de qualidade (`src/motor/io/quality_report.py`)

Roda sobre as tabelas canônicas, então não depende do formato do mercado.

- `build_quality_report(sales, items, entries=None, stock=None, params) -> QualityReport`.
- Cada verificação é uma função pequena que devolve ocorrências com `tipo`, `item_id`, `date`, `valor`, `descricao`. O relatório agrega por tipo: quantidade, % sobre o total de linhas, cinco exemplos, e marca como crítico acima de `limite_percentual_critico`.
- Verificações:
  1. código com mais de uma descrição;
  2. devolução sem venda correspondente (`units_returned > 0` sem venda do item nos dias anteriores — janela no `params.yaml`);
  3. dia sem venda em item regular (reaproveitar a lógica da censura, sem duplicar);
  4. mesmo código com unidades de venda diferentes;
  5. recebimento antes do pedido (só se `entries` tiver `order_date`; senão "não avaliada");
  6. item ativo sem fardo ou sem validade; e % do cadastro completo contra `cadastro_minimo_completo`.
- Verificação sem dado para rodar aparece como **não avaliada**, nunca como zero ocorrências.
- Exportar xlsx em `results/quality/` com uma aba de resumo legível pela dona (em português, sem nome de coluna técnico) e uma aba por tipo.
- Se `reporting/auditoria_cadastro.py` (Sprint 22) já existir, reaproveitar o que se sobrepõe.

**Testes** (`tests/test_quality_report.py`): fixture sintética com exatamente uma ocorrência de cada tipo → relatório acha as seis, nem mais nem menos; fixture limpa → zero; sem `entries` → verificação 5 "não avaliada".

---

## 24.7 — Backtest de comparação (`src/motor/experiments/piloto_backtest.py`)

- Ponto de entrada que recebe as tabelas canônicas (Favorita agora; mercado depois) e o `params.yaml`.
- Origens móveis semanais; a janela final de `janela_teste_semanas` fica reservada. Com o valor `null`, o backtest falha com a mensagem da 24.1; para o Favorita, passar o valor por argumento explícito.
- Em cada origem, os três métodos com **o mesmo histórico censurado**:
  1. regra ERP (braço 1, via 24.5) — previsão implícita = média diária × horizonte;
  2. naive sazonal (24.3);
  3. motor atual (braço 2, `forecast/statistical.py`).
- Classe de demanda (regular, intermitente, errática) calculada **só com dado anterior à janela de teste**.
- Métricas da 24.2 por método × classe, com os dias censurados da janela de teste excluídos pela máscara.
- Saída em `results/piloto/`: tabela (uma linha por método × classe), `censoring_summary` gravado na saída do backtest (dias marcados por item e total, com alerta; ausente com `censura.ativa: false`), e manifesto com hashes dos insumos, `params.yaml` e commit.

**Testes:** ponta a ponta com dado sintético pequeno — os três métodos rodam na mesma janela; uma linha por método × classe; rodar duas vezes gera bytes idênticos.

**Pronto quando:** a tabela sai preenchida para o Favorita.

---

## 24.8 — Fechamento

- Emenda datada no `CLAUDE.md`: módulos novos (`censoring`, `forecast_quality`, `naive_seasonal`, `quality_report`, `piloto_backtest`), o contrato `Entry`, a mudança do braço 1 e a regra "censura só no histórico de previsão". Não apagar emendas antigas.
- Lista de decisões em aberto (os `null`) num lugar só, com o que é preciso para fechar cada uma.
- Anotar número de testes e cobertura finais ao lado dos da 24.0.

### Pendências antes do piloto

- **[OBRIGATÓRIA] `ARM2_CHOSEN_ALPHA` fora da grade de quantis.** `experiments/iso_service.py` define `ARM2_CHOSEN_ALPHA = 0.66`, que não está em `model.quantiles` do `params.yaml` (`[0.5, 0.7, 0.8, 0.85, 0.9, 0.95]`). A decisão por item da lista de compra (`reporting/purchase_list.py::_decide_item`) levanta `ValueError` (alpha fora da grade) com o `params.yaml` atual, então a lista de compra não roda. Não corrigido na Sprint 24, por decisão explícita. Registrado em `tests/test_purchase_list.py` por um teste `xfail(strict=True)`: quando o bug for corrigido o teste passa, o `strict` o derruba, e o `xfail` deve ser removido.
- Alvo de treino do GBM (braço 3) não é censurado; fora da v1.

---

## Pronto da sprint

- 24.0 a 24.8 concluídas, com todos os comandos verdes.
- Regressão do Favorita sem mudança não explicada.
- O backtest roda no Favorita de ponta a ponta com censura ligada e desligada.
- Os `null` do `params.yaml` estão listados como decisões em aberto, e nenhum tem valor escondido no código.
- Para o mercado faltam só três coisas: o adaptador (`io/market_adapter.py`), os limiares da censura e a janela de teste.

## Fora desta sprint

- **Adaptador do mercado (`io/market_adapter.py`).** Espera a amostra do dado real.
- Mudanças no braço 3 (LightGBM), calendário brasileiro, dashboard.
