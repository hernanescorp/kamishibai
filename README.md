# Mi Kamishibai

Control diario de 13 tareas, todos los días del año. HTML/CSS/JavaScript nativos → Azure Functions Python → Azure SQL mediante `pyodbc`. SQL es la fuente de verdad: la recarga recupera los estados guardados, sin localStorage. Las duraciones son descriptivas, incluido el objetivo de 6 h de sueño.

## Estructura

- `frontend/index.html`: interfaz responsive, progreso, errores y reintento.
- `api/function_app.py`: endpoints y conexión con reintentos centralizados.
- `api/tests/test_api.py`: pruebas unitarias sin acceso a Azure.
- `api/test_connection.py`: comprobación manual de solo lectura.
- `database/inspect.sql`: inspección previa de estructura e histórico.
- `database/schema.sql`: creación/migración idempotente y catálogo de tareas.

## Configuración y migración

Usar Python 3.11 para coincidir con el runtime preparado de SWA, ODBC Driver 18 for SQL Server, Azure Functions Core Tools v4, Azurite y SWA CLI. Desde la raíz:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r api/requirements.txt
```

Crear `api/local.settings.json` localmente, con la cadena real exclusivamente en este archivo ignorado o en variables de entorno:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "SQL_CONNECTION_STRING": "<cadena de conexión local>"
  }
}
```

Antes de migrar, conectar con la herramienta SQL habitual y ejecutar `database/inspect.sql`. Revisar columnas, índices y datos; conservar una copia de seguridad. Después ejecutar manualmente `database/schema.sql` en esa misma base. La aplicación no ejecuta DDL al arrancar.

El esquema conocido del MVP contiene `id`, `valor` y `fecha DATETIME`. Esos CHECK no permiten identificar una tarea: el script renombra la tabla a `kamishibai.registros_legacy` y conserva íntegros sus IDs, valores y fechas originales, sin reinterpretar la zona horaria. Crea la nueva tabla con fecha lógica, timestamp UTC, FK y UNIQUE `(id_tarea, fecha)`. No borra tablas ni el archivo histórico. En ejecuciones posteriores no duplica el catálogo ni vuelve a archivar. Si ya existe una tabla legacy y otra tabla antigua pendiente, aborta para revisión manual. Una estructura distinta de la del MVP debe revisarse antes de aplicar este script.

La inspección remota de solo lectura confirmó las columnas `id INT NOT NULL`, `valor INT NOT NULL` y `fecha DATETIME NOT NULL`, con 24 registros existentes. La primera conexión agotó el timeout y la siguiente comprobación pudo conectar. La migración fue aplicada manualmente por el propietario, que confirmó marcado, desmarcado y persistencia al recargar.

## Desarrollo local

Abrir tres terminales desde la raíz:

```bash
azurite --location .azurite
```

```bash
source .venv/bin/activate
cd api
func start
```

```bash
swa start frontend --api-devserver-url http://localhost:7071
```

Web: `http://localhost:4280`. Acceder a través de SWA para que la API reciba la identidad. El acceso directo a `http://localhost:7071/api/tareas` sin principal devuelve 401.

### Iniciar sesión en local

1. Abrir `http://localhost:4280/` y pulsar «Entrar con GitHub».
2. SWA CLI muestra su formulario de autenticación simulada: introducir un User ID y un nombre de usuario ficticios.
3. Añadir `propietario` en **User's roles** (una línea). El emulador añade `authenticated` automáticamente.
4. Completar el formulario para volver a la aplicación. «Cerrar sesión» termina la sesión local.

Esta pantalla simula identidades y no verifica credenciales de GitHub. Utilizar el emulador solo para desarrollo local. Para comprobar el bloqueo, iniciar sesión sin `propietario`: debe aparecer «Acceso restringido».

## API y fechas

- `GET /api/tareas`: `{fecha, tareas}` con ID, hora, nombre, duración en minutos, completado y timestamp UTC ISO 8601 (`Z`), ordenadas por hora.
- `POST /api/check`: `{"id_tarea":1,"completado":true}` marca; `false` desmarca. Devuelve el estado confirmado y la fecha. Operaciones idempotentes, SQL parametrizado y bloqueo de rango más restricción UNIQUE para evitar duplicados concurrentes.
- Respuestas: 200 correcto, 400 JSON o campos inválidos, 404 tarea inexistente/inactiva, 503 indisponibilidad temporal agotada, 500 configuración o error SQL permanente. Los errores no exponen cadenas de conexión.

El backend calcula el día en `Europe/Madrid` después de conectar, también tras reintentos. Los timestamps se guardan en UTC. Desmarcar solo elimina el registro de ese día. La interfaz comprueba el cambio de día cada 15 segundos y al volver a la pestaña; recarga sin borrar el histórico. El checkbox queda pendiente hasta confirmación y recupera su estado anterior ante un fallo. «Reintentar» consulta de nuevo SQL, también para reconciliar una escritura cuya respuesta se haya perdido.

## Reactivación de Azure SQL

Cada petición abre una conexión nueva, con timeout de conexión de 5 s y de consulta de 3 s. No hay reintentos ni esperas dentro de esa petición. Antes del commit se comprueba un presupuesto de 20 s. Los timeouts nativos no garantizan un límite absoluto de pared: falta medir cold start y ODBC en Azure.

Los fallos temporales devuelven 503 con `transitorio: true`. El navegador hace hasta tres reintentos entre peticiones, con esperas de 5, 10 y 15 s, un límite global de 90 s y de 25 s por fetch. En una escritura reserva 15 s para consultar el estado si no puede confirmar la respuesta. No reenvía automáticamente POST ante una pérdida de red, ni repite una escritura del día anterior después de medianoche. Si no puede reconciliar el estado, bloquea las casillas hasta recuperar SQL con Reintentar. No hay keep-alive ni funciones programadas.

## Verificación

```bash
.venv/bin/python -m unittest discover -s api/tests -v
.venv/bin/python api/test_connection.py
node --test frontend/tests/ui.test.cjs
```

Las pruebas unitarias usan dobles de SQL: validan JSON, carga y serialización de tareas, marcado/desmarcado, repetición idempotente, histórico, fecha de Madrid en verano/invierno, un intento SQL por petición, presupuesto antes de commit y errores permanentes. Las pruebas de interfaz simulan el servidor; no sustituyen una prueba contra SQL real.

Tras migrar, verificar en local: 13 tareas en orden, marcar, recargar y comprobar persistencia, repetir la misma petición sin duplicados, desmarcar y volver a recargar. Comprobar que los CHECK anteriores permanecen en `registros_legacy`. Para el cambio de día, abrir la web durante la medianoche de Madrid y comprobar que las nuevas casillas aparecen vacías y los registros del día anterior siguen en SQL. Tras una suspensión natural, abrir la web y observar la recuperación automática o el error con «Reintentar».

## Autenticación y preparación de Azure

`frontend/staticwebapp.config.json` exige el rol `propietario` tanto en `/api/*` como en el resto de la web. Solo las páginas de acceso y error son públicas. Se usa GitHub, proveedor preconfigurado incluido en el plan Free; el inicio de sesión con Microsoft está deshabilitado. No hay contraseñas propias ni secretos nuevos en el repositorio. Las respuestas 401 muestran el acceso y las 403 explican la falta de permisos. La interfaz permite cerrar sesión y redirige si la sesión deja de autorizar las peticiones.

La API también comprueba `x-ms-client-principal`: requiere ID de usuario, proveedor GitHub y roles `authenticated` y `propietario` antes de abrir SQL. Functions conserva `AuthLevel.ANONYMOUS` porque SWA gestiona la sesión; ese ajuste no sustituye las reglas y comprobaciones anteriores. No se omite autenticación por variables de desarrollo.

**Límite de confianza:** el principal es una cabecera codificada en base64, no un token firmado que la API pueda verificar de manera independiente. En producción debe usarse la API administrada de Static Web Apps, accesible a través de su gateway, que controla las cabeceras de identidad. No publicar esta Function como backend independiente abierto: un cliente podría falsificar esa cabecera. Si se utiliza una Function App separada, antes hay que configurar su integración y restricciones de acceso para impedir el acceso directo; la cabecera por sí sola no la protege.

Al crear el recurso en Azure, sin desplegar todavía desde esta sesión:

1. Elegir plan Free, frontend `frontend` y API administrada `api`. Incluir `staticwebapp.config.json` en la raíz del contenido publicado.
2. Configurar `SQL_CONNECTION_STRING` como secreto del recurso, sin subir `local.settings.json`.
3. En **Role management / Administración de roles**, crear una invitación para la cuenta GitHub del propietario y el rol `propietario`; aceptar la invitación usando esa cuenta. No asignar ese rol a otras cuentas.
4. Verificar con sesión cerrada que web y API están bloqueadas; con otra cuenta que responden con acceso denegado; y con la cuenta autorizada que cargar, marcar y desmarcar funciona.
5. Comprobar HTTPS, integración Python/ODBC y que no existe una URL pública alternativa que permita saltarse SWA.

Las pruebas de backend cubren principal ausente, malformado, sin ID, rol incorrecto y proveedor incorrecto, sin tocar SQL. El emulador verifica las reglas de ruta con identidades simuladas; la autenticación real y la asignación del rol requieren el recurso Azure. Este trabajo no incluye despliegue, push ni creación de recursos.

Referencias: [autenticación integrada](https://learn.microsoft.com/en-us/azure/static-web-apps/authentication-authorization), [reglas de acceso](https://learn.microsoft.com/en-us/azure/static-web-apps/configuration), [principal de usuario](https://learn.microsoft.com/en-us/azure/static-web-apps/user-information), [emulación local](https://azure.github.io/static-web-apps-cli/docs/cli/local-auth/).

## Informe previo al despliegue

Estado, evidencias y pendientes: [informe del 31 de octubre de 2026](docs/informe-previo-despliegue.md).

Revisión documental para SWA Free, bloqueos y secuencia de despliegue: [viabilidad técnica](docs/viabilidad-swa-free.md).

## Publicación manual preparada

El workflow solo se ejecuta manualmente y no se ha ejecutado. Incluye pruebas con Python 3.11 y empaquetado por lista permitida; no publica secretos, pruebas ni archivos locales. Consulta [preparación, límites y pasos para publicar](docs/despliegue-swa-free.md). ODBC Driver 18 en la API administrada sigue pendiente de evidencia real.
