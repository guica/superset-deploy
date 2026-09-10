-- Maturidade · erros do Sentry por app e dia/semana. FONTE = como o app foi atribuído:
-- 'tag' (o app carimbou `app`), 'transaction' (parse da rota/task) ou 'nenhuma' (ponto cego).
SELECT DIA, APP, COALESCE(APP_LABEL, APP) AS APP_LABEL, COALESCE(DOMINIO, 'sem app') AS DOMINIO,
       PROJECT, ENV, FONTE, GRANULARIDADE, SEMANA, SEMANA::TIMESTAMP_NTZ AS SEMANA_TS, EVENTS, ISSUES, USERS
FROM CUSTOMER_DB.CUSTOMER.APP_SENTRY_DAILY
