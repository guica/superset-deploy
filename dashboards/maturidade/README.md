# Dashboard "Plataforma — Maturidade dos Apps" (`/superset/dashboard/maturidade/`)

Responde, com dado vivo, às quatro perguntas de acompanhamento dos apps do home-app:

| # | pergunta | onde no dashboard |
|---|---|---|
| 1 | Onde vai o esforço, e o uso justifica? | "PRs por app", "Funcionalidade × correção", bolhas esforço × uso, "PRs por 1.000 acessos", "apps sem uso" |
| 2 | O esforço está surtindo efeito? | razão de conserto amortecida por semana, acessos por semana, tabela de tendência (3 semanas vs 3 anteriores) |
| 3 | Quem está estabilizado? | placar (`SITUACAO = Estabilizado`), "Correções por 1.000 acessos" |
| 4 | Quem pede atenção? | placar (`SITUACAO = Atenção`), "Erros por 1.000 acessos", erros por semana |

Irmão do `uso-humano/` — mesma conexão Superset ("Snowflake CUSTOMER_DB", id 2), mesma
dedup e unidade de uso. As três pernas — **entrega**, **uso** e **erro** — chegam curadas
pela DAG `maturity_pipeline` (repo `priv-data-customer-cost-ingestion`, irmã da
`customer_cost_pipeline`: extrai → S3 → bronze → curadoria em SQL), em
`CUSTOMER_DB.CUSTOMER.APP_*`. Os datasets daqui são leituras diretas dessas tabelas.

| arquivo | o que é |
|---|---|
| `dataset_mat_prs.sql` | `mat_prs` — `CUSTOMER.APP_PR_HISTORY`: 1 linha por PR mergeado (tipo, app, fonte da atribuição, semana) |
| `dataset_mat_uso_semanal.sql` | `mat_uso_semanal` — `CUSTOMER.APP_USAGE_WEEKLY`: acessos a telas por app × semana × origem |
| `dataset_mat_sentry_semanal.sql` | `mat_sentry_semanal` — `CUSTOMER.APP_SENTRY_DAILY`: erros por app × dia × projeto × fonte |
| `dataset_mat_placar.sql` | `mat_placar` — `CUSTOMER.APP_MATURITY_SCORE`: 1 linha por app com as quatro perguntas e a `SITUACAO` |
| `dataset_mat_movimento.sql` | `mat_movimento` — `CUSTOMER.APP_MATURITY_WEEKLY`: app × semana, janela deslizante de 3 semanas (o "filme") |
| `build.py` | cria/atualiza datasets, charts e o dashboard via API (idempotente por nome) |
| `verify.py` | executa a query de cada chart via `/api/v1/chart/data` |

```bash
export $(grep -v '^#' ../../../superset-mcp/.env | xargs)   # SUPERSET_BASE_URL/USERNAME/PASSWORD
python3 build.py && python3 verify.py
```

## As métricas (ler antes de interpretar)

- **Tipo** vem do prefixo do título do PR (`feat`, `fix`, …), garantido pelo gate
  `pr-title.yml`. **App** vem do escopo entre parênteses (`APP_FONTE = titulo`); PR anterior ao
  gate ou fora do padrão é atribuído pelo caminho de arquivo (`arquivos`). O gráfico "PRs
  classificados pelo título" mostra a proporção — a meta é 100% `titulo`.
- **Razão de conserto** = `fix ÷ (fix + feat)`. Só `feat`/`fix`/`perf`/`refactor` são entrega;
  `docs`/`ci`/`test`/`chore`/`style`/`build` ficam fora da razão de propósito.
- **Amortecimento** (janelas de 3 e 6 semanas): `(fix + 6·p₀) ÷ (n + 6)`, com `p₀` = razão do
  app nos 90 dias (placar) ou 180 dias (movimento). Com 2 PRs a razão bruta só pode ser 0, 50 ou
  100% — a bolha pularia sem nada ter mudado. Um PR anda 14% do caminho entre a média e o
  observado; 6 PRs, metade; 20, 77%. Sem estado entre semanas: sem lag, sem deriva.
- **Acesso a tela** = `(cliente, usuário, app·seção, minuto)` distinto, só `env=prod`.
- **PRs / correções / erros por 1.000 acessos** normalizam esforço e dor pelo uso. Exigem ≥50
  acessos (placar) ou ≥30 (movimento); abaixo disso ficam nulos — a taxa vira ruído.
- **Tendência**: últimas 3 semanas vs. as 3 anteriores — `USO_DELTA_PCT` (%) e `FIX_DELTA_PP`
  (pontos da razão amortecida).
- **Situação** (ordem de avaliação importa):
  1. `Inativo` — sem PR e sem acesso em 90 dias
  2. `Sem uso` — recebeu PRs, zero acesso em produção
  3. `Sem evidência` — menos de 4 PRs
  4. `Atenção` — ≥400 acessos e (conserto amortecido >62% **ou** subindo ≥8 pp)
  5. `Esforço sem retorno` — <300 acessos e >100 PRs por 1.000 acessos
  6. `Sob pressão` — ≥20 PRs e conserto >62%
  7. `Estabilizado` — ≥400 acessos, ≤12 correções por 1.000 acessos e ≤15 PRs em 6 semanas
  8. `Em construção` — conserto ≤45%
  9. `Em estabilização` — o resto

## Pontos cegos

- **Cache**: tela servida do result cache não gera `QUERY_TAG` — ausência de acesso ≠ não uso.
- **Pessoa**: o tag das telas ainda não carrega `caller`; acesso conta por cliente. Quando o
  backend gravar o `caller` no ramo `X-App-Page`, as contagens passam a ser por pessoa sem
  mudar SQL.
- **Sentry sem `transaction`**: em set/2026, 59% dos eventos de erro em prod não tinham
  `transaction` e aparecem como `~sem-atribuicao` (gráfico "Ponto cego do Sentry"). A tag
  `app` (PR "Carimbar o app no Sentry") elimina isso daqui para a frente — o histórico
  anterior continua cego.
- **Celery em prod** carimba `level_2 = Geral` e se mistura às telas sem seção (≥93% das
  queries em horário comercial: ruído pequeno).
- **Sentry** entra por dia dentro da retenção de 90 dias; antes disso não há histórico.
- A lógica das métricas (classificação, amortecimento, situação) vive em
  `priv-data-customer-cost-ingestion/dags/sql/maturity_refresh.sql` — mudou lá, muda aqui.
