-- Maturidade · uso por app e semana (grão: app × semana × origem). Curado pela DAG sobre
-- BRONZE.QUERY_ATTRIBUTION_HISTORY com a mesma régua do dashboard uso-humano.
SELECT APP, APP_LABEL, DOMINIO, ORIGEM, SEMANA, SEMANA::TIMESTAMP_NTZ AS SEMANA_TS,
       ACESSOS, MINUTOS, CLIENTES, DIAS_ATIVOS, ULTIMO_ACESSO
FROM CUSTOMER_DB.CUSTOMER.APP_USAGE_WEEKLY
