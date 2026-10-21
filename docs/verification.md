# Estado de verificación de la entrega

Comprobado el 21 de octubre de 2026. El proyecto utiliza la rama `main` y su repositorio de GitHub es privado: [gonibix23/drop-alerts](https://github.com/gonibix23/drop-alerts).

## Actualización 1.2: fecha prevista del drop

- `python -m pytest -q --basetemp work/pytest-release-1-2-final-check`: **428 pruebas aprobadas**, Python 3.14 en Windows. Incluyen extracción temporal en inglés/español, ventanas, zonas horarias, negaciones, encabezados de envío/legalidad, fecha orientativa por selección semántica y reintentos sin duplicados.
- Consulta HTTPS real con TLS verificado a dos anuncios de Magic, sin IA, webhook ni base de producción: Countdown Kit se extrajo como **02/11/2026**, y la nueva venta de The Zeta Set como **09/12/2026**. Ambos quedaron sin hora porque los textos examinados no la proporcionan. Se conservaron como anuncios, sin convertirlos en stock disponible.
- La reproducción completa de un artículo guardado pasa por extracción, persistencia y tarjeta Discord, utilizando la fecha del lanzamiento y descartando la legalidad de cartas de abril de 2027.
- Se comprobó el enriquecimiento de elementos antiguos sin nuevas revisiones ni entregas, la lectura de eventos legados y el vencimiento de la ayuda opcional de IA en un máximo de 60 segundos. No se ejecutó una inferencia real ni se envió un mensaje a Discord.
- La nueva información usa los JSON existentes: se conserva el esquema SQLite 2 y el volumen. Los resultados de Docker y las pruebas Linux de cada commit se consultan en GitHub Actions.

Véase [cómo se detectan y presentan las fechas](release-dates.md). Las verificaciones siguientes son históricas.

## Actualización 1.1: anuncios y Discord

- `python -m pytest -q --basetemp work/pytest-release-1-1`: **267 pruebas aprobadas**, Python 3.14 en Windows. Incluyen las siete fuentes, RSS/Atom secundarios, inventarios silenciosos en bases existentes, migración 1→2, deduplicación entre fuentes, planificación, límites HTTP compartidos y presentación de Discord. No requieren servicios externos.
- Comprobación HTTPS real conjunta, con TLS verificado, de las **siete fuentes oficiales** usando una SQLite en memoria, IA desactivada y ningún webhook: todas extrajeron contenido sin errores parciales. El arranque silencioso dejó **0 notificaciones pendientes**. Se limitaron los detalles para esta prueba; los recuentos no representan una exploración completa.
- Consultas específicas comprobaron el catálogo de Chaos Vault, artículos WPN/MagicCon y descubrimiento de Countdown Kit fuera de la portada de Magic. Los cuatro feeds secundarios también se reprodujeron desde capturas guardadas.
- `python -m pip check`: sin incompatibilidades. `docker compose --env-file .env.example config --quiet`: configuración válida. La construcción local sigue sin ser posible porque no existe el pipe del motor Docker; la configuración se comprobó también con una ruta aislada de Docker.
- La vista previa de Discord contiene datos ficticios. No se envió ningún mensaje real, no se accedió a Proxmox/Portainer y no se hizo una inferencia autenticada nueva.

Los límites de cobertura y el procedimiento de actualización se describen en [fuentes implementadas](announcement-sources.md). El resultado de construcción y ejecución del contenedor para cada commit se consulta en [GitHub Actions](https://github.com/gonibix23/drop-alerts/actions); las comprobaciones históricas siguientes corresponden a versiones anteriores.

## Verificación inicial 1.0

- Instalación del paquete y dependencias de desarrollo en un entorno aislado.
- `python -m pytest -q --basetemp work/pytest-final-complete`: **124 pruebas aprobadas**, Python 3.14 en Windows. Las pruebas no hacen peticiones reales ni publican en Discord.
- `python -m pip check`: sin dependencias incompatibles.
- Compilación de los módulos Python con `compileall`.
- `docker compose config --quiet`: configuración válida, sin necesidad de motor Docker.
- Disponibilidad de ruedas binarias de dependencias para CPython 3.12 Linux amd64 y arm64. No equivale a ejecutar pruebas en esas plataformas.
- Posteriormente, [GitHub Actions ejecutó correctamente las pruebas con Python 3.12 y 3.14 y construyó la imagen en Linux](https://github.com/gonibix23/drop-alerts/actions/runs/39666625380). Esa primera construcción comprobaba Docker, pero todavía no publicaba la imagen en un registro.

## Fuentes reales

Se hicieron consultas HTTPS con TLS verificado a las fuentes y a los endpoints públicos descubiertos en sus páginas. Una pasada real del servicio con IA desactivada y sin webhook guardó referencias de ambas fuentes sin enviar mensajes. La consulta ampliada descubrió 67 productos; algunas páginas usan JSON-LD `Thing`, por lo que se añadió una extracción conservadora comprobada con esos cuerpos reales guardados.

La reproducción final sin red de las respuestas capturadas extrajo **70 elementos de Secret Lair** (67 productos y 3 anuncios) y **8 artículos de Magic**, sin errores de extracción. Entre los productos: 14 con `AVAILABLE`, 8 con `UPCOMING` y 45 con `UNKNOWN`, sin inventar stock o precio en los documentos `Thing`. Repetir la reproducción contra el estado persistido produjo **0 eventos nuevos y 0 notificaciones pendientes**. Estos recuentos pertenecen a esa captura y no describen necesariamente el catálogo actual de tu despliegue. Véase `source-research.md` para procedencia, señales utilizadas y límites de cobertura.

## Modelo remoto

La raíz del servidor y `/v1/models` respondieron HTTP 401 sin credencial; `/api/tags` agotó el saludo TLS. Se comprobó la respuesta de la infraestructura, pero **no la compatibilidad de chat, la existencia del modelo ni una inferencia autenticada**. El cliente y sus fallos están probados con respuestas simuladas. Configura la autenticación real y ejecuta `doctor` y `check-llm` desde el contenedor; instrucciones en `llm-verification.md`.

## Pendiente en Docker y Portainer

Se intentó construir la imagen localmente. La configuración Docker del usuario no era legible en este entorno; usando una carpeta de configuración aislada el intento llegó a la conexión con el motor y falló porque no existía el pipe `docker_engine`. No se ha construido ni ejecutado la imagen en este equipo Windows. La construcción y las pruebas de Python sí se comprobaron posteriormente en GitHub Actions, como se indica arriba.

El despliegue predeterminado usa `build.context=.` y `Dockerfile` en `docker-compose.yml`, siguiendo el método comprobado en el Compose de `nexo-erp`: Portainer obtiene el repositorio Git y construye la imagen. No requiere acceder a una imagen privada de la aplicación ni configurar un token de paquetes. El repositorio sigue siendo privado y necesita autenticación Git con acceso a `drop-alerts`.

Como alternativa permanece disponible `ghcr.io/gonibix23/drop-alerts:main`. [La primera publicación de GHCR terminó correctamente](https://github.com/gonibix23/drop-alerts/actions/runs/39669314847): pruebas Python 3.12/3.14, construcción, ejecución sin red, persistencia tras reinicio, publicación amd64/arm64, descarga por digest y segunda comprobación de ejecución en el runner amd64. Solo si se elige esta alternativa de imagen privada se necesita autenticar `ghcr.io` en Portainer. El resultado de publicaciones posteriores se consulta en [Actions](https://github.com/gonibix23/drop-alerts/actions). Véase `deployment.md`.

No se ha accedido a tu Proxmox, Portainer, VM/LXC o Discord. Quedan pendientes la construcción real, permisos del volumen UID 10001, red/DNS/TLS/proxy/autenticación desde ese contenedor y una entrega real a tu webhook. No se ha medido tamaño de imagen, RAM o CPU.

La deduplicación interna y los reintentos se han probado. Una confirmación perdida después de que Discord acepte un mensaje puede causar una repetición; los webhooks no permiten prometer entrega exactamente una vez.
