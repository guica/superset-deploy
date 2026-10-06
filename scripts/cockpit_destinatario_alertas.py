#!/usr/bin/env python3
"""Acrescenta o destinatário Cockpit (Webhook) em todos os alertas do Superset.

DEV-1821: todo alerta (type=Alert) passa a mandar o evento para o Cockpit, que
decide pelas regras da tela se abre ticket. E-mail e Teams continuam: o PUT do
`/report/{id}` SUBSTITUI a lista de destinatários, então ela vai completa.

Simula por padrão; `--aplicar` grava. Idempotente (pula quem já tem).

Em prod o login é AUTH_OAUTH (Entra): o `/security/login` com provider=db dá 401.
Lá o caminho é rodar DENTRO do container, pelo ORM (sem SUPERSET_BASE_URL no
ambiente o script vai por esse modo):

    docker exec -i superset-superset-1 python - [--aplicar] [--remover] \
        < scripts/cockpit_destinatario_alertas.py

Contra um Superset com login de banco (local), pela API REST:

    SUPERSET_BASE_URL=... SUPERSET_USERNAME=... SUPERSET_PASSWORD=... \
        python scripts/cockpit_destinatario_alertas.py [--aplicar] [--remover]
"""

import argparse
import json
import os
import sys

URL_COCKPIT = "https://cockpit.astecha.com.br/api/interno/eventos/superset"


def sessao():
    import requests

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


def via_orm(a: argparse.Namespace) -> int:
    """Dentro do container: mexe direto em report_recipient pelo ORM."""
    from superset.app import create_app

    with create_app().app_context():
        from superset.extensions import db
        from superset.reports.models import ReportRecipients, ReportSchedule

        alertas = db.session.query(ReportSchedule).filter(ReportSchedule.type == "Alert").all()
        mudou = 0
        for al in alertas:
            recs = list(al.recipients)
            meus = [
                r for r in recs
                if eh_cockpit({"type": r.type, "recipient_config_json": r.recipient_config_json})
            ]
            if a.remover:
                if not meus:
                    continue
                if a.aplicar:
                    for r in meus:
                        db.session.delete(r)
                novos = len(recs) - len(meus)
            else:
                if meus:
                    continue
                if a.aplicar:
                    db.session.add(
                        ReportRecipients(
                            type="Webhook",
                            recipient_config_json=json.dumps({"target": URL_COCKPIT}),
                            report_schedule=al,
                        )
                    )
                novos = len(recs) + 1
            mudou += 1
            acao = "tirar" if a.remover else "pôr"
            print(f"#{al.id:>4} {acao} Cockpit · {al.name} ({len(recs)} → {novos} destinatários)")
        if a.aplicar:
            db.session.commit()
        print(f"{len(alertas)} alertas, {mudou} {'alterados' if a.aplicar else 'a alterar (simulação)'}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="grava (sem isto, só mostra)")
    ap.add_argument("--remover", action="store_true", help="tira o destinatário Cockpit")
    a = ap.parse_args()
    if not os.environ.get("SUPERSET_BASE_URL"):
        return via_orm(a)
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
