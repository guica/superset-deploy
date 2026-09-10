-- Maturidade · placar (grão: 1 linha por app): as quatro perguntas + SITUACAO.
-- Calculado pela DAG (dags/sql/maturity_refresh.sql, passo 5) — aqui só se lê.
SELECT * FROM CUSTOMER_DB.CUSTOMER.APP_MATURITY_SCORE
