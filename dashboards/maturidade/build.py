"""Cria (ou recria) o dashboard "Plataforma — Maturidade dos Apps" no Superset via API.

Idempotente por nome: datasets/charts/dashboard com os mesmos nomes são atualizados.
ATENÇÃO: o nome de cada chart é a chave de upsert e é GLOBAL no Superset — todos os daqui
começam com "Maturidade ·" para não sequestrar charts dos dashboards irmãos (uso-humano,
mcp-uso). Irmão do dashboards/uso-humano/build.py — mesma conexão (CUSTOMER_DB), mesma
dedup do uso; acrescenta as pernas de entrega (PR_HISTORY) e erro (SENTRY_APP_DAILY).

As quatro perguntas que o dashboard responde, e onde cada uma mora:
  1. Onde vai o esforço, e o uso justifica?        → seção "Esforço × uso"
  2. O esforço está surtindo efeito?               → seção "Efeito"
  3. Quem está estabilizado?                       → placar (SITUACAO) + "Correções por 1.000 acessos"
  4. Quem pede atenção?                            → placar (SITUACAO = Atenção) + "Erros por 1.000 acessos"
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import requests  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ["SUPERSET_BASE_URL"].rstrip("/")
DB_ID = 2  # Snowflake CUSTOMER_DB
DASH_TITLE = "Plataforma — Maturidade dos Apps"
DASH_SLUG = "maturidade"

s = requests.Session()
tok = s.post(f"{BASE}/api/v1/security/login", json={
    "username": os.environ["SUPERSET_USERNAME"], "password": os.environ["SUPERSET_PASSWORD"],
    "provider": "db", "refresh": True}).json()["access_token"]
s.headers.update({"Authorization": f"Bearer {tok}", "Referer": BASE})
s.headers.update({"X-CSRFToken": s.get(f"{BASE}/api/v1/security/csrf_token/").json()["result"]})


def api(method, path, **kw):
    r = s.request(method, f"{BASE}{path}", **kw)
    if r.status_code >= 400:
        print("API ERROR", method, path, r.status_code, r.text[:1500])
        sys.exit(1)
    return r.json()


def rison_q(filters, page_size=100):
    f = ",".join(f"(col:{c},opr:{o},value:'{v}')" for c, o, v in filters)
    return f"(filters:!({f}),page_size:{page_size})"


# ── Datasets ────────────────────────────────────────────────────────────────
def read_sql(name):
    with open(os.path.join(HERE, name)) as fh:
        return fh.read()


def upsert_dataset(table_name, sql, main_dttm=None):
    existing = api("GET", f"/api/v1/dataset/?q={rison_q([('table_name', 'eq', table_name)])}")["result"]
    if existing:
        ds_id = existing[0]["id"]
        api("PUT", f"/api/v1/dataset/{ds_id}?override_columns=true", json={"sql": sql})
        api("PUT", f"/api/v1/dataset/{ds_id}/refresh")
        print(f"dataset {table_name} atualizado id={ds_id}")
    else:
        ds_id = api("POST", "/api/v1/dataset/", json={
            "database": DB_ID, "table_name": table_name, "sql": sql, "owners": []})["id"]
        print(f"dataset {table_name} criado id={ds_id}")
    if main_dttm:
        api("PUT", f"/api/v1/dataset/{ds_id}", json={"main_dttm_col": main_dttm})
    cols = [c["column_name"] for c in api("GET", f"/api/v1/dataset/{ds_id}")["result"]["columns"]]
    print("   colunas:", len(cols))
    return ds_id


PRS_ID = upsert_dataset("mat_prs", read_sql("dataset_mat_prs.sql"), main_dttm="MERGED_AT")
USO_ID = upsert_dataset("mat_uso_semanal", read_sql("dataset_mat_uso_semanal.sql"), main_dttm="SEMANA_TS")
SEN_ID = upsert_dataset("mat_sentry_semanal", read_sql("dataset_mat_sentry_semanal.sql"), main_dttm="SEMANA_TS")
PLA_ID = upsert_dataset("mat_placar", read_sql("dataset_mat_placar.sql"))
MOV_ID = upsert_dataset("mat_movimento", read_sql("dataset_mat_movimento.sql"), main_dttm="SEMANA_TS")
REW_ID = upsert_dataset("mat_retrabalho", read_sql("dataset_mat_retrabalho.sql"))


# ── Helpers de form_data ────────────────────────────────────────────────────
def m(sql, label):
    return {"expressionType": "SQL", "sqlExpression": sql, "label": label}


def sqlf(expr):
    return {"clause": "WHERE", "expressionType": "SQL", "sqlExpression": expr}


def trange(col, comparator="No filter"):
    return {"clause": "WHERE", "expressionType": "SIMPLE", "subject": col,
            "operator": "TEMPORAL_RANGE", "comparator": comparator}


PRS = m("COUNT(*)", "PRs")
FIXES = m("SUM(IS_FIX)", "Correções")
FEATS = m("SUM(IS_FEAT)", "Funcionalidades")
FIX_PCT = m("ROUND(100.0 * SUM(IS_FIX) / NULLIF(SUM(IS_FIX) + SUM(IS_FEAT), 0), 1)", "Razão de conserto %")
ACESSOS = m("SUM(ACESSOS)", "Acessos a telas (aprox.)")
ERROS = m("SUM(EVENTS)", "Eventos de erro")
ISSUES = m("SUM(ISSUES)", "Issues")
PROD = sqlf("ORIGEM = 'Cliente (prod)'")
SEN_PROD = sqlf("ENV = 'prod'")
ENTREGA = sqlf("ENTREGA = 1")
NAO_TRANSV = sqlf("NOT TRANSVERSAL")
LAST7_PR = sqlf("MERGED_AT >= DATEADD(day, -7, CURRENT_DATE())")
LAST90_PR = sqlf("MERGED_AT >= DATEADD(day, -90, CURRENT_DATE())")
LAST42_PR = sqlf("MERGED_AT >= DATEADD(day, -42, CURRENT_DATE())")
LAST7_SEM = sqlf("SEMANA_TS >= DATEADD(day, -7, CURRENT_DATE())")


def big(ds_col, metric, subheader, fmt="SMART_NUMBER", filters=None):
    return {"viz_type": "big_number_total", "metric": metric, "adhoc_filters": (filters or []) + [trange(ds_col)],
            "subheader": subheader, "y_axis_format": fmt, "header_font_size": 0.4,
            "subheader_font_size": 0.15, "time_format": "smart_date", "force_timestamp_formatting": False}


def ts(viz, x, metrics, groupby=None, grain=None, extra=None, filters=None, tcol=None):
    p = {"viz_type": viz, "x_axis": x, "metrics": metrics, "groupby": groupby or [],
         "adhoc_filters": (filters or []) + [trange(tcol or x)], "row_limit": 10000,
         "truncate_metric": True, "show_empty_columns": True, "comparison_type": "values",
         "annotation_layers": [], "forecastPeriods": 10, "forecastInterval": 0.8,
         "x_axis_title_margin": 15, "y_axis_title_margin": 15, "y_axis_title_position": "Left",
         "sort_series_type": "sum", "color_scheme": "supersetColors", "show_value": False,
         "only_total": True, "show_legend": True, "legendType": "scroll", "legendOrientation": "top",
         "x_axis_time_format": "smart_date", "rich_tooltip": True, "showTooltipTotal": True,
         "tooltipTimeFormat": "smart_date", "y_axis_format": "SMART_NUMBER", "truncateXAxis": True,
         "y_axis_bounds": [None, None], "extra_form_data": {}}
    if grain:
        p["time_grain_sqla"] = grain
    if extra:
        p.update(extra)
    return p


def table_raw(columns, order_col, filters=None, col_cfg=None, fmt=None, row_limit=100, tcol="MERGED_AT"):
    return {"viz_type": "table", "query_mode": "raw", "all_columns": columns,
            "order_by_cols": [json.dumps([order_col, False])], "row_limit": row_limit,
            "adhoc_filters": (filters or []), "show_cell_bars": True, "color_pn": False,
            "table_timestamp_format": "%Y-%m-%d", "column_config": col_cfg or {},
            "conditional_formatting": fmt or [], "extra_form_data": {}}


def table_agg(groupby, metrics, order_label, filters=None, col_cfg=None, row_limit=50, tcol="MERGED_AT", extra=None):
    p = {"viz_type": "table", "query_mode": "aggregate", "groupby": groupby, "metrics": metrics,
         "all_columns": [], "percent_metrics": [], "adhoc_filters": (filters or []) + [trange(tcol)],
         "order_by_cols": [json.dumps([order_label, False])], "row_limit": row_limit,
         "server_page_length": 25, "order_desc": True, "show_cell_bars": True, "color_pn": False,
         "table_timestamp_format": "%Y-%m-%d %H:%M", "column_config": col_cfg or {},
         "conditional_formatting": [], "extra_form_data": {}}
    if extra:
        p.update(extra)
    return p


def hbar(ds_x, metric, filters, tcol, limit=30, extra=None):
    return ts("echarts_timeseries_bar", ds_x, [metric], [], None,
              {"orientation": "horizontal", "row_limit": limit, "order_desc": True, "show_value": True,
               "y_axis_format": ",.1f", "show_legend": False, "truncateXAxis": False,
               "timeseries_limit_metric": metric, "x_axis_sort_series": "sum",
               "x_axis_sort_asc": True, "x_axis_sort": metric["label"], **(extra or {})},
              filters=filters, tcol=tcol)


INT = {"d3NumberFormat": ",d"}
DEC = {"d3NumberFormat": ",.1f"}
SIT_COLORS = [
    ("Atenção", "#E04355"), ("Sob pressão", "#FF7F44"), ("Esforço sem retorno", "#FCC700"),
    ("Em estabilização", "#FFB300"), ("Em construção", "#5AC189"), ("Estabilizado", "#1FA8C9"),
    ("Sem uso", "#A868B7"), ("Sem evidência", "#B2B2B2"), ("Inativo", "#E0E0E0"),
]
FMT_SIT = [{"colorScheme": c, "column": "SITUACAO", "operator": "=", "targetValue": v} for v, c in SIT_COLORS]

PLACAR_COLS = ["APP_LABEL", "DOMINIO", "SITUACAO", "PRS_90D", "FIX_90D", "FEAT_90D", "PRS_6SEM", "PRS_DELTA_PCT",
               "FIX_PCT_6SEM", "FIX_DELTA_PP", "ACESSOS_90D", "ACESSOS_6SEM", "USO_DELTA_PCT", "CLIENTES_90D",
               "ULTIMO_ACESSO", "PRS_POR_1K", "FIX_POR_1K", "ERROS_30D", "ERROS_POR_1K", "ERROS_DELTA_PCT",
               "LINHAS_90D", "TESTE_PCT", "TITULO_PCT"]
PCT = {"d3NumberFormat": ",d"}

charts = {
    # KPIs
    "kpi_prs": ("Maturidade · KPI · PRs mergeados (7d)", PRS_ID, big("MERGED_AT", PRS, "PRs mergeados na stage nos últimos 7 dias", filters=[LAST7_PR])),
    "kpi_fix": ("Maturidade · KPI · Razão de conserto (6 sem)", PRS_ID, big("MERGED_AT", FIX_PCT, "fix ÷ (fix + feat), últimas 6 semanas, todos os apps", filters=[LAST42_PR, ENTREGA])),
    "kpi_uso": ("Maturidade · KPI · Acessos a telas (7d)", USO_ID, big("SEMANA_TS", ACESSOS, "só produção (clientes)", filters=[PROD, LAST7_SEM])),
    "kpi_erros": ("Maturidade · KPI · Erros em produção (7d)", SEN_ID, big("SEMANA_TS", ERROS, "eventos level:error, backend + frontend", filters=[SEN_PROD, LAST7_SEM])),
    # 1. Esforço × uso
    "esforco_app": ("Maturidade · PRs por app (90d)", PRS_ID,
                    hbar("APP_LABEL", PRS, [LAST90_PR, NAO_TRANSV], "MERGED_AT", extra={"y_axis_format": ",d"})),
    "esforco_tipo": ("Maturidade · Funcionalidade × correção por app (90d)", PRS_ID,
                     ts("echarts_timeseries_bar", "APP_LABEL", [FEATS, FIXES], [], None,
                        {"orientation": "horizontal", "stack": "Stack", "row_limit": 30, "show_value": False,
                         "y_axis_format": ",d", "truncateXAxis": False, "x_axis_sort": "Correções", "x_axis_sort_asc": True},
                        filters=[LAST90_PR, NAO_TRANSV, ENTREGA], tcol="MERGED_AT")),
    "bolhas": ("Maturidade · Onde o esforço encontra o uso", PLA_ID, {
        "viz_type": "bubble_v2", "entity": "APP_LABEL", "series": "SITUACAO",
        "x": m("MAX(ACESSOS_90D)", "Acessos 90d"), "y": m("MAX(FIX_PCT_6SEM)", "Conserto 6 sem %"),
        "size": m("MAX(PRS_90D)", "PRs 90d"), "adhoc_filters": [sqlf("ACESSOS_90D > 0")],
        "row_limit": 100, "max_bubble_size": "25", "logXAxis": True, "logYAxis": False,
        "x_axis_format": "SMART_NUMBER", "y_axis_format": "SMART_NUMBER", "tooltipSizeFormat": "SMART_NUMBER",
        "show_legend": True, "legendType": "scroll", "legendOrientation": "top", "color_scheme": "supersetColors",
        "x_axis_title": "Acessos a telas em produção (90d, escala log)", "y_axis_title": "Razão de conserto amortecida (6 sem)",
        "x_axis_title_margin": 30, "y_axis_title_margin": 30, "truncateXAxis": False, "extra_form_data": {}}),
    "prs_por_1k": ("Maturidade · Esforço por uso · PRs por 1.000 acessos", PLA_ID, table_raw(
        ["APP_LABEL", "SITUACAO", "PRS_90D", "ACESSOS_90D", "CLIENTES_90D", "PRS_POR_1K", "FIX_POR_1K"], "PRS_POR_1K",
        filters=[sqlf("PRS_POR_1K IS NOT NULL")], col_cfg={"PRS_90D": INT, "ACESSOS_90D": INT, "PRS_POR_1K": DEC, "FIX_POR_1K": DEC},
        fmt=FMT_SIT)),
    "linhas_app": ("Maturidade · Linhas alteradas por app (90d)", PLA_ID,
                   hbar("APP_LABEL", m("MAX(LINHAS_90D)", "Linhas alteradas"), [sqlf("LINHAS_90D > 0")], "ULTIMO_ACESSO",
                        extra={"y_axis_format": ",d"})),
    "sem_uso": ("Maturidade · PRs em apps sem uso em produção (90d)", PLA_ID, table_raw(
        ["APP_LABEL", "DOMINIO", "PRS_90D", "FIX_90D", "FEAT_90D", "ACESSOS_90D", "ULTIMO_ACESSO"], "PRS_90D",
        filters=[sqlf("SITUACAO IN ('Sem uso', 'Inativo') AND PRS_90D > 0")], col_cfg={"PRS_90D": INT})),
    # 2. Efeito
    "mov_fix": ("Maturidade · Razão de conserto amortecida · por app e semana", MOV_ID,
                ts("echarts_timeseries_line", "SEMANA_TS", [m("AVG(FIX_PCT_AMORT)", "Conserto % (3 sem, amortecida)")], ["APP_LABEL"], "P1W",
                   {"markerEnabled": True, "markerSize": 4, "y_axis_format": ",d", "y_axis_bounds": [0, 100], "zoomable": True},
                   filters=[sqlf("PRS_3SEM >= 3")])),
    "mov_uso": ("Maturidade · Acessos por semana · por app (prod)", USO_ID,
                ts("echarts_area", "SEMANA_TS", [ACESSOS], ["APP_LABEL"], "P1W",
                   {"stack": "Stack", "opacity": 0.6, "y_axis_format": ",d"}, filters=[PROD])),
    "tendencia": ("Maturidade · Tendência · uso e conserto, 3 semanas vs 3 anteriores", PLA_ID, table_raw(
        ["APP_LABEL", "SITUACAO", "ACESSOS_3B", "ACESSOS_3A", "USO_DELTA_PCT", "FIX_PCT_3B", "FIX_PCT_3A", "FIX_DELTA_PP", "PRS_6SEM"], "USO_DELTA_PCT",
        filters=[sqlf("ACESSOS_3B + ACESSOS_3A >= 30")], col_cfg={"ACESSOS_3B": INT, "ACESSOS_3A": INT, "PRS_6SEM": INT},
        fmt=FMT_SIT + [
            {"colorScheme": "#5AC189", "column": "FIX_DELTA_PP", "operator": "<", "targetValue": -3},
            {"colorScheme": "#E04355", "column": "FIX_DELTA_PP", "operator": ">", "targetValue": 5},
            {"colorScheme": "#5AC189", "column": "USO_DELTA_PCT", "operator": ">", "targetValue": 10},
        ])),
    "melhorando": ("Maturidade · Quem está melhorando · Δ uso × Δ conserto", PLA_ID, {
        "viz_type": "bubble_v2", "entity": "APP_LABEL", "series": "SITUACAO",
        "x": m("MAX(USO_DELTA_PCT)", "Δ uso % (3 sem vs 3 anteriores)"), "y": m("MAX(FIX_DELTA_PP)", "Δ conserto pp"),
        "size": m("MAX(ACESSOS_90D)", "Acessos 90d"), "adhoc_filters": [sqlf("USO_DELTA_PCT IS NOT NULL AND FIX_DELTA_PP IS NOT NULL AND ACESSOS_3A + ACESSOS_3B >= 30")],
        "row_limit": 100, "max_bubble_size": "25", "logXAxis": False, "logYAxis": False,
        "x_axis_format": "SMART_NUMBER", "y_axis_format": "SMART_NUMBER", "tooltipSizeFormat": "SMART_NUMBER",
        "show_legend": True, "legendType": "scroll", "legendOrientation": "top", "color_scheme": "supersetColors",
        "x_axis_title": "Δ uso % — direita = usando mais", "y_axis_title": "Δ conserto pp — baixo = menos problema",
        "x_axis_title_margin": 30, "y_axis_title_margin": 30, "truncateXAxis": False, "extra_form_data": {}}),
    "mov_err1k": ("Maturidade · Erros por 1.000 acessos · por semana", MOV_ID,
                  ts("echarts_timeseries_line", "SEMANA_TS", [m("AVG(ERROS_POR_1K)", "Erros / 1.000 acessos (3 sem)")], ["APP_LABEL"], "P1W",
                     {"markerEnabled": True, "markerSize": 4, "y_axis_format": ",.1f", "zoomable": True},
                     filters=[sqlf("ERROS_POR_1K IS NOT NULL")])),
    "mov_fix1k": ("Maturidade · Correções por 1.000 acessos · por semana", MOV_ID,
                  ts("echarts_timeseries_line", "SEMANA_TS", [m("AVG(FIX_POR_1K)", "Correções / 1.000 acessos (3 sem)")], ["APP_LABEL"], "P1W",
                     {"markerEnabled": True, "markerSize": 4, "y_axis_format": ",.1f", "zoomable": True},
                     filters=[sqlf("FIX_POR_1K IS NOT NULL")])),
    # 3/4. Placar, estabilidade e atenção
    "placar": ("Maturidade · Placar · situação por app", PLA_ID, table_raw(
        PLACAR_COLS, "ACESSOS_90D", filters=[sqlf("PRS_90D > 0 OR ACESSOS_90D > 0")],
        col_cfg={"PRS_90D": INT, "FIX_90D": INT, "FEAT_90D": INT, "PRS_6SEM": INT, "ACESSOS_90D": INT, "ACESSOS_6SEM": INT,
                 "CLIENTES_90D": INT, "ERROS_30D": INT, "PRS_POR_1K": DEC, "FIX_POR_1K": DEC, "ERROS_POR_1K": DEC},
        fmt=FMT_SIT)),
    "estaveis": ("Maturidade · Estabilizados · usados, com pouco conserto e pouca modificação", PLA_ID, table_raw(
        ["APP_LABEL", "ACESSOS_90D", "CLIENTES_90D", "PRS_6SEM", "PRS_DELTA_PCT", "FIX_PCT_6SEM", "FIX_POR_1K", "ERROS_POR_1K", "TESTE_PCT"], "ACESSOS_90D",
        filters=[sqlf("SITUACAO = 'Estabilizado'")], col_cfg={"ACESSOS_90D": INT, "PRS_6SEM": INT, "FIX_POR_1K": DEC, "ERROS_POR_1K": DEC})),
    "mov_vol": ("Maturidade · Volume de modificação · PRs por semana (3 sem), por app", MOV_ID,
                ts("echarts_timeseries_line", "SEMANA_TS", [m("AVG(PRS_3SEM)", "PRs (3 sem)")], ["APP_LABEL"], "P1W",
                   {"markerEnabled": True, "markerSize": 4, "y_axis_format": ",d", "zoomable": True})),
    "atencao": ("Maturidade · Atenção · muito uso com muito erro, ou erro subindo", PLA_ID, table_raw(
        ["APP_LABEL", "ACESSOS_90D", "FIX_PCT_6SEM", "FIX_DELTA_PP", "ERROS_30D", "ERROS_POR_1K", "ERROS_3B", "ERROS_3A", "ERROS_DELTA_PCT", "PRS_6SEM"], "ERROS_POR_1K",
        filters=[sqlf("SITUACAO = 'Atenção'")], col_cfg={"ACESSOS_90D": INT, "ERROS_30D": INT, "ERROS_3B": INT, "ERROS_3A": INT, "PRS_6SEM": INT, "ERROS_POR_1K": DEC},
        fmt=[{"colorScheme": "#E04355", "column": "ERROS_DELTA_PCT", "operator": ">", "targetValue": 50},
             {"colorScheme": "#E04355", "column": "FIX_DELTA_PP", "operator": ">", "targetValue": 5}])),
    "retrabalho": ("Maturidade · Retrabalho · arquivos corrigidos 2+ vezes em 6 semanas", REW_ID, table_raw(
        ["APP_LABEL", "PATH", "N_FIXES", "PRIMEIRO_FIX", "ULTIMO_FIX", "PRS"], "N_FIXES", col_cfg={"N_FIXES": INT}, row_limit=100)),
    "clientes_sem": ("Maturidade · Clientes ativos por semana · por app (prod)", USO_ID,
                     ts("echarts_timeseries_line", "SEMANA_TS", [m("MAX(CLIENTES)", "Clientes")], ["APP_LABEL"], "P1W",
                        {"markerEnabled": True, "markerSize": 4, "y_axis_format": ",d"}, filters=[PROD])),
    "testes_app": ("Maturidade · PRs com teste · por app (90d)", PLA_ID,
                   hbar("APP_LABEL", m("MAX(TESTE_PCT)", "PRs com teste %"), [sqlf("PRS_90D >= 4")], "ULTIMO_ACESSO",
                        extra={"y_axis_format": ",d"})),
    "situacao": ("Maturidade · Apps por situação", PLA_ID, {
        "viz_type": "pie", "groupby": ["SITUACAO"], "metric": m("COUNT(*)", "Apps"),
        "adhoc_filters": [sqlf("SITUACAO NOT IN ('Inativo')")], "row_limit": 20, "donut": True, "show_labels": True,
        "label_type": "key_value", "show_legend": True, "legendOrientation": "right", "color_scheme": "supersetColors",
        "innerRadius": 40, "outerRadius": 70, "extra_form_data": {}}),
    "fix1k": ("Maturidade · Correções por 1.000 acessos (90d)", PLA_ID,
              hbar("APP_LABEL", m("MAX(FIX_POR_1K)", "Correções / 1.000 acessos"), [sqlf("FIX_POR_1K IS NOT NULL")], "ULTIMO_ACESSO")),
    "err1k": ("Maturidade · Erros por 1.000 acessos (30d)", PLA_ID,
              hbar("APP_LABEL", m("MAX(ERROS_POR_1K)", "Erros / 1.000 acessos"), [sqlf("ERROS_POR_1K IS NOT NULL")], "ULTIMO_ACESSO")),
    "erros_sem": ("Maturidade · Erros por semana · por app (prod)", SEN_ID,
                  ts("echarts_timeseries_bar", "SEMANA_TS", [ERROS], ["APP_LABEL"], "P1W",
                     {"stack": "Stack", "y_axis_format": ",d"}, filters=[SEN_PROD])),
    "erros_fonte": ("Maturidade · Ponto cego do Sentry · como o app foi atribuído", SEN_ID,
                    ts("echarts_timeseries_bar", "SEMANA_TS", [ERROS], ["FONTE"], "P1W",
                       {"stack": "Stack", "y_axis_format": ",d", "contributionMode": "row"}, filters=[SEN_PROD])),
    # Qualidade do dado
    "titulo_fonte": ("Maturidade · PRs classificados pelo título · por semana", PRS_ID,
                     ts("echarts_timeseries_bar", "MERGED_AT", [PRS], ["APP_FONTE"], "P1W",
                        {"stack": "Stack", "y_axis_format": ",d", "contributionMode": "row"})),
    "prs_lista": ("Maturidade · PRs recentes", PRS_ID, table_raw(
        ["MERGED_AT", "PR_NUMBER", "TIPO", "APP_LABEL", "APP_FONTE", "TITLE", "AUTHOR", "TOCA_TESTES"], "MERGED_AT",
        filters=[trange("MERGED_AT", "Last month")], row_limit=200)),
}

# ── Dashboard ───────────────────────────────────────────────────────────────
existing = api("GET", f"/api/v1/dashboard/?q={rison_q([('slug', 'eq', DASH_SLUG)])}")["result"]
if existing:
    DASH_ID = existing[0]["id"]
    print("dashboard existente id=", DASH_ID)
else:
    DASH_ID = api("POST", "/api/v1/dashboard/", json={"dashboard_title": DASH_TITLE, "slug": DASH_SLUG, "published": False})["id"]
    print("dashboard criado id=", DASH_ID)

chart_ids = {}
for key, (name, ds_id, params) in charts.items():
    params = {**params, "datasource": f"{ds_id}__table"}
    body = {"slice_name": name, "viz_type": params["viz_type"], "datasource_id": ds_id,
            "datasource_type": "table", "params": json.dumps(params), "dashboards": [DASH_ID]}
    found = api("GET", f"/api/v1/chart/?q={rison_q([('slice_name', 'eq', name)])}")["result"]
    if found:
        cid = found[0]["id"]
        api("PUT", f"/api/v1/chart/{cid}", json=body)
    else:
        cid = api("POST", "/api/v1/chart/", json=body)["id"]
    chart_ids[key] = cid
    print(f"chart {name!r} id={cid}")

# ── Layout ──────────────────────────────────────────────────────────────────
pos = {"DASHBOARD_VERSION_KEY": "v2",
       "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
       "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
       "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": DASH_TITLE}}}
n = [0]


def add_row(items):
    n[0] += 1
    rid = f"ROW-mat-{n[0]}"
    pos[rid] = {"type": "ROW", "id": rid, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"}}
    pos["GRID_ID"]["children"].append(rid)
    for kind, payload, width, height in items:
        n[0] += 1
        if kind == "chart":
            cid = f"CHART-mat-{n[0]}"
            pos[cid] = {"type": "CHART", "id": cid, "children": [], "parents": ["ROOT_ID", "GRID_ID", rid],
                        "meta": {"width": width, "height": height, "chartId": chart_ids[payload], "sliceName": charts[payload][0]}}
        else:
            cid = f"MARKDOWN-mat-{n[0]}"
            pos[cid] = {"type": "MARKDOWN", "id": cid, "children": [], "parents": ["ROOT_ID", "GRID_ID", rid],
                        "meta": {"width": width, "height": height, "code": payload}}
        pos[rid]["children"].append(cid)


def add_header(text):
    n[0] += 1
    hid = f"HEADER-mat-{n[0]}"
    pos[hid] = {"type": "HEADER", "id": hid, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"text": text, "headerSize": "MEDIUM_HEADER", "background": "BACKGROUND_TRANSPARENT"}}
    pos["GRID_ID"]["children"].append(hid)


INTRO = """### Como ler este dashboard
Três fontes, um vocabulário de app: **entrega** (PRs mergeados na `stage`, classificados pelo título — `feat`/`fix`/… e o escopo entre parênteses; `CUSTOMER_DB.PLATFORM.PR_HISTORY`), **uso** (acessos humanos a telas em produção, a mesma fonte e filtros do dashboard *Uso Humano por Cliente*) e **erro** (eventos do Sentry por app; `PLATFORM.SENTRY_APP_DAILY`). Carga semanal: `maturity-load.yml` (terça à noite).

- **Razão de conserto** = `fix ÷ (fix + feat)`. Só `feat`/`fix`/`perf`/`refactor` contam como entrega; `docs`/`ci`/`test`/`chore` ficam fora. Nas janelas curtas ela é **amortecida**: `(fix + 6·p₀) ÷ (n + 6)`, com p₀ = razão do app em 90 dias — com 2 PRs a razão bruta só pode ser 0, 50 ou 100%.
- **PRs / correções / erros por 1.000 acessos** normalizam o esforço e a dor pelo uso: um app com 130 correções e 13 mil acessos é mais saudável que um com 10 correções e 80 acessos.
- **Situação** (placar): *Atenção* = uso alto (≥400 acessos/90d) com conserto >62%, ou subindo ≥8 pp, ou ≥20 erros por 1.000 acessos, ou erros crescendo ≥50% (3 semanas vs 3 anteriores) · *Sob pressão* = ≥20 PRs e conserto >62% · *Esforço sem retorno* = >100 PRs por 1.000 acessos em app com <300 acessos · *Estabilizado* = uso alto, ≤12 correções por 1.000 acessos e ≤15 PRs em 6 semanas · *Em construção* = conserto ≤45% · *Sem uso* = PRs sem nenhum acesso em produção.
- **Pontos cegos**: tela servida do cache não gera `QUERY_TAG` (ausência ≠ não uso); o usuário final ainda não está no tag das telas (acesso conta por cliente); eventos do Sentry sem `transaction` aparecem como *~sem-atribuicao* até a tag `app` estar no ar (gráfico "Ponto cego do Sentry"); PR com título fora do padrão é atribuído pelo caminho de arquivo (`APP_FONTE = arquivos`).
"""

add_row([("md", INTRO, 12, 34)])
add_header("Visão geral · últimos 7 dias")
add_row([("chart", "kpi_prs", 3, 30), ("chart", "kpi_fix", 3, 30), ("chart", "kpi_uso", 3, 30), ("chart", "kpi_erros", 3, 30)])
add_header("1 · Onde vai o esforço, e o uso justifica?")
add_row([("chart", "esforco_app", 4, 70), ("chart", "esforco_tipo", 4, 70), ("chart", "bolhas", 4, 70)])
add_row([("chart", "prs_por_1k", 5, 60), ("chart", "linhas_app", 3, 60), ("chart", "sem_uso", 4, 60)])
add_header("2 · O esforço está surtindo efeito?")
add_row([("chart", "melhorando", 6, 65), ("chart", "tendencia", 6, 65)])
add_row([("chart", "mov_fix", 6, 55), ("chart", "mov_uso", 6, 55)])
add_row([("chart", "mov_fix1k", 6, 50), ("chart", "mov_err1k", 6, 50)])
add_header("3 · Quem está estabilizado (usado, pouco conserto, pouca modificação)")
add_row([("chart", "estaveis", 7, 50), ("chart", "mov_vol", 5, 50)])
add_row([("chart", "fix1k", 6, 60), ("chart", "clientes_sem", 6, 60)])
add_header("4 · Quem pede atenção (muito uso com muito erro, ou erro subindo)")
add_row([("chart", "atencao", 12, 50)])
add_row([("chart", "err1k", 4, 60), ("chart", "erros_sem", 4, 60), ("chart", "retrabalho", 4, 60)])
add_header("Placar completo")
add_row([("chart", "placar", 9, 75), ("chart", "situacao", 3, 75)])
add_header("Qualidade do dado")
add_row([("chart", "titulo_fonte", 4, 50), ("chart", "erros_fonte", 4, 50), ("chart", "testes_app", 4, 50)])
add_row([("chart", "prs_lista", 12, 60)])


def scope(ds):
    return [chart_ids[k] for k, (_, d, _) in charts.items() if d == ds]


def nf(fid, name, column, targets, scope_ids, ftype="filter_select"):
    return {"id": f"NATIVE_FILTER-mat-{fid}", "name": name, "filterType": ftype, "type": "NATIVE_FILTER",
            "controlValues": {"enableEmptyFilter": False, "inverseSelection": False, "multiSelect": True,
                              "defaultToFirstItem": False, "searchAllOptions": False},
            "targets": [{"datasetId": d, "column": {"name": column}} for d in targets] if column else [{}],
            "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
            "cascadeParentIds": [], "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
            "description": "", "chartsInScope": scope_ids, "tabsInScope": []}


ALL_DS = [PRS_ID, USO_ID, SEN_ID, PLA_ID, MOV_ID, REW_ID]
todos = [cid for cid in chart_ids.values()]
temporais = scope(PRS_ID) + scope(USO_ID) + scope(SEN_ID) + scope(MOV_ID)
meta = {"color_scheme": "supersetColors", "refresh_frequency": 0, "expanded_slices": {}, "label_colors": {},
        "timed_refresh_immune_slices": [], "cross_filters_enabled": True, "shared_label_colors": [],
        "chart_configuration": {},
        "native_filter_configuration": [
            nf("periodo", "Período (séries semanais e PRs)", None, [], temporais, "filter_time"),
            nf("app", "App", "APP_LABEL", ALL_DS, todos),
            nf("dominio", "Domínio", "DOMINIO", ALL_DS, todos),
            nf("situacao", "Situação", "SITUACAO", [PLA_ID], scope(PLA_ID)),
        ]}

api("PUT", f"/api/v1/dashboard/{DASH_ID}", json={
    "dashboard_title": DASH_TITLE, "slug": DASH_SLUG, "published": True,
    "position_json": json.dumps(pos), "json_metadata": json.dumps(meta)})
print(f"\nOK → {BASE}/superset/dashboard/{DASH_SLUG}/")
