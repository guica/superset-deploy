-- Maturidade · PRs (grão: 1 linha por PR mergeado). Fonte curada pela DAG maturity_pipeline
-- (priv-data-customer-cost-ingestion): tipo pelo prefixo do título, app pelo escopo
-- (APP_FONTE = 'titulo') ou pelo caminho de arquivo ('arquivos').
SELECT PR_NUMBER, TITLE, TIPO, APP,
       COALESCE(APP_LABEL, APP, '(sem app)') AS APP_LABEL, COALESCE(DOMINIO, 'sem app') AS DOMINIO, TRANSVERSAL,
       APP_FONTE, TITULO_VALIDO, AUTHOR, MERGED_AT, DIA, SEMANA, MES,
       ENTREGA, IS_FIX, IS_FEAT, IS_REVERT, ADDITIONS, DELETIONS, CHANGED_FILES, TOCA_TESTES, CARD_URL, BASE_REF
FROM CUSTOMER_DB.CUSTOMER.APP_PR_HISTORY
