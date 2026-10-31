IF SCHEMA_ID(N'kamishibai') IS NULL
    EXEC(N'CREATE SCHEMA kamishibai');

CREATE TABLE kamishibai.registros (
    id INT IDENTITY(1,1) PRIMARY KEY,
    valor INT NOT NULL,
    fecha DATETIME NOT NULL DEFAULT GETDATE()
)

