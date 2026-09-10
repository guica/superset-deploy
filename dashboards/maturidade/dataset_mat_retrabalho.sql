-- Maturidade · retrabalho (grão: app × arquivo). Arquivo tocado por 2+ PRs `fix` nas últimas
-- 6 semanas — "conserto que não pegou". Calculado pela DAG (maturity_refresh.sql, passo 6).
SELECT APP, APP_LABEL, DOMINIO, PATH, N_FIXES, PRIMEIRO_FIX, ULTIMO_FIX, PRS::STRING AS PRS
FROM CUSTOMER_DB.CUSTOMER.APP_REWORK
