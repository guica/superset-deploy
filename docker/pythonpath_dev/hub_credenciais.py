"""Chave Snowflake do Hub de credenciais na hora de conectar (DEV-2098, D134 do Cockpit).

Só age na conexão que pede: em "Edit database → Advanced → Other → Engine
parameters", `{"connect_args": {"hub_segredo": "astecha/prod/ast/superset/svc_superset_prod"}}`.
Sem `hub_segredo`, a conexão segue exatamente como antes (senha/chave da tela).

- A credencial AWS é a da EC2 (role compartilhada); daqui se assume
  `astecha-credenciais-prod-superset`, que só esta instância pode assumir
  (`ec2:SourceInstanceARN` na confiança) e que só lê segredo com
  `consumidor=superset`.
- A chave nunca vai para o Postgres de metadados: fica em memória, por processo.
- Rotação (R2 do spike DEV-2090): a chave antiga morre na hora. A cada 60 s o
  mutator confere a versão AWSCURRENT (DescribeSecret, sem valor) e, se mudou,
  busca a nova. O pior caso é ~60 s de "JWT token is invalid" logo depois de
  uma rotação; a agenda da rotação é de 30 em 30 dias.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

ROLE_ARN = os.getenv(
    "HUB_SUPERSET_ROLE_ARN", "arn:aws:iam::311141545519:role/astecha-credenciais-prod-superset"
)
REGIAO = os.getenv("HUB_REGIAO", "us-east-2")
CONFERE_VERSAO_S = int(os.getenv("HUB_CONFERE_VERSAO_S", "60"))

_trava = threading.Lock()
_cliente: dict = {}  # {"sm": client, "expira": epoch}
_cache: dict[str, dict] = {}  # segredo → {"versao", "conferido", "user", "der"}


def _sm():
    import boto3

    agora = time.time()
    if _cliente.get("expira", 0) > agora + 300:
        return _cliente["sm"]
    cred = boto3.client("sts", region_name=REGIAO).assume_role(
        RoleArn=ROLE_ARN, RoleSessionName="superset-hub", DurationSeconds=3600
    )["Credentials"]
    _cliente["sm"] = boto3.client(
        "secretsmanager", region_name=REGIAO,
        aws_access_key_id=cred["AccessKeyId"], aws_secret_access_key=cred["SecretAccessKey"],
        aws_session_token=cred["SessionToken"],
    )
    _cliente["expira"] = cred["Expiration"].timestamp()
    return _cliente["sm"]


def _der(pem: str) -> bytes:
    from cryptography.hazmat.primitives import serialization

    chave = serialization.load_pem_private_key(pem.encode(), password=None)
    return chave.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _versao_atual(sm, segredo: str) -> str | None:
    estagios = sm.describe_secret(SecretId=segredo).get("VersionIdsToStages") or {}
    return next((v for v, e in estagios.items() if "AWSCURRENT" in e), None)


def credencial(segredo: str) -> dict:
    """{"user", "der"} do segredo, com cache por versão."""
    with _trava:
        agora = time.time()
        item = _cache.get(segredo)
        sm = _sm()
        if item and agora - item["conferido"] < CONFERE_VERSAO_S:
            return item
        if item and _versao_atual(sm, segredo) == item["versao"]:
            item["conferido"] = agora
            return item
        r = sm.get_secret_value(SecretId=segredo)
        valor = json.loads(r["SecretString"])
        item = {"versao": r["VersionId"], "conferido": agora, "user": valor["user"], "der": _der(valor["privateKey"])}
        _cache[segredo] = item
        log.info("hub_credenciais: %s na versão %s", segredo, r["VersionId"])
        return item


def mutator(uri, params, username, security_manager, source):  # noqa: ARG001
    connect_args = (params or {}).get("connect_args") or {}
    segredo = connect_args.pop("hub_segredo", None)
    if not segredo:
        return uri, params
    c = credencial(segredo)
    connect_args["private_key"] = c["der"]
    connect_args.pop("private_key_file", None)
    connect_args.pop("private_key_file_pwd", None)
    params["connect_args"] = connect_args
    # O usuário é o do segredo; a senha da tela (se houver) sai da URL.
    # `URL.set(password=None)` não limpa (None = "não mexe"); `_replace` limpa.
    return uri._replace(username=c["user"], password=None), params
