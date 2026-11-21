# Estado de verificación de la entrega

El proyecto utiliza la rama `main` y su repositorio de GitHub es privado: [gonibix23/drop-alerts](https://github.com/gonibix23/drop-alerts). Las comprobaciones se detallan por versión y fecha.

## Actualización 1.4.3: El Cartón Peleón (21/11/2026)

- `python -m pytest -q -p no:cacheprovider --basetemp work/pytest-carton-release-final`: **918 pruebas aprobadas**, Python 3.14 en Windows. Se completaron también compilación de módulos, `pip check`, validación del Compose y revisión de formato.
- Consulta real de `carton_peleon` con `SourceHTTP`, HTTPS/TLS verificado y SQLite en memoria: **12 fichas y cuatro páginas**, sin errores parciales. El arranque silencioso dejó **0 notificaciones pendientes** y repetir los resultados produjo **0 eventos nuevos**. La ventana reciente consultada contenía productos próximos y no representa todo el catálogo.
- El pack Warhammer solicitado quedó como plantilla `19822`, variante `23219`, `UPCOMING`: **próximamente disponible para reservar**. Se visita primero en cada ronda. El precio cero de metadatos, el importe oculto de edición y la fecha estimada contradictoria no se presentan como precio o fecha confirmados.
- Se verificó por separado una ficha normal con HTML de stock insuficiente: la RPC pública de lectura de combinaciones devolvió las identidades y existencias de esa variante. Mediante `SourceHTTP.post_json` pasó de `UNKNOWN` a `AVAILABLE`, conservando el precio público visible y corroborado. No se usa el precio de la API ni se realizan acciones de carrito o compra.
- Las **63 pruebas del adaptador** reproducen HTML/JSON guardados, identidades de plantilla y variante, precio oculto, stock online frente a tienda física, reservas, errores de RPC, bloqueo de venta, límites y referencia inicial diferida. Las pruebas del transporte comprueban que las consultas JSON comparten las pausas y reintentos HTTP, rechazan respuestas ambiguas y no cachean stock ni siguen redirecciones; la compatibilidad de GET y su caché también pasó.
- Se conservan SQLite 2, volumen, dependencias y ausencia de puertos publicados. Hay **19 fuentes activas y 31 registradas**. Los nuevos identificadores opcionales `palworld`, `universus` y `weiss_schwarz` respetan la selección de juegos; los tres juegos iniciales siguen siendo los predeterminados.
- Las verificaciones utilizaron estado temporal, IA desactivada y ningún webhook. No se accedió a Portainer ni se envió un mensaje real. La construcción y ejecución de cada revisión se consultan en [GitHub Actions](https://github.com/gonibix23/drop-alerts/actions); el motor Docker local no estaba disponible. Las capturas completas están en `work/research/carton-peleon/`, excluido de Git.

Consulta [la guía de El Cartón Peleón](carton-peleon.md) y [la investigación de la fuente](research-carton-peleon.md). Las verificaciones siguientes son históricas.

## Actualización 1.4.2: Zial TCG y producto enlazado (19/11/2026)

- `python -m pytest -q -p no:cacheprovider --basetemp work/pytest-zial-final`: **829 pruebas aprobadas**, Python 3.14 en Windows. `compileall`, `pip check`, la validación del Compose y la revisión de formato terminaron correctamente.
- Consulta real de `zial_tcg` con `SourceHTTP`, HTTPS/TLS verificado y SQLite en memoria: **12 productos y seis páginas de catálogo**, sin errores parciales. Se observaron seis preventas, cuatro productos disponibles y dos agotados en esa ventana. El arranque silencioso dejó **0 notificaciones pendientes**; repetir los resultados generó **0 eventos nuevos**. No se hicieron inferencias ni envíos a Discord.
- El producto enlazado por el usuario, Commander Deck Display Warhammer 40K, quedó identificado como `product:11533` y `UPCOMING`, con precio EUR comprobado. Se consulta expresamente cada ronda. La cantidad reservable no se presenta como stock para entrega inmediata, porque la propia ficha indica preventa. Los importes y estados corresponden al momento de la consulta.
- Las **41 pruebas del adaptador** cubren respuestas reales guardadas, precio actual frente a tachado, SKU comercial independiente del ID WooCommerce, divisa, reservas, stock negativo, variantes sin verificar, exclusión de figuras/entradas/ruletas, géneros explícitos de cartas, cuotas y límites de consulta, reposiciones fuera del listado y la recuperación silenciosa del producto enlazado tras un fallo inicial y un reinicio.
- La selección de juegos sigue siendo Magic, One Piece y Pokémon. Se añaden etiquetas opcionales para productos identificados como `gundam` y `jurassic_park`, sin crear fuentes oficiales nuevas ni activar esos juegos automáticamente. Hay **18 fuentes activas y 30 registradas**, con el esquema SQLite 2, volumen y dependencias existentes.
- El motor Docker local sigue sin estar disponible. La construcción y ejecución de cada revisión se verifican en [GitHub Actions](https://github.com/gonibix23/drop-alerts/actions). No se ha accedido a Portainer ni se ha probado una entrega real. Las capturas completas de trabajo se guardan en `work/research/zial/`, excluido de Git; las pruebas incluyen extractos reducidos.

Consulta [la guía de Zial TCG](zial.md) y [la investigación de la fuente](research-zial.md). Las verificaciones siguientes son históricas.

## Actualización 1.4.1: Animefan, solo TCG (19/11/2026)

- `python -m pytest -q -p no:cacheprovider --basetemp work/pytest-animefan-final`: **784 pruebas aprobadas**, Python 3.14 en Windows. Se completaron también `compileall`, `pip check` y la validación del Compose sin errores.
- La consulta real de `animefan`, con `SourceHTTP`, HTTPS/TLS verificado y SQLite en memoria, extrajo **12 productos Pokémon de cuatro páginas**, sin errores parciales. El arranque silencioso dejó **0 notificaciones pendientes** y repetir los resultados produjo **0 eventos nuevos**. No se consultó el modelo ni se envió nada a Discord.
- Se comprobaron las categorías públicas de cartas y sus fichas WooCommerce/Elementor. Las pruebas reproducen productos TCG y accesorios, productos agotados, reservas, compra bajo pedido, recomendaciones anidadas, depósito frente a precio total, importes contradictorios y errores HTTP. La categoría genérica de cartas coleccionables no basta para afirmar que un artículo sea TCG: se exige evidencia propia del producto o fabricante y se excluyen naipes y figuras en el modo inicial.
- La configuración entregada mantiene `include_collectibles=false`, conforme a la preferencia de **solo cartas TCG**. También se verificó la opción independiente desactivada de coleccionables, incluido el cierre de mensajes pendientes y su exclusión de las vistas previas al desactivarla.
- Se mantienen SQLite 2, dependencias y volumen, sin puertos ni servicios adicionales. Hay **17 fuentes activas y 29 registradas**. Las capturas completas están en `work/research/animefan/`, fuera de Git; se incluyen extractos reducidos en las pruebas. La prueba en vivo es una ventana acotada, no el catálogo completo.
- El motor Docker local no está disponible. La construcción y ejecución del contenedor de cada revisión se consultan en [GitHub Actions](https://github.com/gonibix23/drop-alerts/actions). No se ha accedido al stack de Portainer; la conectividad y entrega real deben comprobarse en ese entorno.

Consulta [la configuración de Animefan](animefan.md) y [el estudio de la fuente](research-animefan.md). Las verificaciones siguientes son históricas.

## Actualización 1.4: tiendas online (19/11/2026)

- `python -m pytest -q -p no:cacheprovider --basetemp work/pytest-retail-final`: **739 pruebas aprobadas**, Python 3.14 en Windows. Compilación de módulos con `compileall` y revisión de formato completadas correctamente.
- Comprobación real conjunta de `tabletop_gamers` y `jjcollection`, mediante `SourceHTTP`, HTTPS y TLS verificado, con SQLite en memoria, sin IA ni webhook: **cuatro productos por fuente**, cero errores parciales, **0 notificaciones pendientes** durante el arranque silencioso y **0 eventos adicionales** al repetir exactamente los mismos resultados. Los estados observados incluyeron disponibles, agotados y reservas; las ventanas acotadas no representan el catálogo completo.
- Las verificaciones individuales ampliadas extrajeron ocho productos de Tabletop y doce variantes de JJ Collection, sin errores parciales. JJ descubrió 213 URLs distintas en el sitemap examinado. Las capturas completas y diagnósticos están en `work/research/`, excluidos de Git; se incluyen fixtures reducidos para las pruebas.
- Las pruebas nuevas comprueban correlación de precio y stock por variante, rebajas, reservas, estados contradictorios, páginas bloqueadas, ausencia de productos, reposiciones, inventarios diferidos silenciosos tras reinicios, presupuestos de consulta, fichas lentas y rotación persistente. La integración prueba reglas por juego, estados separados entre tiendas, ausencia de ruido por cambios de cantidad y selección por `--source` en consultas de solo lectura.
- `docker compose --env-file .env.example config --quiet`: configuración válida. `pip check`: sin incompatibilidades. El motor Docker local sigue sin estar disponible (`docker_engine` ausente); la construcción y el arranque de cada revisión se verifican en [GitHub Actions](https://github.com/gonibix23/drop-alerts/actions).
- Se conservan esquema SQLite 2, dependencias, puertos y volumen. La versión predeterminada tiene **16 fuentes activas y 28 registradas**. No se ha accedido a Portainer ni se ha enviado una notificación real. La conectividad y permisos de tu despliegue siguen comprobándose allí.

Consulta [la guía de tiendas](retail-stores.md) y la investigación de [Tabletop Gamers](research-tabletop.md) y [JJ Collection](research-jjcollection.md). Las verificaciones siguientes corresponden a versiones anteriores.

## Actualización 1.3: varios TCG y calendarios (25/10/2026)

- `python -m pytest -q --basetemp work/pytest-multi-tcg-release-final`: **662 pruebas aprobadas**, Python 3.14 en Windows. Incluyen los adaptadores nuevos con respuestas guardadas, selección por juego, filtros de región/ciudad/canal, fechas de torneos y sus zonas horarias, deduplicación, compatibilidad con eventos antiguos, consultas de solo lectura y desactivación de notificaciones pendientes. También verifican que endurecer una regla para exigir análisis no envía mensajes anteriores sin ese análisis.
- Comprobación HTTPS real conjunta de las **14 fuentes activas** con `SourceHTTP` y TLS verificado: todas devolvieron contenido válido, sin errores parciales. Se utilizó una SQLite en memoria, con IA y webhook desactivados; el arranque silencioso dejó **0 notificaciones pendientes**. Las consultas limitaron el número de detalles y no equivalen a una exploración histórica completa.
- Se consultó el contenido del chat compartido y se investigaron sus **25 tiendas**. Se verificaron 23 perfiles públicos con JSON-LD de eventos y alternativas directas para Next Dice y Júpiter Guadalajara. El inventario de procedencia y activación está en [local-stores-coverage.json](local-stores-coverage.json); por defecto se revisan ocho tiendas cercanas. Un calendario válido sin torneos de los tres juegos seleccionados es un resultado vacío correcto.
- Los calendarios directos adicionales se comprobaron por separado con transporte real: Next Dice, Arte9 (iCalendar), Ludoteca Maldita y Júpiter Guadalajara (octubre y noviembre). No se generaron recurrencias futuras ni se dedujeron plazas disponibles a partir del aforo.
- Las galerías de productos de Pokémon quedaron opcionales por respuestas intermitentes de bloqueo; Pokémon Center devolvió HTTP 403. Las fuentes activas de Pokémon son el portal TCG y su prensa oficial en español. No se implementa stock de Pokémon Center ni se interpreta el idioma español como disponibilidad en España.
- `docker compose --env-file .env.example config --quiet`: configuración válida. `pip check`: sin incompatibilidades. Las nuevas fuentes no añaden dependencias de ejecución, puertos ni contenedores. Se volvió a consultar el motor Docker local y el pipe `docker_engine` sigue ausente; la construcción y ejecución de esta revisión se comprueban en [GitHub Actions](https://github.com/gonibix23/drop-alerts/actions).
- El esquema SQLite sigue en **2**. El enriquecimiento de juego en registros antiguos es silencioso y no recrea eventos ni entregas. Las vistas previas son ficticias; las pruebas y verificaciones de esta versión no enviaron mensajes a Discord ni hicieron inferencias reales.

Véanse [cobertura y configuración multi-TCG](multi-tcg.md), [consultas y prueba de mensajes](inspecting-alerts.md) y los estudios de [One Piece](research-one-piece-sources.md), [Pokémon](research-pokemon-sources.md) y [calendarios de tiendas](research-store-calendars.md). Las verificaciones siguientes son históricas.

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
