# Informe de estado de Kamishibai antes del despliegue

> Actualización posterior: se implementaron las peticiones cortas, reintentos del navegador, runtime Python 3.11 y workflow manual. El estado actual y las comprobaciones están en [despliegue-swa-free.md](despliegue-swa-free.md). Las observaciones sobre cambios todavía no aplicados que aparecen debajo describen la revisión anterior; ODBC en Azure continúa sin verificar.

> Actualización: la [revisión documental de SWA Free](viabilidad-swa-free.md) confirma un límite de 45 segundos por petición. Los reintentos actuales necesitan adaptación antes de publicar; ODBC Driver 18 en la imagen administrada sigue sin verificar.

Fecha: 31 de octubre de 2026 · Entorno de desarrollo: WSL Ubuntu · Zona funcional: Europe/Madrid.

## 1. Evaluación general

La aplicación funciona en desarrollo local y dispone de autenticación preparada para Azure Static Web Apps (SWA). El propietario confirmó manualmente el marcado, desmarcado y la persistencia después de recargar, utilizando Azure SQL.

El estado actual permite preparar el despliegue, pero todavía no acredita funcionamiento en producción. Deben resolverse y verificarse la integración de la API Python con SWA, la disponibilidad del driver ODBC en el entorno cloud y la asignación real del rol de acceso. No se ha realizado push, merge ni despliegue durante este trabajo.

## 2. Arquitectura actual

| Componente | Implementación | Estado |
| --- | --- | --- |
| Interfaz | HTML, CSS y JavaScript nativos | Implementada y probada localmente |
| Servidor local web | Azure Static Web Apps CLI, puerto 4280 | Utilizado en las comprobaciones |
| API | Azure Functions Python, puerto local 7071 | Implementada y probada localmente |
| Acceso a datos | pyodbc y SQL parametrizado | Funciona en el entorno local |
| Base de datos | Azure SQL, esquema kamishibai | Persistencia confirmada por el propietario |
| Servicios locales de almacenamiento | Azurite | Utilizado para Functions |
| Identidad | GitHub preconfigurado en SWA y rol propietario | Configuración implementada; identidad simulada en local |

No se ha introducido un framework de frontend, ORM, Docker ni servicios adicionales. No se utiliza localStorage como fuente de datos de las tareas.

## 3. Funcionalidad entregada

- Catálogo SQL con las 13 tareas, nombres y horarios especificados, todos los días.
- Duraciones informativas, sin temporizadores ni restricciones por solapamiento. «Horas sueño» es un checkbox.
- Lista ordenada cronológicamente, fecha visible e indicador de completadas sobre 13.
- Marcado y desmarcado con confirmación del servidor; control deshabilitado mientras se procesa su petición.
- Recuperación del estado desde SQL al recargar y mensajes de error con reintento.
- Día lógico calculado por el backend en Europe/Madrid; instantes de completado almacenados en UTC.
- Comprobación del cambio de día cada 15 segundos y al recuperar visibilidad, sin borrar el histórico.

El paso real por medianoche y los cambios de horario de verano no se han observado de extremo a extremo en una sesión real: la lógica tiene cobertura mediante simulaciones y pruebas de fechas.

## 4. Datos y migración

La inspección remota inicial de solo lectura confirmó la estructura antigua de `kamishibai.registros`: `id INT`, `valor INT` y `fecha DATETIME`, con 24 filas en ese momento.

El script `database/schema.sql` prepara una migración transaccional e idempotente:

1. Renombra la tabla antigua a `kamishibai.registros_legacy`, conservando los CHECK sin inventar asociaciones a tareas.
2. Crea `kamishibai.maestro_tareas` y carga las 13 tareas sin duplicarlas en ejecuciones posteriores.
3. Crea la nueva `kamishibai.registros` con ID identity, tarea, fecha lógica y timestamp UTC.
4. Añade clave foránea y unicidad de `(id_tarea, fecha)`.

El propietario ejecutó manualmente el script y confirmó posteriormente el funcionamiento con persistencia. No se ha vuelto a contar el contenido de `registros_legacy` en esta revisión: confirmar la conservación de esas 24 filas es una comprobación pendiente. El script es una migración desde la estructura conocida del MVP, no un migrador genérico para cualquier variante del esquema.

`database/inspect.sql` permite revisar columnas, índices y datos antes de nuevas intervenciones. `api/test_connection.py` se ha convertido en una comprobación de solo lectura.

## 5. API y recuperación de SQL

| Endpoint | Operación | Autorización |
| --- | --- | --- |
| GET /api/tareas | Devuelve fecha y tareas activas con sus estados | GitHub + authenticated + propietario |
| POST /api/check | Marca o desmarca una tarea del día calculado en el servidor | GitHub + authenticated + propietario |

Se validan JSON, tipos e identificadores. Las consultas son parametrizadas. El marcado utiliza inserción condicional con bloqueo de rango y una restricción UNIQUE para evitar duplicados. El desmarcado afecta exclusivamente a la tarea y fecha actuales.

La conexión reutiliza una única función con un máximo de cuatro intentos y esperas de 5, 10 y 15 segundos. Se abre una conexión nueva en cada intento y se cierra al terminar. Se reintentan errores conocidos de conexión, disponibilidad, throttling y deadlock; los errores permanentes de autenticación, configuración y SQL fallan sin esos reintentos.

La conexión y las consultas tienen timeout de 10 segundos. El navegador limita la espera a 100 segundos. Estos valores no constituyen una garantía estricta del tiempo total del driver: deben contrastarse con el límite HTTP efectivo de SWA y Functions en el despliegue. No se han añadido tareas programadas para mantener SQL despierto.

La primera inspección remota agotó el timeout y una comprobación posterior conectó. Esto es compatible con el comportamiento descrito de reactivación, pero no demuestra por sí solo que el fallo se debiera a suspensión. La recuperación tras tres fallos y el agotamiento de intentos se han probado con errores simulados; queda pendiente observar una suspensión natural en el entorno publicado.

## 6. Autenticación y límites de seguridad

`frontend/staticwebapp.config.json` protege la web y `/api/*` con el rol `propietario`. Las páginas de acceso y acceso denegado son públicas. La interfaz ofrece inicio de sesión con GitHub y cierre de sesión; Microsoft no está habilitado como alternativa de acceso en esta configuración.

Además, ambos endpoints comprueban el principal enviado por SWA antes de acceder a SQL. Sin sesión válida se rechaza la petición; una identidad sin rol no puede consultar ni modificar tareas. La comprobación se probó localmente con identidades simuladas.

El principal `x-ms-client-principal` está codificado en base64 y no es una firma verificable por este código. La seguridad depende de que la API se publique tras el gateway de SWA y no exista acceso público independiente que permita falsificar esa cabecera. Una Function App separada y abierta no queda protegida únicamente por este código. `AuthLevel.ANONYMOUS` se conserva para la integración con SWA y no debe interpretarse como autorización pública de uso.

No hay bypass de autenticación habilitado para desarrollo. El emulador permite simular usuarios y roles, por lo que debe utilizarse exclusivamente como herramienta local.

Se han añadido cabeceras de no almacenamiento en caché, prevención de interpretación incorrecta del tipo de contenido y política de referrer del mismo origen.

La configuración usa un proveedor preconfigurado, sin autenticación personalizada ni contraseñas propias. El coste total futuro depende también del plan de alojamiento, SQL y servicios asociados; este informe no certifica una factura global de cero euros.

## 7. Configuración y secretos

La conexión se obtiene de `SQL_CONNECTION_STRING`. En desarrollo puede residir en `api/local.settings.json`, excluido de Git. También se ignoran `.azurite/`, `.venv/`, `.env`, variantes de `.env`, `__pycache__/` y bytecode Python.

Antes de subir cambios se debe revisar el contenido que vaya a incluirse en el commit. Las reglas de ignore no eliminan secretos que pudieran existir en el historial anterior; no se ha realizado una auditoría completa del historial Git.

## 8. Verificación de esta revisión

Se han vuelto a ejecutar:

```bash
.venv/bin/python -m unittest discover -s api/tests -q
node --test frontend/tests/ui.test.cjs
git diff --check
```

Resultado: **7 pruebas Python y 3 pruebas JavaScript correctas; sin errores de whitespace en el diff**.

La cobertura incluye validación de peticiones, autorización antes de SQL, serialización y carga, marcado y desmarcado, idempotencia e histórico mediante doble de base de datos, fechas de Madrid, reintentos y errores permanentes, confirmación visual, recarga, fallo/reintento, cambio de día y redirecciones por pérdida de autorización.

En comprobaciones HTTP locales de la implementación de autenticación se observó:

- Web sin sesión: página de acceso, sin la interfaz de tareas.
- API sin sesión: 401; API directa sin principal: 401.
- Cuenta simulada sin permiso: petición rechazada.
- Cuenta simulada propietaria: web accesible y API con las 13 tareas.

Las pruebas JavaScript utilizan un DOM simulado, no un navegador completo. Las pruebas Python utilizan dobles de SQL, por lo que no acreditan por sí solas las restricciones o bloqueos concurrentes de SQL Server. La prueba manual del propietario aporta la evidencia real de persistencia.

## 9. Pendientes antes de publicar

| Prioridad | Pendiente | Criterio de cierre |
| --- | --- | --- |
| Imprescindible | Confirmar entorno cloud Python y ODBC | API desplegada importa pyodbc, dispone del driver requerido y conecta a SQL sin añadir infraestructura innecesaria |
| Imprescindible | Confirmar modalidad de API y límite de confianza | Gateway de SWA protege el backend y no hay vía pública alternativa que acepte principales falsificados |
| Imprescindible | Preparar configuración de despliegue | frontend y api correctos, versión Python elegida y staticwebapp.config.json incluido en la raíz publicada |
| Imprescindible | Configurar secreto y conectividad SQL | Cadena en configuración de Azure, permisos y acceso de red necesarios verificados |
| Imprescindible | Asignar rol a la cuenta real | Invitación GitHub aceptada con propietario; otra cuenta no obtiene acceso |
| Imprescindible | Prueba publicada de autorización y persistencia | Sesión cerrada y cuenta ajena bloqueadas; propietario carga, marca, recarga y desmarca |
| Pendiente de validación | Confirmar archivo del MVP | registros_legacy conserva las 24 filas iniciales |
| Pendiente de validación | Medir reactivación de SQL y límites HTTP | Recuperación o error comprensible tras suspensión natural, sin peticiones indefinidas |
| Pendiente de validación | Observar medianoche de Madrid | Nuevo día vacío, conservando registros de días anteriores |
| Antes del push | Revisar diff y archivos del commit | Sin credenciales ni archivos locales; cambios revisados y autorización de publicación |

No existe todavía un workflow de despliegue en los archivos revisados. `api/requirements.txt` declara azure-functions y pyodbc sin versiones fijadas; elegir versiones compatibles y reproducibles forma parte de preparar el entorno cloud.

## 10. Estado de Git y siguiente paso

Hay modificaciones locales y archivos nuevos de API, interfaz, pruebas y documentación. No se ha creado un commit durante este trabajo ni se ha hecho push o despliegue. La migración de SQL fue una acción manual del propietario.

El siguiente paso es resolver la compatibilidad de la API Python/ODBC con el alojamiento elegido y preparar la configuración concreta de despliegue para revisión. Después se podrá autorizar la publicación y completar las comprobaciones que requieren un recurso Azure real.
