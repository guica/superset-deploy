"""Executa a query de cada chart do dashboard maturidade via /api/v1/chart/data, montando o
query_context a partir do form_data salvo (equivalente ao que o frontend faz ao renderizar)."""
import json
import os
import time
import warnings

warnings.filterwarnings("ignore")
import requests  # noqa: E402

BASE = os.environ["SUPERSET_BASE_URL"].rstrip("/")
s = requests.Session()
tok = s.post(f"{BASE}/api/v1/security/login", json={
    "username": os.environ["SUPERSET_USERNAME"], "password": os.environ["SUPERSET_PASSWORD"],
    "provider": "db", "refresh": True}).json()["access_token"]
s.headers.update({"Authorization": f"Bearer {tok}", "Referer": BASE})
s.headers.update({"X-CSRFToken": s.get(f"{BASE}/api/v1/security/csrf_token/").json()["result"]})

dash = s.get(f"{BASE}/api/v1/dashboard/maturidade/charts").json()["result"]


def split_filters(adhoc):
    where, filters = [], []
    for f in adhoc or []:
        if f.get("expressionType") == "SQL":
            where.append(f"({f['sqlExpression']})")
        elif f.get("operator") == "TEMPORAL_RANGE":
            filters.append({"col": f["subject"], "op": "TEMPORAL_RANGE", "val": f.get("comparator", "No filter")})
    return " AND ".join(where), filters


def qc(ds_id, p):
    viz = p["viz_type"]
    where, filters = split_filters(p.get("adhoc_filters"))
    q = {"filters": filters, "extras": {"where": where, "having": ""}, "columns": [], "metrics": [],
         "orderby": [], "row_limit": p.get("row_limit", 1000), "time_range": "No filter",
         "annotation_layers": [], "applied_time_extras": {}, "url_params": {}, "custom_params": {}, "custom_form_data": {}}
    if viz == "big_number_total":
        q["metrics"] = [p["metric"]]
    elif viz == "bubble_v2":
        # dispersão: entidade (+ série) nas colunas, x/y/tamanho como métricas
        q["columns"] = [p["entity"]] + ([p["series"]] if p.get("series") else [])
        q["metrics"] = [p["x"], p["y"], p["size"]]
    elif viz.startswith("echarts_"):
        x = p["x_axis"]
        if p.get("time_grain_sqla"):
            q["columns"] = [{"timeGrain": p["time_grain_sqla"], "columnType": "BASE_AXIS", "sqlExpression": x,
                             "label": x, "expressionType": "SQL"}]
            q["extras"]["time_grain_sqla"] = p["time_grain_sqla"]
        else:
            q["columns"] = [x]
        q["columns"] += p.get("groupby", [])
        q["metrics"] = p["metrics"]
        if p.get("order_desc") and not p.get("time_grain_sqla"):
            q["orderby"] = [[p["metrics"][0], False]]
    elif viz == "table":
        if p.get("query_mode") == "raw":
            q["columns"] = p["all_columns"]
            q["orderby"] = [json.loads(o) for o in p.get("order_by_cols", [])]
        else:
            q["columns"] = p["groupby"]
            q["metrics"] = p["metrics"]
            for o in p.get("order_by_cols", []):
                lbl, asc = json.loads(o)
                met = next((mm for mm in p["metrics"] if mm.get("label") == lbl), lbl)
                q["orderby"].append([met, asc])
    elif viz == "pivot_table_v2":
        q["columns"] = p["groupbyRows"] + p["groupbyColumns"]
        q["metrics"] = p["metrics"]
    elif viz == "pie":
        q["columns"] = p["groupby"]
        q["metrics"] = [p["metric"]]
    elif viz == "heatmap_v2":
        q["columns"] = [p["x_axis"], p["groupby"]]
        q["metrics"] = [p["metric"]]
    return {"datasource": {"id": ds_id, "type": "table"}, "force": True, "queries": [q],
            "form_data": p, "result_format": "json", "result_type": "full"}


ok = 0
for c in sorted(dash, key=lambda c: c["id"]):
    p = c["form_data"]
    ds_id = int(p["datasource"].split("__")[0])
    t = time.time()
    r = s.post(f"{BASE}/api/v1/chart/data", json=qc(ds_id, p))
    if r.status_code != 200:
        print(f"[{c['id']}] {c['slice_name']}: HTTP {r.status_code} {r.text[:700]}")
        continue
    res = r.json()["result"][0]
    err = res.get("error")
    print(f"[{c['id']}] {c['slice_name']}: {res.get('status')} rows={res.get('rowcount')} "
          f"{time.time() - t:.1f}s" + (f" ERR={err}" if err else "")
          + f"\n      {json.dumps((res.get('data') or [])[:2], default=str, ensure_ascii=False)[:300]}")
    ok += not err
print(f"\n{ok}/{len(dash)} charts OK")
