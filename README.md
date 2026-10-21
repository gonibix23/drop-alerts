# Drop Alerts

Servicio de alertas con adaptadores independientes, estado en SQLite, cola persistente y notificaciones por webhook de Discord. Vigila Secret Lair EU, Chaos Vault, anuncios de Magic, Bluesky oficial de Secret Lair, WPN, MagicCon y WeeklyMTG. El modelo remoto interpreta contenido ambiguo; el código conserva la autoridad sobre consultas, precios, disponibilidad, reglas, deduplicación y envíos.

El contenedor usa Python 3.12 slim, un único servicio y un volumen. No publica puertos y no incluye ningún modelo, navegador ni servidor de inferencia.

El estado de esta entrega y las comprobaciones realizadas están en [verificación](docs/verification.md). Si recibes el proyecto como ZIP, extráelo como `drop-alerts` y entra en esa carpeta en lugar de ejecutar `git clone`.

Consulta las [fuentes implementadas y sus intervalos](docs/announcement-sources.md). La [investigación ampliada](docs/source-expansion-research.md) conserva la revisión original y otros candidatos; que una fuente aparezca investigada no significa que esté activada.

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

Para actualizar un stack existente en Portainer, abre el stack creado desde Repository y utiliza **Pull and redeploy** para obtener `main` y reconstruir con `docker-compose.yml`. Conserva el volumen `drop_alerts_data`: al arrancar se aplica automáticamente la migración aditiva de SQLite de esquema 1 a 2, sin borrar estados, colas ni entregas. Mantén `BOOTSTRAP_MODE=silent`; las fuentes nuevas y los inventarios ampliados de Magic se incorporan sin avisos históricos. Si montas un TOML antiguo, incorpora los nuevos bloques de fuentes y reglas desde el ejemplo: ese archivo sustituye las listas predeterminadas.

## Anuncios y Discord

Hay siete fuentes oficiales activadas por defecto. Secret Lair EU, Chaos Vault, Magic y Bluesky siguen `POLL_INTERVAL_SECONDS` (300 segundos inicialmente); WPN y WeeklyMTG se revisan cada 15 minutos y MagicCon cada 30. Magic amplía la portada con la categoría de anuncios, el sitemap y revisiones de artículos guardados. Los medios MagicSpoiler, MTGGoldfish, MTGDrops y Star City Games están disponibles como fuentes opcionales, desactivadas inicialmente.

Las notificaciones usan tarjetas con color e icono según el evento, título enlazado, extracto de la fuente, región, fecha y una imagen cuando el adaptador la ha extraído de la fuente. Los precios y la disponibilidad se muestran cuando hay datos admitidos por el programa; un anuncio no prueba que un producto ya esté a la venta. El texto conserva el idioma de la fuente y las etiquetas están en español. Las menciones siguen desactivadas.

Puedes abrir la [vista previa HTML](docs/discord-preview.html) en tu navegador o consultar el [JSON de ejemplo](docs/examples/discord-announcement.json). Ambos usan datos ficticios y no envían mensajes.

La deduplicación entre fuentes reconoce publicaciones que enlazan el mismo artículo oficial. No fusiona automáticamente campañas por títulos parecidos: dos anuncios diferentes, una revelación y un producto de tienda pueden generar eventos distintos. La [guía de fuentes](docs/announcement-sources.md) explica esa cobertura y sus límites.

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

[.env.example](.env.example) reúne las opciones. Las variables se validan al arrancar. Para personalizar fuentes y reglas, copia [config.example.toml](config.example.toml), edítalo, móntalo en `/app/config.toml` y configura `CONFIG_PATH=/app/config.toml`. Cada fuente admite `interval_seconds`; si lo omites, utiliza `POLL_INTERVAL_SECONDS`. Las reglas filtran por fuente, categoría, tipo de evento y palabras clave. Las palabras clave se comprueban sin distinguir mayúsculas. Revisa [cómo ampliar el sistema](docs/extending.md).

| Grupo | Opciones principales |
| --- | --- |
| Servicio | `POLL_INTERVAL_SECONDS=300`, `TIMEZONE=Europe/Madrid`, `BOOTSTRAP_MODE=silent`, `LOG_LEVEL=INFO` |
| Persistencia | `DATABASE_PATH=/data/drop-alerts.db`, `HEARTBEAT_PATH=/data/heartbeat.json`, `RETENTION_DAYS=90` |
| Fuentes | `HTTP_TIMEOUT_SECONDS=20`, `HTTP_MAX_RETRIES=1`, `SOURCE_MAX_BYTES=2000000`, `SOURCE_MAX_ITEMS=100` |
| IA | `LLM_ENABLED`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`/`LLM_API_KEY_FILE`, tiempo de espera, reintentos, temperatura, límites de entrada/salida y caché |
| Cola IA | `MAX_PENDING_ANALYSES=100`, `ANALYSES_PER_TICK=4`, `ANALYSIS_MAX_ATTEMPTS=3` |
| Discord | `DISCORD_WEBHOOK_URL`/`DISCORD_WEBHOOK_URL_FILE`, `NOTIFICATION_MAX_ATTEMPTS=12`, `NOTIFICATION_BATCH_SIZE=10` |

La zona horaria controla la presentación de fechas. Los instantes persistidos emplean UTC. No configures varias réplicas contra la misma base de datos: este despliegue está pensado para una instancia.

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

Las pruebas usan respuestas guardadas y transportes HTTP simulados: no requieren el modelo real ni envían mensajes a Discord. La integración continua prueba Python 3.12 y 3.14 y prepara imágenes Linux amd64 y arm64. La publicación en GHCR se hace desde `main` después de superar las pruebas; las solicitudes de cambios no publican imágenes. Consulta el resultado de la ejecución concreta en GitHub Actions.

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
