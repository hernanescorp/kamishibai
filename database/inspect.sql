-- Solo lectura: ejecutar antes de schema.sql y revisar los resultados.
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'kamishibai' AND TABLE_NAME = 'registros'
ORDER BY ORDINAL_POSITION;
SELECT i.name, i.is_unique, c.name AS columna
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
WHERE i.object_id=OBJECT_ID(N'kamishibai.registros');
IF OBJECT_ID(N'kamishibai.registros', N'U') IS NOT NULL
BEGIN
    SELECT COUNT_BIG(*) AS registros_existentes FROM kamishibai.registros;
    SELECT TOP (20) * FROM kamishibai.registros ORDER BY id;
END;
