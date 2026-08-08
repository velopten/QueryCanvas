WITH tgt AS (
    -- 추출 대상 테이블 목록을 온보딩할 스키마에 맞게 채우세요
    SELECT column_value AS table_name FROM TABLE(SYS.ODCIVARCHAR2LIST(
        'YOUR_TABLE_1','YOUR_TABLE_2','YOUR_TABLE_3'
    ))
)
SELECT ddl_text FROM (
    SELECT 1 AS ord, t.table_name, 1 AS sub,
           DBMS_METADATA.GET_DDL('TABLE', t.table_name) || CHR(10) || '/' AS ddl_text
    FROM   tgt t
    WHERE  EXISTS (SELECT 1 FROM user_tables ut WHERE ut.table_name = t.table_name)
    UNION ALL
    SELECT 2, c.table_name, 1,
           'COMMENT ON TABLE ' || c.table_name ||
           ' IS ''' || REPLACE(c.comments, '''', '''''') || '''' || CHR(10) || '/'
    FROM   user_tab_comments c
           JOIN tgt t ON t.table_name = c.table_name
    WHERE  c.comments IS NOT NULL
    UNION ALL
    SELECT 3, c.table_name, c.column_id,
           'COMMENT ON COLUMN ' || c.table_name || '.' || c.column_name ||
           ' IS ''' || REPLACE(cc.comments, '''', '''''') || '''' || CHR(10) || '/'
    FROM   user_tab_columns c
           JOIN user_col_comments cc
                ON cc.table_name = c.table_name AND cc.column_name = c.column_name
           JOIN tgt t ON t.table_name = c.table_name
    WHERE  cc.comments IS NOT NULL
)
ORDER BY table_name, ord, sub;
