# superset-deploy

Configuração de deploy de uma instância **Apache Superset 6.1.0** em Docker Compose,
com **Alerts & Reports funcionando de verdade** — isto é, mandando print de gráfico
por e-mail — e com o **tema visual da Astecha** (logo, cores, fontes e paleta dos
gráficos) versionado como código.

Este repositório guarda **só o que é nosso**: a imagem customizada com headless
browser, o nginx com TLS, o override de configuração do Superset, o tema e os
assets da marca, e os scripts de certificado, backup e upgrade. O Superset em si
continua vindo da imagem oficial, **com a versão pinada** (nunca `latest`).

Onde roda: EC2 `dashboards-prod` (`i-07a5ae79baa590070`, us-east-2), diretório
`/home/ubuntu/superset`, acesso por **SSM** (`aws ssm start-session` / `send-command`;
a porta 22 não é pública desde o zero-trust). URL: https://dashboard.astecha.com.br
(via WARP).

---

## Por que este repositório existe

A instalação padrão fica num clone do repositório upstream `apache/superset`, e
isso cria um problema silencioso: **os dois arquivos mais importantes de um deploy
real são gitignorados pelo próprio Superset.**

```
docker/pythonpath_dev/.gitignore:19:*   →  superset_config_docker.py
.gitignore:123:docker/*local*           →  docker/.env-local
```

O `git status` mostra a pasta limpa e passa a impressão de que não há nada para
versionar — enquanto toda a configuração de produção (SMTP, feature flags,
webdriver) mora exatamente ali. Além disso, um clone do upstream não aceita push
e briga com `git pull` a cada alteração local.

---

## O problema principal que este setup resolve

A imagem publicada `apache/superset` é o flavor **lean: não traz browser nenhum**.
Todo Report que manda screenshot morre com:

```
Failed taking a screenshot ... chromedriver unexpectedly exited. Status code was: 127
```

O `127` engana: parece binário ausente, mas é **biblioteca de sistema faltando**
(`libglib`, `libnss`, `libnspr`, `libxcb`, `libdbus`). O selenium-manager do
Superset baixa o chromedriver sozinho, ele não roda, e o ciclo se repete a cada
execução — na nossa instância isso acumulou **3,9 GB** de cache com 10 versões do
Chrome baixadas em loop.

A correção é [`docker-browser/Dockerfile`](docker-browser/Dockerfile): a imagem
oficial + **Playwright com Chromium**, que é a abordagem recomendada pelo projeto
desde a 4.1.x e o que o Dockerfile oficial faz via `--build-arg INCLUDE_CHROMIUM=true`.

---

## Estrutura

| Caminho | O que é |
|---|---|
| `docker-browser/Dockerfile` | imagem `apache/superset:${SUPERSET_VERSION}` + Playwright + Chromium |
| `docker-compose.yml` | stack completa, versão pinada via `TAG`/`BROWSER_TAG`; só o `superset-worker` usa a imagem com browser |
| `conf/nginx/` | `nginx.conf` + vhost TLS com headers de segurança |
| `docker/pythonpath_dev/superset_config_docker.py` | override de config do Superset (SMTP, feature flags, esperas do screenshot, branding, tema, paletas) |
| `docker/themes/astecha-light.json`, `astecha-dark.json` | tema Astecha (tokens Ant Design + overrides ECharts), carregado pelo config |
| `docker/assets/` | logos da marca, montados em `/static/assets/astecha/` |
| `docker/.env-local.example` | modelo do arquivo de segredos (o real nunca é commitado) |
| `scripts/backup-db.sh` | backup do metadata DB + volume antes de qualquer upgrade |
| `scripts/upgrade-superset.sh` | pull + build + `compose up` com migração, para subir de versão |
| `scripts/chart_theme_review.py` | revisão dos charts/dashboards existentes para aderirem ao tema (via API) |
| `scripts/init-letsencrypt.sh` | emissão inicial do certificado |
| `scripts/renew-cert.sh` | renovação + reload seguro do nginx |

---

## Deploy

```bash
git clone <este-repo> superset-deploy && cd superset-deploy

# 1. Segredos (nunca commitados)
cp docker/.env-local.example docker/.env-local
$EDITOR docker/.env-local      # SUPERSET_SECRET_KEY, MAIL_PASSWORD, domínio

# 2. Imagem com o headless browser (só o worker precisa dela) — mesma versão do TAG
docker build --build-arg SUPERSET_VERSION=6.1.0 -t astecha/superset-browser:6.1.0 docker-browser/

# 3. Certificado (primeira vez)
EMAIL=voce@dominio DOMAIN=seu.dominio ./scripts/init-letsencrypt.sh

# 4. Subir
docker compose up -d
```

O `docker/` do upstream (`docker-bootstrap.sh`, `docker-init.sh`, `.env`) continua
vindo do repositório do Superset — este repo cobre apenas os arquivos próprios.

---

## Tema Astecha (branding, cores, fontes, gráficos)

Tudo é configuração, nada é fork: o Superset 6 tem tema por tokens (Ant Design v5)
e overrides de ECharts por tema, e é isso que usamos.

| Camada | Onde | O que controla |
|---|---|---|
| `THEME_DEFAULT` / `THEME_DARK` | `superset_config_docker.py` ← `docker/themes/*.json` | logo, nome do app, cor primária/links/estados, fonte (Fira Sans / Fira Code via Google Fonts), raio de borda |
| `echartsOptionsOverrides` | dentro do JSON do tema | fonte dos gráficos, legenda com marcador redondo, tooltip sem borda e com sombra |
| `echartsOptionsOverridesByChartType` | idem, chave = `viz_type` | barras com canto arredondado, linhas 2.5px, fatias de pizza/treemap com separador |
| `EXTRA_CATEGORICAL_COLOR_SCHEMES` | `superset_config_docker.py` | paleta `astecha` (mesma `ASTECHA_PALETTE` do home-app), **default** para todo gráfico |
| `EXTRA_SEQUENTIAL_COLOR_SCHEMES` | idem | `astechaPurple` (default), `astechaRedPurple` (divergente), `astechaRisk` (ok → crítico) |
| `APP_NAME` / `APP_ICON` | idem | título da aba e logo do favicon/header |

Como o tema entra no ar: na subida do app o Superset faz **upsert** de
`THEME_DEFAULT`/`THEME_DARK` na tabela `themes` (`is_system=True`). Com
`ENABLE_UI_THEME_ADMINISTRATION` (default `True`), a UI em *Settings > Themes*
mostra esses dois como "system"; enquanto ninguém marcar outro tema como *system
default* na UI, o que vale é o do config. **Se alguém setar um tema pela UI, ele
passa a ganhar do config** — por isso a regra é: edita-se o JSON no repo, não na UI.

Para testar uma mudança de tema sem deploy: cole o JSON em *Settings > Themes >
+ Theme* e aplique só num dashboard (*Edit dashboard > ... > Theme*). Quando
aprovar, leve para `docker/themes/` e faça deploy.

### Ferramentas do 6.1 que substituem "plugin de gráfico"

Não existe loja de extensões de gráficos para o Superset, e os plugins de terceiros
listados no wiki oficial são de 2021–2023 (React 16 / `@superset-ui/core` 0.17) —
não rodam na 6.x. O framework de *Extensions* (`.supx`) da 6.x também **não**
registra tipos de gráfico (só views, comandos, menus, editores, SQL Lab). O que dá
para usar sem rebuild:

- **Editor de opções ECharts por gráfico** (6.1, aba *Customize > ECharts Options*):
  JSON deep-merged por cima do que o Superset gera. Qualquer opção do ECharts
  (gradiente, rótulo, sombra, `smooth`, etc.).
- **Table V2 com AG Grid** (`AG_GRID_TABLE_ENABLED`, ligado aqui): barras nas
  células, formatação condicional por linha, pin/filtro por coluna, time shift.
- **Big Number período a período** (`CHART_PLUGINS_EXPERIMENTAL`, ligado aqui).
- **Handlebars** + CSS do dashboard para cards de KPI customizados.
- Já vêm na imagem: Sankey, Sunburst, Waterfall, Gantt, Gauge, Radar, Treemap,
  Heatmap, Histogram, Graph, Tree, Bubble, mapas deck.gl (precisa `MAPBOX_API_KEY`).

### Revisão dos gráficos existentes

`scripts/chart_theme_review.py` (roda de uma estação, contra a API) migra o que
estava preso a esquemas antigos: `color_scheme` explícito (`supersetColors`,
`modernSunset`, ...) → `astecha`; escala sequencial explícita → `astechaPurple`;
zera o cache `shared_label_colors` dos dashboards (rótulo → cor sorteada no esquema
antigo); e fixa cor semântica para rótulos de status de qualidade (`OK_*`,
`ATENCAO_*`, `ALERTA_*`, `CRITICO_*`, `SEM_INFORME_*`) na rampa de risco da marca.
Dry-run por padrão; `--apply` grava.

```bash
export SUPERSET_BASE_URL=https://dashboard.astecha.com.br SUPERSET_USERNAME=... SUPERSET_PASSWORD=...
python3 scripts/chart_theme_review.py          # mostra
python3 scripts/chart_theme_review.py --apply  # grava
```

---

## Upgrade de versão

Registro do 6.0.0 → 6.1.0 (03/09/2026), que é o roteiro para os próximos:

1. **Backup primeiro** — `sudo ./scripts/backup-db.sh` (fica em `/home/ubuntu/backups`).
   O `pg_dump -Fc` do metadata DB (~3 MB) é o que importa; o tar do volume
   `superset_home` é opcional (`SKIP_HOME=1`) — é cache do Playwright/thumbnails e
   passa de 1 GB.
2. Ler o [`UPDATING.md`](https://github.com/apache/superset/blob/6.1.0/UPDATING.md)
   da versão. Na 6.1.0 nada quebrou para nós (ClickHouse, GAQ/WebSocket e exemplos
   não se aplicam); adotamos a recomendação `DISTRIBUTED_COORDINATION_CONFIG`.
3. Subir `TAG`/`BROWSER_TAG` em `docker/.env-local` e os defaults no
   `docker-compose.yml` e `docker-browser/Dockerfile` (`ARG SUPERSET_VERSION`).
4. `sudo ./scripts/upgrade-superset.sh 6.1.0` — pull, build do browser, `compose up -d`
   (o `superset-init` roda `superset db upgrade` + `superset init`), espera health,
   imprime `VERSION_STRING` e **recarrega o nginx** — sem isso o site fica em 502,
   porque o nginx guardou o IP do container antigo (armadilha 2).
   Nota: a migração 6.0.0 → 6.1.0 levou ~2 min; o `.env-local` novo faz o compose
   recriar também o `db` (só restart do Postgres, dados no volume).
5. Conferir: login, um dashboard de cada tipo, um Report em dry-run (seção abaixo),
   e *Settings > Themes* mostrando o tema Astecha.
6. Rollback: `TAG`/`BROWSER_TAG` de volta + `pg_restore --clean` do dump (o
   `db upgrade` não é reversível por migração).

Armadilha nova: **`latest` não é uma versão.** Em 31/08/2026 a tag `latest` do
Docker Hub passou de 6.0.0 para 6.1.0; antes deste upgrade o compose usava
`${TAG:-latest}`, e qualquer `docker compose pull` teria migrado o banco sem
ninguém pedir. Agora o default é a versão explícita.

---

## Armadilhas descobertas na prática

Cada uma destas custou tempo de diagnóstico. Estão anotadas aqui para não custarem
de novo.

### 1. `WEBDRIVER_BASEURL` apontando para o domínio público derruba TODOS os alertas

Se o worker acessa o Superset pela URL pública, ele sai para a internet, volta pelo
nginx e passa a **validar TLS**. Quando o certificado vence, todo alerta quebra com
`SSL: CERTIFICATE_VERIFY_FAILED` — inclusive os que não tiram print nenhum, porque o
caminho de CSV/dataframe usa a mesma base. Tem que ser a URL interna da rede docker:

```
SUPERSET_WEBDRIVER_BASEURL=http://superset:8088/
```

O link público que vai no corpo do e-mail é outro setting: `WEBDRIVER_BASEURL_USER_FRIENDLY`.

### 2. O nginx recusa o reload e serve o certificado vencido em silêncio

O `nginx -s reload` re-parseia a config inteira, e o nginx resolve **todos** os
upstreams nesse parse. Um container parado que apareça como `upstream` faz o reload
falhar — e o nginx segue no ar servindo o certificado antigo, sem erro visível.
Pior: um `docker compose restart nginx` nessa situação **falha no boot e derruba o
site**. Por isso `scripts/renew-cert.sh` roda `nginx -t` como gate e confere no fim
o que está sendo servido de fato, via `openssl s_client`.

### 3. `pip` não é o Python do Superset

Na imagem oficial, `pip` no PATH é o do sistema (`/usr/local/bin/pip`), mas o
Superset roda no venv `/app/.venv`. Instalar com `pip` puro coloca o pacote no
interpretador errado e o import só falha em runtime. Use:

```dockerfile
uv pip install --python /app/.venv/bin/python playwright
```

### 4. `PLAYWRIGHT_BROWSERS_PATH` tem que ser caminho de sistema

A imagem base tem `USER superset`, mas o compose roda os serviços como `root`. Se o
browser for para o `$HOME`, um dos dois não o encontra. Daí
`/usr/local/share/playwright-browsers`.

### 5. Screenshot saindo antes dos gráficos carregarem

A sequência de espera do Superset é:

```
goto(wait_until=SCREENSHOT_PLAYWRIGHT_WAIT_EVENT)
  → sleep(SCREENSHOT_SELENIUM_HEADSTART)
  → espera .chart-container
  → espera os .loading sumirem
  → sleep(SCREENSHOT_SELENIUM_ANIMATION_WAIT)
  → print
```

O default do `WAIT_EVENT` é `domcontentloaded`, que dispara assim que o HTML é
parseado — **antes de qualquer query voltar**. Usamos `networkidle`. E note que a
espera dos `.loading` só cobre os elementos existentes *naquele instante*: gráfico
que ainda nem começou a renderizar não tem `.loading`, e ninguém espera por ele —
por isso os dois sleeps fixos.

Teto: `CeleryConfig.task_soft_time_limit` é **180s** para a execução inteira do
report. Não adianta aumentar as esperas sem olhar isso.

### 6. Antes de culpar o tempo, meça

"Gráfico não carregou no print" muitas vezes não é timing. Vale inspecionar o DOM
depois do load — contar `.chart-container`, `.loading` restantes e a altura do
dashboard. No nosso caso, o branco embaixo do print era **área vazia do próprio
dashboard** (1874px de conteúdo num viewport de 2000px, `WEBDRIVER_WINDOW["dashboard"]`),
não gráfico faltando.

---

## Testar um report sem enviar e-mail para os destinatários reais

O dry-run é checado **depois** do screenshot (`commands/report/execute.py`), então
esse caminho exercita o pipeline de imagem por inteiro sem mandar nada a ninguém:

```python
from superset.app import create_app
app_ = create_app()
with app_.app_context():
    from flask import current_app
    current_app.config["ALERT_REPORTS_NOTIFICATION_DRY_RUN"] = True   # trava
    from superset.commands.report.execute import AsyncExecuteReportScheduleCommand
    from datetime import datetime; import uuid
    AsyncExecuteReportScheduleCommand(str(uuid.uuid4()), <REPORT_ID>, datetime.utcnow()).run()
```

Para diagnosticar um alerta que falhou, o metadata DB é Postgres: as tabelas são
`report_schedule` (coluna `last_state`) e `report_execution_log` (`error_message`).

---

## Alertas e reports no Microsoft Teams

Não existe método "Teams" no Superset. O alerta/report usa o método **Webhook**
(`ALERT_REPORT_WEBHOOK` ligado em `superset_config_docker.py`), e
`docker/pythonpath_dev/teams_notification.py` intercepta a entrega: se a URL é de
webhook do Teams (`*.powerplatform.com`, `*.logic.azure.com`, `*.webhook.office.com`),
manda um Adaptive Card; qualquer outra URL segue pelo Webhook padrão do Superset.

1. No canal do Teams: "…" → **Workflows** → **"Send webhook alerts to a channel"**.
   Copiar a URL gerada. O fluxo pertence a quem o cria — se a pessoa sair, para.
2. No alerta/report: adicionar método de notificação **Webhook** (junto do Email)
   e colar a URL.

O card leva título, descrição, a tabela dos alertas em formato TEXT (cortada para
caber no teto de ~28 KB do Teams) e o botão "Abrir no Superset". **Anexos PNG/PDF/CSV
não vão para o Teams** — o card avisa e quem precisa do arquivo segue no e-mail.

A URL do Workflows carrega a assinatura (`sig=`): trate como segredo. Ela fica só
no metadata DB (`report_recipient`); o log do worker registra apenas o host.
Diagnóstico: `docker logs superset-superset-worker-1 | grep 'Teams webhook'`.

---

## Licença

Os arquivos derivados do Apache Superset mantêm a licença Apache 2.0 original.
