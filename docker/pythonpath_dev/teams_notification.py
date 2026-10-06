"""
Entrega de alertas e reports no Microsoft Teams.

O Superset 6.1 so tem Email, Slack e um Webhook generico. O Webhook manda um
JSON proprio ({name, header, text, description, url}), ou multipart quando ha
anexo, e o Teams nao entende nenhum dos dois. Nos alertas em formato TEXT
(ex.: #69/#70 do CDI) ele ainda descarta a tabela: ela vai em
`content.embedded_data`, que o Webhook nao le.

Este modulo mantem o tipo de destinatario "Webhook" (nada muda no banco nem na
UI) e troca so a entrega: quando a URL e de um webhook do Teams (Workflows do
Power Automate), o POST vira um Adaptive Card com titulo, descricao, a tabela
do alerta e um botao "Abrir no Superset". Qualquer outra URL segue pelo
Webhook original do Superset.

Do lado do Teams: no canal, "..." > Workflows > "Send webhook alerts to a
channel" (template padrao, sem editar o fluxo). A URL gerada e o que se cola
no campo Webhook do alerta/report.

Anexos (PNG, PDF, CSV) nao vao para o Teams: o card via Workflows tem teto de
~28 KB e nao aceita arquivo. O card avisa e aponta para o Superset; quem
precisa do anexo continua recebendo por e-mail no mesmo alerta.

Instalado por FLASK_APP_MUTATOR em superset_config_docker.py.

Cockpit (DEV-1821): uma URL `https://cockpit.astecha.com.br/api/interno/eventos/superset`
no destinatario Webhook vira um evento JSON para o Astecha Cockpit, que abre
(ou comenta) o ticket de suporte pelas regras da tela Suporte > Configuracao >
Integracoes. O token vai no header, lido de COCKPIT_EVENTOS_TOKEN (docker/.env
do servidor): a URL salva no alerta nao tem segredo nenhum.
"""

import os

import json
import logging
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Hosts das URLs de webhook do Teams. Workflows do Power Automate:
# *.environment.api.powerplatform.com (URLs novas) e *.logic.azure.com (antigas).
# *.webhook.office.com e o conector O365 legado, ainda aceito se existir.
TEAMS_HOST_SUFFIXES = (
    ".powerplatform.com",
    ".logic.azure.com",
    ".webhook.office.com",
)

# O Teams recusa card acima de ~28 KB. Folga para o envelope da mensagem.
MAX_CARD_BYTES = 24_000
MAX_TABLE_ROWS = 30
MAX_TABLE_COLS = 8
MAX_CELL_CHARS = 60
MAX_TEXT_CHARS = 2_000


COCKPIT_EVENTOS_PATH = "/api/interno/eventos/"
MAX_COCKPIT_ROWS = 20


def is_cockpit_url(url: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return (host == "cockpit.astecha.com.br" or host.startswith("cockpit.")) and p.path.startswith(
        COCKPIT_EVENTOS_PATH
    )


def _https(url: Optional[str]) -> Optional[str]:
    if url and url.lower().startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def build_cockpit_payload(
    report_id: Optional[int],
    name: str,
    header: dict,
    url: Optional[str],
    description: Optional[str],
    embedded_data: Any = None,
) -> dict:
    """O evento que o Cockpit espera (cockpit.suporte.integracoes.normalizar)."""
    linhas: list = []
    if embedded_data is not None:
        try:
            df = embedded_data.head(MAX_COCKPIT_ROWS)
            linhas = [{str(k): _cell(v) for k, v in r.items()} for r in df.to_dict(orient="records")]
        except Exception:  # noqa: BLE001 - tabela e enfeite; o evento sai sem ela
            logger.warning("Cockpit: nao consegui ler a tabela do alerta %s", report_id)
    return {
        "report_id": report_id,
        "nome": name,
        "tipo": header.get("notification_type") or "",
        "descricao": description or "",
        "url": _https(url),
        "execution_id": str(header.get("execution_id") or ""),
        "owners": [str(o) for o in (header.get("owners") or [])],
        "linhas": linhas,
    }


def is_teams_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(TEAMS_HOST_SUFFIXES)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value)
    if len(text) > MAX_CELL_CHARS:
        text = text[: MAX_CELL_CHARS - 1] + "…"
    return text


def _table_element(df: Any, max_rows: int) -> list[dict[str, Any]]:
    cols = list(df.columns)[:MAX_TABLE_COLS]
    shown = df.head(max_rows)

    def row(values: list[Any], header: bool = False) -> dict[str, Any]:
        return {
            "type": "TableRow",
            "cells": [
                {
                    "type": "TableCell",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": _cell(v),
                            "wrap": True,
                            "weight": "Bolder" if header else "Default",
                        }
                    ],
                }
                for v in values
            ],
        }

    elements: list[dict[str, Any]] = [
        {
            "type": "Table",
            "gridStyle": "accent",
            "firstRowAsHeader": True,
            "columns": [{"width": 1} for _ in cols],
            "rows": [row(cols, header=True)]
            + [row([r[c] for c in cols]) for _, r in shown.iterrows()],
        }
    ]

    omitted = []
    if len(df) > len(shown):
        omitted.append(f"{len(df) - len(shown)} de {len(df)} linhas")
    if len(df.columns) > len(cols):
        omitted.append(f"{len(df.columns) - len(cols)} colunas")
    if omitted:
        elements.append(
            {
                "type": "TextBlock",
                "text": f"Tabela cortada ({', '.join(omitted)} fora). "
                "Veja completa no Superset.",
                "isSubtle": True,
                "size": "Small",
                "wrap": True,
            }
        )
    return elements


def build_teams_message(
    name: str,
    header: dict[str, Any],
    url: Optional[str] = None,
    description: Optional[str] = None,
    text: Optional[str] = None,
    embedded_data: Any = None,
    attachments: Optional[list[str]] = None,
    max_rows: int = MAX_TABLE_ROWS,
) -> dict[str, Any]:
    """Monta a mensagem no formato que o webhook do Workflows espera."""
    kind = header.get("notification_type") or "Notificação"
    is_alert = kind == "Alert"

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": ("🔔 Alerta" if is_alert else "📊 Relatório") + " · Superset",
            "isSubtle": True,
            "size": "Small",
            "color": "Attention" if is_alert else "Default",
        },
        {
            "type": "TextBlock",
            "text": name,
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        },
    ]
    if description:
        body.append({"type": "TextBlock", "text": description, "wrap": True})
    if text:
        if len(text) > MAX_TEXT_CHARS:
            text = text[: MAX_TEXT_CHARS - 1] + "…"
        body.append({"type": "TextBlock", "text": text, "wrap": True})
    if embedded_data is not None and len(embedded_data.columns) > 0:
        if len(embedded_data) == 0:
            body.append(
                {"type": "TextBlock", "text": "_Consulta sem linhas._", "wrap": True}
            )
        else:
            body.extend(_table_element(embedded_data, max_rows))
    if attachments:
        body.append(
            {
                "type": "TextBlock",
                "text": f"Anexo ({', '.join(attachments)}) disponível no e-mail "
                "do relatório ou no Superset.",
                "isSubtle": True,
                "size": "Small",
                "wrap": True,
            }
        )

    card: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "msteams": {"width": "Full"},
        "body": body,
    }
    if url:
        # O Workflow aceita (202) mas nunca posta card com link http://.
        if url.lower().startswith("http://"):
            url = "https://" + url[len("http://") :]
        card["actions"] = [
            {"type": "Action.OpenUrl", "title": "Abrir no Superset", "url": url}
        ]

    message = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }

    # Tabela larga estoura o teto do Teams: corta linhas ate caber.
    size = len(json.dumps(message, ensure_ascii=False).encode())
    if size > MAX_CARD_BYTES and embedded_data is not None and max_rows > 1:
        return build_teams_message(
            name,
            header,
            url,
            description,
            text,
            embedded_data,
            attachments,
            max_rows=max(1, max_rows // 2),
        )
    return message


def install() -> None:
    """Registra a entrega do Teams na frente do Webhook original."""
    import backoff
    import requests
    from flask import current_app

    from superset import feature_flag_manager
    from superset.reports.notifications.base import BaseNotification
    from superset.reports.notifications.exceptions import (
        NotificationParamException,
        NotificationUnprocessableException,
    )
    from superset.reports.notifications.webhook import WebhookNotification

    if any(p.__name__ == "TeamsAwareWebhookNotification" for p in BaseNotification.plugins):
        return

    class TeamsAwareWebhookNotification(WebhookNotification):
        def send(self) -> None:
            wh_url = self._get_webhook_url()
            if is_cockpit_url(wh_url):
                return self._send_cockpit(wh_url)
            if not is_teams_url(wh_url):
                return super().send()
            self._send_teams(wh_url)

        @backoff.on_exception(
            backoff.expo,
            NotificationUnprocessableException,
            factor=10,
            base=2,
            max_tries=3,
        )
        def _send_cockpit(self, wh_url: str) -> None:
            token = os.environ.get("COCKPIT_EVENTOS_TOKEN", "")
            if not token:
                raise NotificationParamException(
                    "Cockpit: COCKPIT_EVENTOS_TOKEN nao configurado no docker/.env."
                )
            c = self._content
            payload = build_cockpit_payload(
                report_id=getattr(self._recipient, "report_schedule_id", None),
                name=c.name,
                header=dict(c.header_data or {}),
                url=c.url,
                description=c.description,
                embedded_data=c.embedded_data,
            )
            try:
                response = requests.post(
                    wh_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=20,
                )
            except requests.exceptions.RequestException as ex:
                raise NotificationUnprocessableException(str(ex)) from ex
            logger.info("Cockpit: evento do alerta %s, status %s", payload["report_id"], response.status_code)
            if response.status_code >= 500 or response.status_code == 429:
                raise NotificationUnprocessableException(
                    f"Cockpit falhou ({response.status_code}): {response.text[:300]}"
                )
            if response.status_code >= 400:
                raise NotificationParamException(
                    f"Cockpit recusou ({response.status_code}): {response.text[:300]}"
                )

        @backoff.on_exception(
            backoff.expo,
            NotificationUnprocessableException,
            factor=10,
            base=2,
            max_tries=5,
        )
        def _send_teams(self, wh_url: str) -> None:
            if not feature_flag_manager.is_feature_enabled("ALERT_REPORT_WEBHOOK"):
                raise NotificationUnprocessableException(
                    "Webhook notification sent with ALERT_REPORT_WEBHOOK disabled."
                )
            if (
                current_app.config["ALERT_REPORTS_WEBHOOK_HTTPS_ONLY"]
                and urlparse(wh_url).scheme.lower() != "https"
            ):
                raise NotificationParamException(
                    "Webhook failed: HTTPS is required by config for webhook URLs."
                )

            c = self._content
            attachments = []
            if c.screenshots:
                attachments.append("PNG")
            if c.pdf:
                attachments.append("PDF")
            if c.csv:
                attachments.append("CSV")
            message = build_teams_message(
                name=c.name,
                header=dict(c.header_data or {}),
                url=c.url,
                description=c.description,
                text=c.text,
                embedded_data=c.embedded_data,
                attachments=attachments,
            )

            try:
                response = requests.post(wh_url, json=message, timeout=60)
            except requests.exceptions.RequestException as ex:
                raise NotificationUnprocessableException(str(ex)) from ex

            # O host do Workflows fica no log; a URL inteira nao (tem a assinatura).
            logger.info(
                "Teams webhook sent to %s, status code: %s",
                urlparse(wh_url).hostname,
                response.status_code,
            )
            if response.status_code >= 500 or response.status_code == 429:
                raise NotificationUnprocessableException(
                    f"Teams webhook failed ({response.status_code}): {response.text}"
                )
            if response.status_code >= 400:
                raise NotificationParamException(
                    f"Teams webhook failed ({response.status_code}): {response.text}"
                )

    # __init_subclass__ ja anexou no fim; create_notification pega o primeiro
    # plugin com o mesmo tipo, entao a subclasse precisa vir antes do original.
    BaseNotification.plugins.remove(TeamsAwareWebhookNotification)
    BaseNotification.plugins.insert(0, TeamsAwareWebhookNotification)
    logger.info("Teams-aware webhook notification installed")
