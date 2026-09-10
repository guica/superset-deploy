-- Maturidade · movimento (grão: app × semana, janela deslizante de 3 semanas, razão amortecida).
-- Calculado pela DAG (dags/sql/maturity_refresh.sql, passo 4) — aqui só se lê.
SELECT *, SEMANA::TIMESTAMP_NTZ AS SEMANA_TS FROM CUSTOMER_DB.CUSTOMER.APP_MATURITY_WEEKLY
