# Drop Alerts

Servicio de alertas para **Magic: The Gathering, One Piece Card Game y Pokémon TCG**, con adaptadores independientes, estado en SQLite, cola persistente y notificaciones por webhook de Discord. Vigila anuncios, productos y promociones oficiales, además de calendarios de torneos de tiendas de Madrid y alrededores. Conserva la integración de Secret Lair y Chaos Vault. El modelo remoto interpreta contenido ambiguo; el código conserva la autoridad sobre consultas, fechas, precios, disponibilidad, reglas, deduplicación y envíos.

El contenedor usa Python 3.12 slim, un único servicio y un volumen. No publica puertos y no incluye ningún modelo, navegador ni servidor de inferencia.

El estado de esta entrega y las comprobaciones realizadas están en [verificación](docs/verification.md). Si recibes el proyecto como ZIP, extráelo como `drop-alerts` y entra en esa carpeta en lugar de ejecutar `git clone`.

Consulta la [cobertura actual, fuentes y configuración por juego](docs/multi-tcg.md). La [guía de anuncios de Magic](docs/announcement-sources.md) y la [investigación ampliada](docs/source-expansion-research.md) conservan el detalle de la integración original; que una fuente aparezca investigada no significa que esté activada.

## Arranque con Docker

El stack construye la imagen desde el código del repositorio mediante `build:`. En Portainer utiliza **Stacks → Add stack → Repository**, con la rama `refs/heads/main` y la ruta `docker-compose.yml`. El repositorio es privado: configura el acceso Git que utilices para tus otros repositorios privados. Este despliegue no requiere credenciales de un registro de imágenes.

Para desplegar desde una terminal en el equipo que ejecuta Docker —la VM o el LXC de Proxmox donde se conecta Portainer—:

```sh
git clone https://github.com/gonibix23/drop-alerts.git
cd drop-alerts
cp .env.example .env
# Editar .env y configurar DISCORD_WEBHOOK_URL.
docker compose up -d --build
docker compose logs --tail=100 -f
```

La primera comprobación correcta de cada fuente establece una referencia silenciosa (`BOOTSTRAP_MODE=silent`). Las siguientes comprobaciones generan eventos por novedades y cambios reales. Un fallo de extracción conserva el estado anterior; que un producto no aparezca en una lista no demuestra que esté agotado.

Para Portainer, usa el repositorio `https://github.com/gonibix23/drop-alerts.git`, configura `DISCORD_WEBHOOK_URL` en las variables del stack y despliega. El modo Repository obtiene el Dockerfile y el código necesarios para construir; pegar solamente el YAML en Web editor no aporta esos archivos. La variable antigua `DROP_ALERTS_IMAGE` ya no se utiliza en el Compose predeterminado y puedes eliminarla. La imagen privada de GHCR se conserva como alternativa opcional; el procedimiento completo, actualización y copias de seguridad están en [la guía de despliegue](docs/deployment.md).

Para actualizar un stack existente en Portainer, abre el stack creado desde Repository y utiliza **Pull and redeploy** para obtener `main`, con reconstrucción de la imagen desde `docker-compose.yml`. Conserva el volumen `drop_alerts_data`: la ampliación a varios TCG mantiene el esquema SQLite 2 y las identidades anteriores de Magic. Mantén `BOOTSTRAP_MODE=silent`; cada fuente nueva establece su referencia sin avisos históricos. Si montas un TOML antiguo, incorpora los nuevos bloques de fuentes y reglas desde el ejemplo: ese archivo sustituye las listas predeterminadas, y una fuente ausente no se activa automáticamente.

## Fuentes y Discord

Hay **14 fuentes activadas por defecto y 26 adaptadores registrados**. Los intervalos concretos y las fuentes opcionales figuran en [la guía multijuego](docs/multi-tcg.md).

| Cobertura activa | Fuentes |
| --- | --- |
| Magic · 7 | Secret Lair EU, Chaos Vault EU, noticias de Magic, Bluesky oficial de Secret Lair, WPN, MagicCon y WeeklyMTG |
| One Piece · 2 | Catálogo oficial occidental y anuncios/promociones oficiales de Bandai |
| Pokémon · 2 | Noticias del portal oficial del JCC y prensa oficial en español |
| Torneos locales · 3 | Donde Jugar TCG para seis tiendas cercanas, Mundicomics y Gladius Games |

Las tres fuentes locales cubren inicialmente **ocho tiendas**. El [inventario de las 25 tiendas del chat compartido](docs/local-stores-coverage.json) distingue los calendarios comprobados de los perfiles activados. Madrid, Algete y Guadalajara tienen ampliaciones opcionales; las redes sociales de las tiendas no se rastrean.

Las tarjetas de Discord muestran juego, región, idioma de la fuente, canal, tipo de evento, título enlazado y una imagen cuando procede de la fuente. Los anuncios de One Piece para Occidente incluyen Europa, pero un MSRP en dólares no se presenta como precio europeo. Las noticias de Pokémon en español tienen alcance global: el idioma no demuestra stock en España. Los mercados de Japón y Estados Unidos permanecen separados. Un anuncio no prueba que un producto ya esté a la venta. Las menciones están desactivadas.

Puedes abrir la [vista previa multijuego](docs/multi-tcg-preview.html) o consultar su [JSON de ejemplo](docs/examples/multi-tcg-discord.json). Los ejemplos son ficticios y no envían mensajes.

El servicio intenta obtener la **fecha prevista de venta, preventa o lanzamiento** a partir del anuncio y mostrarla separada de cuándo fue detectado. Convierte la hora a la zona configurada —Madrid por defecto— solo cuando hay una zona horaria respaldada por la fuente, marca las fechas orientativas y avisa de los cambios de fecha. Si no hay datos suficientes, muestra «Sin fecha confirmada». Los torneos muestran su horario, tienda y tarifa de inscripción por separado; un período de evento no se convierte en fecha de venta. Consulta [cómo se extraen y validan las fechas](docs/release-dates.md) y [los límites de los calendarios](docs/multi-tcg.md#torneos-y-tiendas-locales).

La deduplicación entre fuentes reconoce publicaciones que enlazan el mismo artículo oficial. No fusiona automáticamente campañas por títulos parecidos: dos anuncios diferentes, una revelación y un producto de tienda pueden generar eventos distintos. La [guía de fuentes](docs/announcement-sources.md) explica esa cobertura y sus límites.

## Consultar alertas y probar mensajes

En **Portainer → Containers → Drop Alerts → Console**, abre `/bin/sh` y ejecuta:

```sh
python -m drop_alerts events --tcg one_piece --kind event --limit 10
python -m drop_alerts events --tcg pokemon --kind article --limit 10
python -m drop_alerts preview --tcg one_piece --kind event
python -m drop_alerts preview --tcg pokemon --kind article --send
```

`events` consulta eventos guardados; `preview` muestra el último mensaje que coincide. Solo `--send` envía una vista previa al webhook configurado, con la marca **VISTA PREVIA MANUAL**. No vuelve a consultar las webs, no llama al modelo ni cambia el historial o la deduplicación. También permite probar eventos registrados durante el arranque silencioso. Desde el host, antepón `docker compose exec drop-alerts`. La [guía de consultas y pruebas](docs/inspecting-alerts.md) explica los filtros y los errores de envío.

## Modelo remoto

La configuración inicial solicitada es:

```dotenv
LLM_ENABLED=true
LLM_BASE_URL=https://llama.gonibix23.com/v1
LLM_MODEL=qwen3:8b-q4_k_m
LLM_API_KEY=
LLM_TIMEOUT_SECONDS=45
LLM_MAX_RETRIES=1
LLM_TEMPERATURE=0.1
LLM_MAX_INPUT_CHARS=12000
LLM_CACHE_ENABLED=true
```

El cliente utiliza HTTP y JSON con el contrato de chat compatible con OpenAI. No llama automáticamente a proveedores externos. Durante el desarrollo, la raíz y `/v1/models` devolvieron HTTP 401 sin credenciales: el contrato de chat y la presencia del modelo siguen pendientes de comprobar con autenticación. Los detalles están en [verificación del modelo](docs/llm-verification.md). La disponibilidad de esa URL desde un equipo de desarrollo no demuestra que tu VM o LXC pueda acceder: ejecuta el diagnóstico dentro del contenedor.

```sh
docker compose exec drop-alerts python -m drop_alerts doctor
docker compose exec drop-alerts python -m drop_alerts check-llm
docker compose exec drop-alerts python -m drop_alerts status
```

Si el servidor exige autenticación, define `LLM_API_KEY` mediante variables protegidas o un archivo de secreto montado y `LLM_API_KEY_FILE`. No guardes claves en Git. Para desactivar el análisis usa `LLM_ENABLED=false`; la monitorización y las alertas deterministas siguen funcionando.

## Configuración

[.env.example](.env.example) reúne las opciones. Las variables se validan al arrancar. Para personalizar fuentes y reglas, copia [config.example.toml](config.example.toml), edítalo, móntalo en `/app/config.toml` y configura `CONFIG_PATH=/app/config.toml`. Cada fuente admite `interval_seconds`; si lo omites, utiliza `POLL_INTERVAL_SECONDS`.

Selecciona los juegos con `[games].enabled` en el TOML o con `ENABLED_TCGS=magic,one_piece,pokemon` en las variables del stack; la variable, cuando está definida, tiene prioridad. Las reglas admiten `tcgs`, `regions`, `cities` y `channels`, además de fuente, categoría, tipo de evento, estado y palabras clave. Los juegos y filtros geográficos se normalizan; las palabras clave ignoran mayúsculas. Dentro de una regla se deben cumplir todos los filtros, y basta con que coincida una regla para permitir la alerta. Consulta [ejemplos de configuración](docs/multi-tcg.md#seleccionar-juegos-y-reglas) y [cómo ampliar el sistema](docs/extending.md).

| Grupo | Opciones principales |
| --- | --- |
| Servicio | `POLL_INTERVAL_SECONDS=300`, `TIMEZONE=Europe/Madrid`, `BOOTSTRAP_MODE=silent`, `LOG_LEVEL=INFO` |
| Juegos | `ENABLED_TCGS=magic,one_piece,pokemon` o `[games].enabled` en TOML |
| Persistencia | `DATABASE_PATH=/data/drop-alerts.db`, `HEARTBEAT_PATH=/data/heartbeat.json`, `RETENTION_DAYS=90` |
| Fuentes | `HTTP_TIMEOUT_SECONDS=20`, `HTTP_MAX_RETRIES=1`, `SOURCE_MAX_BYTES=2000000`, `SOURCE_MAX_ITEMS=100` |
| IA | `LLM_ENABLED`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`/`LLM_API_KEY_FILE`, tiempo de espera, reintentos, temperatura, límites de entrada/salida y caché |
| Cola IA | `MAX_PENDING_ANALYSES=100`, `ANALYSES_PER_TICK=4`, `ANALYSIS_MAX_ATTEMPTS=3` |
| Discord | `DISCORD_WEBHOOK_URL`/`DISCORD_WEBHOOK_URL_FILE`, `NOTIFICATION_MAX_ATTEMPTS=12`, `NOTIFICATION_BATCH_SIZE=10` |

La zona horaria controla la presentación de fechas. Las fechas de detección emplean UTC; los horarios de torneos conservan también la información temporal de la fuente. No configures varias réplicas contra la misma base de datos: este despliegue está pensado para una instancia.

Al desactivar un juego, fuente o regla, las notificaciones pendientes que dejan de cumplir la configuración se marcan como omitidas (`skipped`). Rehabilitarlo no rescata esa cola antigua; los cambios nuevos que cumplan las reglas pueden generar alertas.

## Flujo de trabajo

1. El monitor consulta cada adaptador con límites de tiempo, tamaño y reintentos.
2. El adaptador transforma evidencia de la fuente en elementos genéricos con identidad estable.
3. El detector compara elementos y estados persistidos. La regla decide si un evento debe notificarse.
4. Los análisis semánticos necesarios entran en una cola limitada. Se reutiliza la caché por contenido, tarea, modelo y versión de esquema.
5. El evento y su notificación pendiente se guardan antes del envío. Un trabajador de Discord respeta esperas y límites de frecuencia.

`Item` y `Event` admiten dominios distintos de productos. Los estados `ANNOUNCED`, `UPCOMING`, `AVAILABLE`, `UNAVAILABLE` y `UNKNOWN` pertenecen a esta integración inicial, no restringen todos los adaptadores. Las interfaces `SourceAdapter`, `Analyzer` y `NotificationChannel` están en `drop_alerts/models.py`. Consulta [la arquitectura y sus garantías](docs/architecture.md) para transacciones, recuperación, límites de confianza y entrega.

La IA recibe contenido como datos no confiables. Sus respuestas se validan con esquemas estrictos y evidencia; nunca ejecuta acciones, elige URLs para visitar, modifica configuración ni decide la disponibilidad del producto. Una confianza alta declarada por el modelo no equivale a una verificación. Los fallos dejan el análisis pendiente o incierto y no convierten `UNKNOWN` en disponibilidad confirmada.

## Pruebas y desarrollo

```sh
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python -m pytest
```

Las pruebas usan respuestas guardadas y transportes HTTP simulados: no requieren el modelo real ni envían mensajes a Discord. La comprobación de esta ampliación del 25 de octubre de 2026 superó **662 pruebas** y consultó las 14 fuentes activas con TLS verificado, sin errores parciales y sin generar notificaciones durante el arranque silencioso; IA y Discord estaban desactivados en esa comprobación. El detalle y las limitaciones de construcción y despliegue están en [verificación](docs/verification.md).

La integración continua prueba Python 3.12 y 3.14 y prepara imágenes Linux amd64 y arm64. La publicación en GHCR se hace desde `main` después de superar las pruebas; las solicitudes de cambios no publican imágenes. Consulta el resultado de la ejecución concreta en GitHub Actions.

Para ejecutar fuera de Docker, configura rutas escribibles locales en `DATABASE_PATH` y `HEARTBEAT_PATH`, y exporta las variables en tu terminal. El archivo `.env` se utiliza para interpolación de Docker Compose; no se carga automáticamente al ejecutar Python directamente.

```sh
python -m drop_alerts once
python -m drop_alerts run
python -m drop_alerts status
python -m drop_alerts health
python -m drop_alerts prune
```

## Fiabilidad y límites

- SQLite conserva estados, eventos, análisis y entregas entre reinicios. Conserva el volumen para mantener la deduplicación.
- La deduplicación interna es persistente. Discord no ofrece una clave de idempotencia para webhooks entrantes: si acepta una petición y la respuesta se pierde antes de guardar el éxito, un reintento puede repetir el mensaje. No se promete entrega exactamente una vez.
- Los límites de cola, reintentos, retención y rotación de logs evitan crecimiento ilimitado de trabajos y registros operativos. La historia necesaria para recordar identidades tiene un coste creciente con el número de elementos.
- El `HEALTHCHECK` comprueba que el proceso sigue atendiendo su ciclo; los fallos de cada fuente y del modelo se consultan por separado.
- No se han supuesto cifras de tamaño de imagen ni consumo de RAM. Mídelas con `docker image inspect` y `docker stats` en tu host.
- Las protecciones y estructuras de las webs pueden cambiar. Consulta [la investigación de fuentes](docs/source-research.md) y [solución de problemas](docs/troubleshooting.md). No se instala un navegador para sortear bloqueos.
