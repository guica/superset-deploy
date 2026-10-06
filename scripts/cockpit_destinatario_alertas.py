#!/usr/bin/env python3
"""Acrescenta o destinatário Cockpit (Webhook) em todos os alertas do Superset.

DEV-1821: todo alerta (type=Alert) passa a mandar o evento para o Cockpit, que
decide pelas regras da tela se abre ticket. E-mail e Teams continuam: o PUT do
`/report/{id}` SUBSTITUI a lista de destinatários, então ela vai completa.

Simula por padrão; `--aplicar` grava. Idempotente (pula quem já tem).

    SUPERSET_BASE_URL=... SUPERSET_USERNAME=... SUPERSET_PASSWORD=... \
        python scripts/cockpit_destinatario_alertas.py [--aplicar] [--remover]
"""

import argparse
import json
import os
import sys

import requests

URL_COCKPIT = "https://cockpit.astecha.com.br/api/interno/eventos/superset"


def sessao() -> tuple[requests.Session, str]:
    base = os.environ["SUPERSET_BASE_URL"].rstrip("/")
    s = requests.Session()
    r = s.post(
        f"{base}/api/v1/security/login",
        json={
            "username": os.environ["SUPERSET_USERNAME"],
            "password": os.environ["SUPERSET_PASSWORD"],
            "provider": "db",
            "refresh": False,
        },
        timeout=30,
    )
    r.raise_for_status()
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    csrf = s.get(f"{base}/api/v1/security/csrf_token/", timeout=30)
    csrf.raise_for_status()
    s.headers["X-CSRFToken"] = csrf.json()["result"]
    s.headers["Referer"] = base
    return s, base


def eh_cockpit(rec: dict) -> bool:
    cfg = rec.get("recipient_config_json") or {}
    if isinstance(cfg, str):
        cfg = json.loads(cfg or "{}")
    return rec.get("type") == "Webhook" and cfg.get("target") == URL_COCKPIT


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="grava (sem isto, só mostra)")
    ap.add_argument("--remover", action="store_true", help="tira o destinatário Cockpit")
    a = ap.parse_args()
    s, base = sessao()
    q = json.dumps({"filters": [{"col": "type", "opr": "eq", "value": "Alert"}], "page_size": 500})
    alertas = s.get(f"{base}/api/v1/report/", params={"q": q}, timeout=60).json()["result"]
    mudou = 0
    for al in alertas:
        det = s.get(f"{base}/api/v1/report/{al['id']}", timeout=60).json()["result"]
        recs = [
            {"type": r["type"], "recipient_config_json": r["recipient_config_json"]}
            for r in det.get("recipients", [])
        ]
        tem = any(eh_cockpit(r) for r in recs)
        if a.remover:
            if not tem:
                continue
            novos = [r for r in recs if not eh_cockpit(r)]
        else:
            if tem:
                continue
            novos = recs + [{"type": "Webhook", "recipient_config_json": {"target": URL_COCKPIT}}]
        mudou += 1
        acao = "tirar" if a.remover else "pôr"
        print(f"#{al['id']:>4} {acao} Cockpit · {det['name']} ({len(recs)} → {len(novos)} destinatários)")
        if a.aplicar:
            r = s.put(f"{base}/api/v1/report/{al['id']}", json={"recipients": novos}, timeout=60)
            if r.status_code >= 400:
                print(f"      ERRO {r.status_code}: {r.text[:300]}", file=sys.stderr)
                return 1
    print(f"{len(alertas)} alertas, {mudou} {'alterados' if a.aplicar else 'a alterar (simulação)'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
