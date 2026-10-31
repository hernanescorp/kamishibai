-- Ejecutar manualmente sobre la base existente. No contiene credenciales.
-- Los CHECK del MVP no tienen tarea asociada: se archivan íntegros, sin inferirla.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF SCHEMA_ID(N'kamishibai') IS NULL EXEC(N'CREATE SCHEMA kamishibai');
IF OBJECT_ID(N'kamishibai.registros', N'U') IS NOT NULL
   AND COL_LENGTH(N'kamishibai.registros', N'id_tarea') IS NULL
BEGIN
    IF OBJECT_ID(N'kamishibai.registros_legacy', N'U') IS NOT NULL
        THROW 50001, 'Ya existe registros_legacy. Revisar manualmente antes de migrar.', 1;
    EXEC sp_rename N'kamishibai.registros', N'registros_legacy';
END;
IF OBJECT_ID(N'kamishibai.maestro_tareas', N'U') IS NULL
BEGIN
    CREATE TABLE kamishibai.maestro_tareas (
        id_tarea INT NOT NULL PRIMARY KEY,
        hora TIME NOT NULL,
        nombre NVARCHAR(200) NOT NULL,
        duracion_minutos INT NULL,
        activo BIT NOT NULL DEFAULT 1
    );
END;
IF OBJECT_ID(N'kamishibai.registros', N'U') IS NULL
BEGIN
    CREATE TABLE kamishibai.registros (
        id INT IDENTITY(1,1) PRIMARY KEY,
        id_tarea INT NOT NULL REFERENCES kamishibai.maestro_tareas(id_tarea),
        fecha DATE NOT NULL,
        timestamp_completado DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_registros_tarea_fecha UNIQUE (id_tarea, fecha)
    );
END;
-- SQL dinámico permite compilar después de renombrar la tabla antigua.
EXEC sp_executesql N'
INSERT INTO kamishibai.maestro_tareas (id_tarea, hora, nombre, duracion_minutos)
SELECT v.id, v.hora, v.nombre, v.duracion
FROM (VALUES
 (1, ''05:30'', N''Levantarse'', NULL),
 (2, ''06:00'', N''Desayunar'', 30),
 (3, ''06:30'', N''Ordenar Habitación'', NULL),
 (4, ''07:00'', N''Horas sueño'', 360),
 (5, ''08:00'', N''Entrenamiento'', NULL),
 (6, ''14:00'', N''Comer y Lavar Platos'', 60),
 (7, ''18:00'', N''Emprendimiento'', 60),
 (8, ''19:00'', N''Estudio Idiomas'', 120),
 (9, ''20:00'', N''Estudio y Portfolio'', 180),
 (10, ''21:00'', N''Cenar'', 30),
 (11, ''21:30'', N''Calendario, Agenta y Correos'', NULL),
 (12, ''22:00'', N''Preparar maleta deporte y Dispositivos'', NULL),
 (13, ''23:00'', N''Dormir'', NULL)
) v(id, hora, nombre, duracion)
WHERE NOT EXISTS (SELECT 1 FROM kamishibai.maestro_tareas t WHERE t.id_tarea=v.id);';
COMMIT TRANSACTION;
