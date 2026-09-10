# syntax=docker/dockerfile:1
#
# Imagem do Superset com headless browser para Alerts & Reports (prints de gráficos).
#
# A imagem oficial `apache/superset` é o flavor "lean": não traz browser nenhum.
# Sem isso, todo Report que manda screenshot morre com
#   "Failed taking a screenshot ... chromedriver unexpectedly exited. Status code was: 127"
# (127 = biblioteca compartilhada faltando — libglib/libnss/libxcb/libdbus).
#
# Aqui usamos Playwright + Chromium, que é a abordagem recomendada pelo projeto
# desde a 4.1.x e o que o próprio Dockerfile oficial faz via --build-arg
# INCLUDE_CHROMIUM=true. Playwright baixa um Chromium autocontido e o
# `install-deps` instala as libs de sistema que faltavam.
#
# Pareado com FEATURE_FLAGS["PLAYWRIGHT_REPORTS_AND_THUMBNAILS"] = True em
# docker/pythonpath_dev/superset_config_docker.py. Com Playwright ativo o
# WEBDRIVER_TYPE deixa de ter efeito (Playwright é sempre Chromium).
#
# Build:
#   docker compose --profile browser build superset-worker
# ou:
#   docker build --build-arg SUPERSET_VERSION=6.1.0 -t astecha/superset-browser:6.1.0 docker-browser/
#
# A versão aqui tem que ser a MESMA do TAG do docker-compose.yml / .env-local.
ARG SUPERSET_VERSION=6.1.0
FROM apache/superset:${SUPERSET_VERSION}

USER root

# Browsers fora do $HOME: o compose roda os serviços como root, mas a imagem base
# tem USER superset. Um caminho de sistema funciona para os dois — senão o
# Playwright procuraria em ~/.cache/ms-playwright do usuário errado.
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright-browsers

# `pip` no PATH é o do sistema (/usr/local/bin/pip), mas o Superset roda no venv
# /app/.venv. Instalar com pip puro colocaria o pacote no interpretador errado e
# o import falharia em runtime — daí o --python explícito.
# Pinado para o build ser reproduzível: o Chromium é baixado pela CLI do
# Playwright, então a versão do pacote determina a versão do browser
# (1.62.0 -> Chromium 151.0.7922.34, validado nesta imagem).
ARG PLAYWRIGHT_VERSION="1.62.0"
RUN set -eux; \
    uv pip install --python /app/.venv/bin/python --no-cache \
        "playwright${PLAYWRIGHT_VERSION:+==${PLAYWRIGHT_VERSION}}"; \
    playwright install-deps chromium; \
    playwright install chromium; \
    chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /root/.cache/*; \
    /app/.venv/bin/python -c "import playwright; print('playwright ok')"

# Backport do fix upstream apache/superset#41051 (commit a529945d3b, issue
# #40996) — "commit permalink before Playwright navigation". Não está na 6.1.0.
#
# Report de dashboard com `extra.dashboard` (ALERT_REPORT_TABS) tira o print de
# um permalink. O worker cria a linha em key_value dentro da transação externa
# do report, só com flush — o @transaction do CreateDashboardPermalinkCommand
# vê g.in_transaction e não comita. O Chromium abre o permalink pelo container
# web (outra conexão), não enxerga a linha, recebe 404 "permalink state not
# found" e o report morre em `waiting for locator(".standalone")` depois de
# SCREENSHOT_PLAYWRIGHT_DEFAULT_TIMEOUT. Só acontece na PRIMEIRA execução de
# cada estado (report novo, ou abas/filtros alterados): nas seguintes a chave
# determinística acha a linha já comitada. Foi o que derrubou o 66 (03/09), o
# 67 (04/09) e o 65 (09/09).
#
# O patch comita logo depois de criar o permalink, igual ao upstream. Se a
# imagem base já trouxer o fix, pula; se o trecho mudou, o build FALHA de
# propósito — revisar antes de subir de versão.
RUN /app/.venv/bin/python - <<'PY'
import pathlib
p = pathlib.Path("/app/superset/commands/report/execute.py")
src = p.read_text()
start = src.index("    def _get_tab_url(")
end = src.index("\n    def ", start + 1)
if "db.session.commit()" in src[start:end]:
    print("execute.py já comita o permalink em _get_tab_url; patch pulado")
else:
    old = (
        "        permalink_key = CreateDashboardPermalinkCommand(\n"
        "            dashboard_id=str(self._report_schedule.dashboard.uuid),\n"
        "            state=dashboard_state,\n"
        "        ).run()\n"
    )
    assert src.count(old) == 1, "trecho de _get_tab_url mudou: revisar o backport do #40996"
    new = old + "        db.session.commit()  # backport apache/superset#41051\n"
    p.write_text(src.replace(old, new))
    print("execute.py: backport do #41051 aplicado")
PY

USER superset
