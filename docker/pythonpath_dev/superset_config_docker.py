# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Superset Docker Configuration - Production
This file overrides settings from superset_config.py for production deployment
"""

import os

# =========================================================================
# ALERTS AND REPORTS CONFIGURATION
# =========================================================================

# Enable Alerts and Reports feature
FEATURE_FLAGS = {
    "ALERT_REPORTS": True,
    # Playwright + Chromium vêm na imagem astecha/superset-browser
    # (ver docker-browser/Dockerfile), usada pelo serviço superset-worker.
    # Com a flag ligada, WEBDRIVER_TYPE abaixo deixa de ter efeito:
    # Playwright é sempre Chromium.
    "PLAYWRIGHT_REPORTS_AND_THUMBNAILS": True,
    # ---- Gráficos (6.x) ----
    # Table V2 com AG Grid: barras nas células, formatação condicional por linha,
    # pin/filtro por coluna, time shift. Vem na imagem, mas desligada por padrão.
    "AG_GRID_TABLE_ENABLED": True,
    # Libera os plugins experimentais (hoje: Big Number período a período).
    "CHART_PLUGINS_EXPERIMENTAL": True,
    # Report de dashboard respeitando o estado salvo em `extra.dashboard`
    # (abas e filtros nativos). Sem isto o worker ignora `nativeFilters` e manda
    # o dashboard sem filtro — o report "uso-humano" depende disto
    # (Período = Last month, Origem = prod, Tipo de usuário = Cliente).
    "ALERT_REPORT_TABS": True,
}

# ⚠️ IMPORTANTE: Desabilitar dry-run mode para enviar emails reais
ALERT_REPORTS_NOTIFICATION_DRY_RUN = False

# =========================================================================
# SENDGRID / SMTP CONFIGURATION
# =========================================================================

# SendGrid SMTP Configuration (porta 465 com SSL)
SMTP_HOST = os.getenv("MAIL_SERVER", "smtp.sendgrid.net")
SMTP_PORT = int(os.getenv("MAIL_PORT", "465"))
SMTP_USER = os.getenv("MAIL_USERNAME", "apikey")
SMTP_PASSWORD = os.getenv("MAIL_PASSWORD", "")
SMTP_MAIL_FROM = os.getenv("MAIL_DEFAULT_SENDER", "noreply@dashboard.astecha.com.br")

# Configurações SSL para porta 465
SMTP_SSL = True  # SSL direto na porta 465
SMTP_STARTTLS = False  # Não usar STARTTLS quando SSL está ativo
SMTP_SSL_SERVER_AUTH = True  # Verificar certificado do servidor

# Prefixo opcional no assunto dos emails
EMAIL_REPORTS_SUBJECT_PREFIX = "[Astecha Dashboard] "

# =========================================================================
# WEBDRIVER CONFIGURATION
# =========================================================================

# URL base interna (para o worker acessar o Superset)
# Usar o nome do serviço Docker
WEBDRIVER_BASEURL = os.getenv(
    "SUPERSET_WEBDRIVER_BASEURL",
    "http://superset:8088/"
)

# URL base amigável (link que vai no email)
# Usar o domínio público
WEBDRIVER_BASEURL_USER_FRIENDLY = os.getenv(
    "WEBDRIVER_BASEURL_USER_FRIENDLY",
    "http://dashboard.astecha.com.br/"
)

# Ignorado enquanto PLAYWRIGHT_REPORTS_AND_THUMBNAILS estiver True.
# Mantido só como fallback caso a flag seja desligada.
WEBDRIVER_TYPE = os.getenv("WEBDRIVER_TYPE", "chrome")

# Argumentos do Chrome para headless mode
WEBDRIVER_OPTION_ARGS = [
    "--force-device-scale-factor=2.0",
    "--high-dpi-support=2.0",
    "--headless",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-extensions",
]

# Tempos de espera para screenshots
SCREENSHOT_LOCATE_WAIT = 100
SCREENSHOT_LOAD_WAIT = 600

# -------------------------------------------------------------------------
# Espera do Playwright: garantir que os graficos terminem de carregar dados
# antes do print. A sequencia em utils/webdriver.py e:
#   goto(wait_until=WAIT_EVENT) -> sleep(HEADSTART) -> espera .chart-container
#   -> espera os .loading sumirem -> sleep(ANIMATION_WAIT) -> screenshot
#
# O default "domcontentloaded" dispara assim que o HTML e parseado, ou seja
# ANTES de qualquer query voltar. "networkidle" espera a rede silenciar, que e
# o proxy pratico para "as consultas dos graficos terminaram".
SCREENSHOT_PLAYWRIGHT_WAIT_EVENT = "networkidle"

# Teto de cada espera individual do Playwright. Se a rede nunca silenciar, o
# goto estoura esse timeout, e logado e o fluxo segue assim mesmo (nao perde o
# print) — MAS a espera seguinte, `element.wait_for()` do seletor .standalone,
# estoura de verdade e derruba o report ("Failed taking a screenshot").
#
# Subido de 60s para 150s em 03/09/2026 achando que o uso-humano era lento. A
# falha era outra: na 1a execucao de cada estado de permalink (report com
# extra.dashboard + ALERT_REPORT_TABS) o worker ainda nao tinha comitado o
# permalink, o web respondia 404 e o .standalone nunca aparecia — com qualquer
# timeout. Corrigido na imagem do worker (docker-browser/Dockerfile, backport
# do apache/superset#41051). Os 150s ficam como folga: com force_screenshot as
# queries do CUSTOMER_DB chegaram a 40-46s logo apos o boot da EC2 (09-10/09).
#
# Nao conflita com o limite do Celery: para reports AGENDADOS o scheduler
# (tasks/scheduler.py) define soft_time_limit = working_timeout + 1 = 3601s por
# task, ignorando o global de 180s. O global so vale para chamada manual da
# task, e a de thumbnail tem soft_time_limit=300s fixo — 150s cabe nos dois.
SCREENSHOT_PLAYWRIGHT_DEFAULT_TIMEOUT = 150000

# A espera dos .loading so cobre os elementos existentes NAQUELE instante:
# grafico que ainda nao comecou a renderizar (lazy-load abaixo da dobra) nao
# tem .loading e por isso ninguem espera por ele. Esses dois sleeps fixos sao a
# folga que cobre esse buraco.
SCREENSHOT_SELENIUM_HEADSTART = 10
SCREENSHOT_SELENIUM_ANIMATION_WAIT = 10


# =========================================================================
# EXECUTORS CONFIGURATION
# =========================================================================

# Por padrão, alertas são executados como o dono do alert/report
# Se quiser usar um usuário fixo, descomente e configure:
# from superset.tasks.types import FixedExecutor
# ALERT_REPORTS_EXECUTORS = [FixedExecutor("admin")]

# =========================================================================
# ADDITIONAL FEATURES
# =========================================================================

# Permitir formatação de data no assunto do email (opcional)
# FEATURE_FLAGS["DATE_FORMAT_IN_EMAIL_SUBJECT"] = True

# Lista de métodos de notificação disponíveis
ALERT_REPORTS_NOTIFICATION_METHODS = ["Email"]

# Se quiser adicionar Slack no futuro, adicione suas configs aqui:
# SLACK_API_TOKEN = os.getenv("SLACK_API_TOKEN", "")
# FEATURE_FLAGS["ALERT_REPORT_SLACK_V2"] = True
# ALERT_REPORTS_NOTIFICATION_METHODS.append("Slack")

# =========================================================================
# BRANDING, TEMA E PALETAS (Superset 6.x)
# =========================================================================
# O tema fica em JSON versionado (docker/themes/*.json) e é carregado aqui para
# que o config continue sendo a única fonte da verdade. Na subida do app o
# Superset faz upsert desses dois temas como "THEME_DEFAULT"/"THEME_DARK"
# (is_system=True) na tabela `themes` — ver superset/commands/theme/seed.py.
# Enquanto nenhum tema for marcado como "system default" na UI
# (Settings > Themes), o que vale é o do config.
#
# Logos e demais assets estáticos: docker/assets/ é montado em
# /app/superset/static/assets/astecha (ver docker-compose.yml), logo o caminho
# público é /static/assets/astecha/<arquivo>.
#
# Fontes: o CSP do Superset (TALISMAN_CONFIG) só libera fonts.googleapis.com,
# fonts.gstatic.com e use.typekit.*; por isso Fira Sans/Fira Code vêm do Google
# Fonts em vez de self-hosted (THEME_FONT_URL_ALLOWED_DOMAINS).

import json as _json
from pathlib import Path as _Path

_THEMES_DIR = _Path(__file__).resolve().parent.parent / "themes"  # /app/docker/themes


def _load_theme(filename: str) -> dict:
    return _json.loads((_THEMES_DIR / filename).read_text(encoding="utf-8"))


APP_NAME = "Astecha Dashboard"
APP_ICON = "/static/assets/astecha/astecha-logo-light.png"

THEME_DEFAULT = _load_theme("astecha-light.json")
THEME_DARK = _load_theme("astecha-dark.json")

# Paleta categórica = a mesma ASTECHA_PALETTE usada nos gráficos do home-app
# (frontend/src/lib/echarts.js), para os dashboards do Superset e do app
# lerem como um produto só. isDefault=True faz dela o esquema padrão de todo
# gráfico novo e de todo gráfico que não fixou esquema.
EXTRA_CATEGORICAL_COLOR_SCHEMES = [
    {
        "id": "astecha",
        "label": "Astecha",
        "description": "Paleta categórica institucional (mesma do home-app)",
        "isDefault": True,
        "colors": [
            "#0D0D38",  # azul quase preto — âncora
            "#001EAF",  # azul profundo
            "#2044DC",  # azul
            "#4571FF",  # azul claro
            "#88AAFF",  # azul pastel
            "#FF6B06",  # laranja
            "#FFBB8D",  # laranja pastel
            "#F8485E",  # vermelho
            "#FF99AF",  # rosa
            "#46E8E0",  # turquesa
            "#B6FFE3",  # verde água
            "#A6A6A6",  # cinza
            "#118680",  # verde petróleo
            "#DBDBF7",  # lilás claro
            "#C65000",  # laranja queimado
        ],
    },
]

# Escalas sequenciais/divergentes derivadas da escala de roxo/vermelho da marca
# (astecha.css --purple-* / --red-*) e da rampa de risco (--risk-0..5).
EXTRA_SEQUENTIAL_COLOR_SCHEMES = [
    {
        "id": "astechaPurple",
        "label": "Astecha — roxo",
        "description": "Sequencial claro→escuro na escala de roxo da marca",
        "isDiverging": False,
        "isDefault": True,
        "colors": [
            "#EFEAFB", "#D4C6F4", "#AD95E8", "#8463DB", "#5A33CC",
            "#3B0FAA", "#270173", "#1F015C", "#170144",
        ],
    },
    {
        "id": "astechaRedPurple",
        "label": "Astecha — vermelho ↔ roxo",
        "description": "Divergente: vermelho da marca ↔ roxo da marca",
        "isDiverging": True,
        "isDefault": False,
        "colors": [
            "#A91718", "#D21D1E", "#F64A4B", "#FBA3A4", "#FEECEC",
            "#EFEAFB", "#AD95E8", "#5A33CC", "#270173",
        ],
    },
    {
        "id": "astechaRisk",
        "label": "Astecha — risco (ok → crítico)",
        "description": "Rampa de severidade sóbria: sálvia → âmbar → tijolo → marrom",
        "isDiverging": False,
        "isDefault": False,
        "colors": ["#4E7A63", "#B08A4A", "#A8703E", "#A85D4A", "#8A4438", "#6E3530"],
    },
]

# =========================================================================
# COORDENAÇÃO DISTRIBUÍDA (novo na 6.1 — Global Task Framework)
# =========================================================================
# Backend Redis unificado para locks e pub/sub entre workers. O UPDATING.md da
# 6.1.0 recomenda configurar em toda instalação de produção com Redis. Reusa o
# mesmo Redis/DB do CACHE_CONFIG do upstream (docker/pythonpath_dev/superset_config.py).
DISTRIBUTED_COORDINATION_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_KEY_PREFIX": "signal_",
    "CACHE_REDIS_URL": (
        f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}/"
        f"{os.getenv('REDIS_RESULTS_DB', '1')}"
    ),
    "CACHE_DEFAULT_TIMEOUT": 300,
}

# =========================================================================
# LOGGING
# =========================================================================

# Aumentar log level se precisar debugar
# import logging
# LOG_LEVEL = logging.DEBUG
