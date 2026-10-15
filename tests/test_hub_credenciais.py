"""python -m pytest tests  (precisa de cryptography e sqlalchemy)."""

import importlib.util
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.engine import make_url

spec = importlib.util.spec_from_file_location(
    "hub_credenciais", Path(__file__).parents[1] / "docker/pythonpath_dev/hub_credenciais.py"
)
hub = importlib.util.module_from_spec(spec)
sys.modules["hub_credenciais"] = hub
spec.loader.exec_module(hub)

PEM = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()


class SmFalso:
    def __init__(self):
        self.versao, self.gets, self.describes = "v1", 0, 0

    def get_secret_value(self, SecretId):
        self.gets += 1
        return {"VersionId": self.versao, "SecretString": json.dumps({"user": "SVC_SUPERSET_PROD", "privateKey": PEM})}

    def describe_secret(self, SecretId):
        self.describes += 1
        return {"VersionIdsToStages": {self.versao: ["AWSCURRENT"]}}


def _prepara(monkeypatch):
    sm = SmFalso()
    hub._cache.clear()
    monkeypatch.setattr(hub, "_sm", lambda: sm)
    return sm


def test_sem_hub_segredo_nao_mexe(monkeypatch):
    sm = _prepara(monkeypatch)
    uri = make_url("snowflake://REDASH:senha@conta/DB?role=R")
    params = {"connect_args": {"x": 1}}
    assert hub.mutator(uri, params, "u", None, None) == (uri, params)
    assert sm.gets == 0


def test_com_hub_segredo_troca_usuario_tira_senha_e_poe_a_chave(monkeypatch):
    _prepara(monkeypatch)
    uri = make_url("snowflake://REDASH:senha@conta/DB?role=DASHBOARD_ROLE")
    novo, params = hub.mutator(uri, {"connect_args": {"hub_segredo": "astecha/prod/ast/superset/x"}}, "u", None, None)
    assert novo.username == "SVC_SUPERSET_PROD" and novo.password is None
    assert novo.query["role"] == "DASHBOARD_ROLE"
    assert isinstance(params["connect_args"]["private_key"], bytes)
    assert "hub_segredo" not in params["connect_args"]


def test_cache_e_troca_de_versao_depois_da_rotacao(monkeypatch):
    sm = _prepara(monkeypatch)
    relogio = [1000.0]
    monkeypatch.setattr(hub.time, "time", lambda: relogio[0])
    hub.credencial("s")
    hub.credencial("s")
    assert (sm.gets, sm.describes) == (1, 0)  # dentro dos 60 s: nem confere
    relogio[0] += 61
    hub.credencial("s")
    assert (sm.gets, sm.describes) == (1, 1)  # conferiu, mesma versão
    sm.versao = "v2"
    relogio[0] += 61
    assert hub.credencial("s")["versao"] == "v2" and sm.gets == 2
