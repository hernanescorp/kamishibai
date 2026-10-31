# Preparación y publicación manual en SWA Free

Actualizado el 31 de octubre de 2026. Preparación implementada; **no se ha desplegado ni creado ningún recurso**. Se mantienen el modelo de datos y las 13 tareas.

## Comportamiento HTTP preparado

La API hace un único intento SQL por petición, sin sleeps: timeout de conexión de 5 segundos y timeout de consulta de 3 segundos. Una lectura ejecuta una consulta; una escritura, hasta tres. El presupuesto nominal de la operación más costosa es 5 + 3 × 3 = 14 segundos antes de commit/cierre. Se comprueba un presupuesto de 20 segundos antes de confirmar la transacción; si se agotó, se cierra sin commit y se devuelve un error transitorio. El cierre de una conexión no confirmada revierte su transacción.

Estas medidas dejan margen frente a los 45 segundos del gateway SWA en funcionamiento normal. Los timeouts del driver no son una garantía de tiempo de pared para DNS, TLS, commit, cierre o cold start. Un driver bloqueado no puede cancelarse de forma fiable mediante un temporizador de JavaScript ni con la comprobación de presupuesto posterior: medir el caso real en Azure sigue siendo necesario. No se afirma un límite estricto de 20 segundos para todo el runtime.

Un error reconocido como temporal devuelve HTTP 503 y `transitorio: true`. Los errores permanentes no llevan una señal positiva de reintento. El navegador repite solo esos 503, como máximo tres veces, tras 5, 10 y 15 segundos. No reintenta automáticamente 400, 401, 403, 404, 500, 503 sin señal, fallos de red ni respuestas no interpretables.

El límite global de una operación visible es 90 segundos y el de cada fetch es 25 segundos, acortado por el presupuesto restante. En escrituras se reservan 15 segundos del presupuesto global para recuperar el estado con GET si no se pudo confirmar la respuesta. Las peticiones se realizan secuencialmente, sin modificaciones paralelas desde la interfaz. Un POST repetido conserva su cuerpo y solo se repite mientras sigue siendo el mismo día de Madrid; la fecha efectiva siempre la decide el backend.

Ante una respuesta perdida, se consulta automáticamente el estado real; no se reenvía a ciegas una escritura por un fallo de red. Si tampoco puede recuperarse, las casillas quedan deshabilitadas y el botón Reintentar vuelve a cargar SQL. El GET puede confirmar tanto un cambio aplicado como uno no aplicado. El comportamiento idempotente de SQL se conserva sin alterar tablas ni tareas.

## Archivos de preparación

- `.github/workflows/azure-static-web-apps.yml`: solo `workflow_dispatch`, sin ejecución por push ni PR; permisos de lectura, pruebas previas y despliegues serializados.
- `scripts/prepare_deployment.py`: genera `.swa-publish/` desde una lista explícita, limpiando restos previos. No copia carpetas completas.
- `frontend/staticwebapp.config.json`: runtime `python:3.11`; conserva las reglas `propietario` y autenticación GitHub.
- `api/requirements.txt`: azure-functions 1.25.0 y pyodbc 5.3.0, compatibles con Python 3.11 según resolución de paquetes y pruebas locales.
- `api/.funcignore`: excluye configuración local, entornos virtuales, pruebas, cachés y otros archivos locales como defensa adicional.
- `.gitignore`: excluye además el paquete temporal `.swa-publish/`.

El frontend publicado contiene únicamente index.html, login.html, acceso-denegado.html y staticwebapp.config.json. La configuración queda en la raíz publicada, junto a index.html. La API enviada al builder contiene únicamente function_app.py, host.json, requirements.txt y .funcignore. No se incluye local.settings.json, Azurite, .venv, SQL scripts, informes ni pruebas. La construcción de la API por SWA permanece habilitada; no se suben paquetes compilados en WSL.

El workflow instala unixODBC en el runner para importar pyodbc durante las pruebas. **Eso no instala ODBC Driver 18 en la API de Azure**. No hay prueba de conexión SQL en CI ni se necesita la cadena SQL en GitHub para ejecutar las pruebas.

## Comprobaciones locales realizadas

Se creó un entorno aislado temporal con Python 3.11 y las dependencias fijadas. Se resolvieron wheels para CPython 3.11/Linux. Resultado: **9 pruebas Python y 11 JavaScript correctas**, generación del paquete y `git diff --check` correctos.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r api/requirements.txt
python -m unittest discover -s api/tests -v
node --test frontend/tests/ui.test.cjs
python scripts/prepare_deployment.py
git diff --check
```

Si ya existe una .venv de otra versión, usar un directorio separado para Python 3.11. El entorno temporal utilizado en esta revisión está fuera del repositorio. Las pruebas no acceden a Azure; el DOM y SQL se simulan. El archivo manual `api/test_connection.py` no se ejecuta como parte de la suite, para evitar conexiones reales no necesarias.

## Pasos que quedan para publicar, con autorización posterior

1. Revisar y autorizar commit y push de los cambios. No se han realizado. El workflow debe estar en la rama por defecto para aparecer en GitHub como ejecución manual. Mantenerlo manual para evitar publicaciones por sorpresa.
2. Autorizar la creación de un recurso **Azure Static Web Apps Free** con API administrada. No crear Function App independiente, ni Application Insights ni servicios de pago en este alcance. Evitar la conexión del asistente que cree o ejecute otro workflow automáticamente; usar configuración de despliegue manual/Other cuando corresponda.
3. Obtener el token de despliegue de SWA y guardarlo en GitHub → Settings → Secrets and variables → Actions → New repository secret, nombre `AZURE_STATIC_WEB_APPS_API_TOKEN`. No incluir el token en archivos ni mensajes.
4. En Azure → SWA → Settings → Environment variables → Production → Add, crear `SQL_CONNECTION_STRING`, pegar la cadena real y guardar con Apply. Usar cifrado y validación del certificado. La variable pertenece exclusivamente al backend; no añadirla al frontend ni al YAML. No subir local.settings.json.
5. Revisar permisos y firewall del SQL existente para la conectividad de la API; no asumir que la IP del runner es la IP de ejecución ni abrir acceso indiscriminado.
6. Autorizar y ejecutar GitHub → Actions → Validate and deploy Kamishibai manually → Run workflow. El workflow utiliza `.swa-publish/frontend` y `.swa-publish/api`; no requiere un recurso Functions separado.
7. En SWA → Role management, invitar la cuenta GitHub autorizada con rol `propietario` y aceptar la invitación con esa cuenta. Verificar rechazo sin sesión y con una cuenta sin rol. No relajar las reglas para depurar fallos.
8. Validar en la API administrada importación de pyodbc, disponibilidad de ODBC Driver 18 y conexión TLS con SQL mediante diagnóstico restringido/logs que no revelen secretos. Retirar cualquier diagnóstico temporal. Esta comprobación sigue pendiente y puede bloquear la aceptación del despliegue.
9. Comprobar carga de las 13 tareas, marcado/desmarcado, recarga, conservación de histórico y reactivación de SQL suspendida. Medir peticiones y verificar errores comprensibles antes de los límites del gateway.

Si falta el driver o una biblioteca nativa, no afirmar que el despliegue funciona: evaluar mssql-python dentro de la misma API administrada y sus dependencias, manteniendo autenticación y sin añadir recursos. La API solo debe publicarse mediante el gateway de SWA; la cabecera base64 de identidad no protege una Function App independiente expuesta.

La documentación oficial y la evidencia pendiente de ODBC están recogidas en [viabilidad-swa-free.md](viabilidad-swa-free.md). No se han creado recursos Azure ni ejecutado workflows, commit, push, merge o despliegues durante esta preparación.
