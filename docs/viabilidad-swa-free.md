# Viabilidad de despliegue en Azure Static Web Apps Free

> Actualización posterior: se implementaron las peticiones cortas, reintentos del navegador, runtime Python 3.11 y workflow manual. El estado actual y las comprobaciones están en [despliegue-swa-free.md](despliegue-swa-free.md). Las observaciones sobre cambios todavía no aplicados que aparecen debajo describen la revisión anterior; ODBC en Azure continúa sin verificar.

Revisión: 31 de octubre de 2026. Resultado: **preparación detenida por un bloqueo de tiempos y una dependencia nativa sin verificar**. No se ha creado un workflow ejecutable ni modificado la aplicación en esta revisión.

## Arquitectura propuesta y evidencia

Mantener frontend estático → API Python administrada por SWA → Azure SQL existente. No se requiere proponer una Function App independiente.

| Aspecto | Confirmado por documentación oficial | Pendiente de despliegue real |
| --- | --- | --- |
| SWA Free y API | Las APIs administradas están disponibles en todos los planes; las APIs externas enlazadas requieren Standard. [Microsoft: API](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-overview) | Construcción e indexación de nuestra API con decoradores |
| Python | La tabla específica de configuración enumera 3.8–3.11, con 3.8 fuera de soporte. Elegir **python:3.11**; 3.12+ no figura para SWA. [Microsoft: runtime](https://learn.microsoft.com/en-us/azure/static-web-apps/configuration#platform) | Imagen efectiva y carga de dependencias del proyecto |
| Aislamiento | Microsoft indica que las funciones administradas no están disponibles fuera de SWA. No ofrecen identidad administrada. [Microsoft: Functions administradas](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-functions) | Acceso real protegido por el gateway y conectividad SQL |
| GitHub y roles | GitHub preconfigurado y asignación de roles por invitación están disponibles en todos los planes. [Microsoft: autenticación](https://learn.microsoft.com/en-us/azure/static-web-apps/authentication-authorization) | Invitación aceptada por la cuenta real y rechazo de cuentas ajenas |

Hay una inconsistencia documental: la sección antigua de restricciones de Functions administradas se detiene en Python 3.10; esa misma página remite a la tabla de configuración, que incluye explícitamente 3.11. La elección de 3.11 se basa en esa tabla específica, no en extrapolar el soporte general de Azure Functions. La versión local observada anteriormente fue Python 3.14; pasar las pruebas allí no certifica Python 3.11.

## Bloqueo 1: máximo de 45 segundos

SWA fija un máximo de **45 segundos por petición de API**. [Microsoft: restricciones HTTP](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-overview#api-constraints).

El código actual permite cuatro conexiones de 10 segundos y esperas de 5 + 10 + 15: hasta 70 segundos nominales antes de añadir las consultas. Los 100 segundos de espera del navegador no amplían el límite del gateway. La observación anterior del README sobre estar por debajo del límite HTTP no es válida para SWA.

Corrección propuesta: distribuir la reactivación entre varias peticiones cortas. La API debe reservar margen bajo los 45 segundos para conexión, consultas, confirmación, cierre y cold start, devolver 503 con un indicador explícito de error transitorio cuando se agote su presupuesto y dejar que el frontend repita con esperas progresivas y límite global. No repetir automáticamente errores permanentes ni 401/403. En escrituras, preservar idempotencia y reconciliar el estado si se pierde una respuesta. Verificar tiempos con SQL suspendida. Un timeout de conexión aislado no es un presupuesto total de la petición.

## Bloqueo 2: pyodbc y ODBC Driver 18

`pyodbc` es un puente ODBC con extensión nativa: instalar el paquete Python no instala por sí solo el controlador de SQL Server. [Proyecto pyodbc](https://github.com/mkleehammer/pyodbc). Microsoft documenta por separado la instalación de `msodbcsql18`, el gestor ODBC y bibliotecas del sistema. [Microsoft: ODBC en Linux](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server).

**No he encontrado una garantía oficial de que la imagen administrada concreta de SWA Python incluya Driver 18 y todas sus bibliotecas. Tampoco hay evidencia de su ausencia.** Los ejemplos de Function Apps independientes y los drivers del runner de GitHub no prueban qué está instalado en la API publicada. Instalar paquetes con apt en el runner no modifica el sistema de ejecución de SWA.

Decisión: conservar pyodbc en el código local por ahora. Solo aprobarlo para Azure cuando una prueba protegida en el entorno real confirme importación, `pyodbc.drivers()` con Driver 18 y conexión TLS a SQL. Registrar únicamente versiones/nombres de driver, nunca credenciales. No crear un endpoint de diagnóstico anónimo.

Alternativa de menor coste de infraestructura: evaluar **mssql-python** dentro de la misma API administrada, sin recursos nuevos. Su instalación incluye los binarios ODBC y requiere Python 3.10+, pero Linux sigue necesitando bibliotecas como libltdl y Kerberos. No es una alternativa libre de dependencias nativas ni una compatibilidad SWA garantizada. [Microsoft: instalación](https://learn.microsoft.com/en-us/sql/connect/python/mssql-python/installation).

Si se adopta esa alternativa, cambiar imports, manejo de errores y parámetros de conexión/consulta según la API del driver, adaptar la cadena (sin selector Driver externo) y volver a probar transacciones, timeouts e idempotencia. No basta con renombrar el import. Si faltan también sus bibliotecas en SWA, detenerse y reevaluar un cliente TDS empaquetable antes de considerar recursos de pago.

## Cambios necesarios cuando se resuelvan los bloqueos

| Archivo | Cambio propuesto, todavía no aplicado |
| --- | --- |
| api/function_app.py | Presupuesto por petición compatible con 45 s y errores transitorios distinguibles; adaptar driver solo si se decide sustituirlo |
| frontend/index.html | Reintentos entre peticiones cortas, con límite global, preservando autorización e idempotencia |
| api/requirements.txt | Fijar versiones tras validarlas con Python 3.11/Linux y el driver elegido |
| frontend/staticwebapp.config.json | Añadir platform.apiRuntime = python:3.11 sin alterar las reglas propietario |
| api/tests/ y frontend/tests/ | Cubrir presupuesto, reactivación entre peticiones, errores permanentes y escrituras con respuesta perdida |
| .github/workflows/azure-static-web-apps.yml | Crear workflow manual; pruebas antes de publicar; empaquetado explícito y API administrada |
| api/.funcignore | Excluir local.settings.json, tests/, test_connection.py, __pycache__/, .venv/ y bytecode del paquete de API |

El workflow futuro debe usar `workflow_dispatch`, `permissions: contents: read`, checkout y pruebas con Python 3.11. Preparar una carpeta temporal con **solo** index.html, login.html, acceso-denegado.html y staticwebapp.config.json; esto deja las pruebas del frontend fuera del contenido publicado. Para `Azure/static-web-apps-deploy@v1`:

```yaml
with:
  azure_static_web_apps_api_token: ${{ secrets.AZURE_STATIC_WEB_APPS_API_TOKEN }}
  action: upload
  app_location: .swa-publish
  api_location: api
  output_location: ''
  skip_app_build: true
```

La construcción de la API debe permanecer habilitada. No copiar .venv ni paquetes compilados en WSL al artefacto. `actions/setup-python` configura las pruebas del runner; `platform.apiRuntime` selecciona la versión de la API. [Microsoft: build](https://learn.microsoft.com/en-us/azure/static-web-apps/build-configuration).

`staticwebapp.config.json` ya existe en la raíz de frontend. Con el empaquetado indicado se copiará a `.swa-publish/staticwebapp.config.json`, junto a index.html, y se comprobará su presencia antes de publicar. Microsoft exige conservarlo en la raíz de la salida. [Microsoft: ubicación](https://learn.microsoft.com/en-us/azure/static-web-apps/configuration#file-location).

## Secuencia futura de despliegue, no ejecutada

1. Corregir el presupuesto HTTP y validar dependencias con Python 3.11. Revisar los cambios; si se necesita evidencia cloud para ODBC, tratar el primer despliegue como validación protegida, no como compatibilidad ya acreditada.
2. Tras autorización explícita, crear únicamente SWA **Free** con API administrada; evitar asistentes que creen/publican un workflow automáticamente y no crear Function App separada ni Application Insights en este alcance.
3. En SWA → Settings → Environment variables → Production → Add, introducir `SQL_CONNECTION_STRING` con la cadena real; Apply y guardar. Es una variable del backend, no del build ni del frontend. Mantener cifrado y validación del certificado en la cadena. [Microsoft: variables](https://learn.microsoft.com/en-us/azure/static-web-apps/application-settings).
4. Verificar conectividad/firewall del SQL existente y permisos mínimos de la cuenta; no asumir que las IP del runner son las de la API ni abrir indiscriminadamente el servidor.
5. Guardar el token de despliegue de SWA en GitHub → Settings → Secrets and variables → Actions como `AZURE_STATIC_WEB_APPS_API_TOKEN`. No usar ahí la cadena SQL para empaquetarla. Preparar el workflow manual descrito y revisar el artefacto.
6. Solo con autorización posterior para commit/push/publicación, subir los cambios y ejecutar el workflow manual. Comprobar runtime y ODBC mediante registros o diagnóstico restringido al propietario; retirar el diagnóstico después.
7. En Role management de SWA, invitar la cuenta GitHub con rol `propietario` y aceptar la invitación. Verificar sesión cerrada, cuenta sin rol y propietario. No relajar reglas si hay fallos.
8. Probar las 13 tareas, marcado/desmarcado, recarga, histórico y reactivación natural de SQL dentro del límite HTTP. Si falla la carga del driver, detener la aceptación y evaluar mssql-python sin añadir recursos.

## Verificación del repositorio

Se ha inspeccionado git status, estructura, configuración, API y dependencias. Hay cambios locales previos y archivos sin seguimiento; no existe workflow de despliegue. Las 13 tareas y el modelo de datos no se han modificado.

Resultados: **7 pruebas Python + 3 JavaScript correctas**, `git diff --check` correcto. `git check-ignore` confirma la exclusión de Azurite, .venv, .env, local.settings.json y cachés. No aparecen esos archivos entre los versionados o candidatos no ignorados. Un escaneo básico de esos candidatos no detectó patrones de contraseñas literales, tokens GitHub o claves privadas; no equivale a una auditoría completa del historial.

En esta revisión solo se añade este informe y se aclara la documentación anterior sobre el límite HTTP. No se crea recurso, workflow activo, commit, push, merge ni despliegue. La implementación queda detenida según la restricción solicitada al encontrar el bloqueo.
