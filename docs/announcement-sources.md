# Fuentes implementadas para anuncios y drops especiales

El servicio tiene **siete fuentes oficiales activadas por defecto** y cuatro medios opcionales desactivados. Esta página describe el código y la configuración actuales; los informes de investigación conservan candidatos adicionales y observaciones de la revisión inicial.

## Fuentes oficiales activadas

| ID | Fuente y método | Cobertura | Intervalo inicial |
| --- | --- | --- | --- |
| `secret_lair_eu` | [Tienda EU](https://secretlair.wizards.com/eu/), catálogo público descubierto en su HTML y fichas con JSON-LD | Anuncios de portada, productos y cambios comerciales verificables de EU | Global: 300 s |
| `magic_news` | [Noticias](https://magic.wizards.com/en/news), [anuncios](https://magic.wizards.com/en/news/announcements) y [sitemap](https://magic.wizards.com/en/sitemap.xml) | Artículos relevantes, nuevas ventanas de venta, retrasos y revisiones de artículos guardados | Global: 300 s |
| `chaos_vault_eu` | [Chaos Vault EU](https://secretlair.wizards.com/eu/chaosvault), filtros del catálogo oficial | Anuncios de productos publicados en Chaos Vault; no interpreta el catálogo como prueba de stock | Global: 300 s |
| `secret_lair_bluesky` | [Cuenta oficial](https://bsky.app/profile/mtgsecretlair.com), API pública de Bluesky | Publicaciones propias relevantes y enlaces explícitos; excluye reposts | Global: 300 s |
| `wpn_news` | [Noticias WPN](https://wpn.wizards.com/en/news), HTML de listado y artículos | Secret Lair de tiendas, promociones y productos especiales con contenido verificable | 900 s · 15 min |
| `magiccon_news` | [Noticias MagicCon](https://www.mtgfestivals.com/global/en-us/magiccon-news.html), HTML de listado y artículos | Festival in a Box, Secret Gallery, Roadshow y exclusivas anunciadas en noticias del festival | 1.800 s · 30 min |
| `weekly_mtg` | [Playlist WeeklyMTG](https://www.youtube.com/playlist?list=PL3rP64NRtmbjdg_j75RqbTu5Ffpc-Q_9s), feed Atom | Títulos y descripciones de vídeos relevantes del canal oficial de Magic | 900 s · 15 min |

«Global» significa `POLL_INTERVAL_SECONDS`, inicialmente 300. Las fuentes con intervalo propio usan `interval_seconds` de su bloque TOML. Puedes cambiarlo entre 30 y 86.400 segundos; las solicitudes también respetan los límites HTTP y las pausas indicadas por los servidores. Las fuentes fallan de forma independiente.

Bluesky consulta `app.bsky.feed.getAuthorFeed` en `public.api.bsky.app` con el DID aprobado `did:plc:5a2wvprzfv3cej7fxud66twr`, comprueba el autor de cada publicación y conserva la URI del post como identidad. No necesita una cuenta del usuario ni depende del nombre visible del perfil. La respuesta solicitada es una ventana de 30 registros, no el archivo completo de la cuenta.

Magic combina descubrimiento acotado y una ventana rotatoria de revisión. El sitemap selecciona URLs con términos de drops especiales; `lastmod` ordena consultas, nunca demuestra una publicación nueva. El máximo de detalles es 15 por comprobación, o menos si reduces `SOURCE_MAX_ITEMS`. Los títulos ambiguos sin términos reconocibles pueden depender de aparecer en los listados. No se descarga todo el archivo ni se promete cobertura de todas las noticias históricas.

Chaos Vault descubre sus filtros en la página real y obtiene la configuración de transporte de la portada EU. WPN y MagicCon examinan ventanas acotadas de artículos de sus listados. Los extractores conservan solo elementos extraídos correctamente; errores de red, cambios de estructura o desapariciones del listado no convierten un producto en agotado.

## Medios opcionales

Estos adaptadores están implementados y su configuración inicial es `enabled=false`:

| ID | Feed comprobado | Intervalo configurado si se activa |
| --- | --- | --- |
| `magicspoiler` | [RSS MagicSpoiler](https://www.magicspoiler.com/feed/) | 900 s |
| `mtggoldfish` | [Atom MTGGoldfish](https://www.mtggoldfish.com/feed) | 900 s |
| `mtgdrops` | [RSS MTGDrops](https://mtgdrops.com/feed.xml) | 900 s |
| `scg_news` | [RSS Star City Games](https://articles.starcitygames.com/feed/) | 1.800 s |

Para activarlos, parte del [ejemplo completo](../config.example.toml), cambia el bloque correspondiente a `enabled=true`, conserva la regla `secondary-special-announcements`, monta el archivo en `/app/config.toml` y configura `CONFIG_PATH=/app/config.toml`. Los apartados presentes de ese TOML sustituyen los valores predeterminados: un archivo antiguo no recibe automáticamente las nuevas fuentes ni reglas.

Los feeds se filtran por temas de anuncios especiales y sus entradas conservan procedencia secundaria. Las fechas ausentes quedan desconocidas. Los valores volátiles como `updated` del feed o las métricas sociales no se consideran por sí solos cambios editoriales. Una noticia de un medio o una fecha de calendario no demuestra precio ni disponibilidad EU.

## Eventos, duplicados y formato de Discord

Las nuevas fuentes producen anuncios; Magic conserva el tipo de publicación editorial y la tienda sus eventos de productos. Un anuncio puede existir semanas antes de la venta. La disponibilidad comercial sigue requiriendo evidencia de la región correspondiente.

La deduplicación cruzada se limita a publicaciones que remiten al **mismo artículo oficial permitido**. Por ejemplo, un post de Bluesky o una entrada RSS que enlaza un artículo de Magic pueden compartir esa identidad y evitar otro primer aviso. Se conserva el registro de cada fuente. No se fusionan automáticamente títulos parecidos, campañas, variantes, regiones, noticias diferentes ni un anuncio con su posterior producto de tienda. Las actualizaciones relevantes siguen teniendo eventos propios.

Discord muestra una tarjeta con icono y color por evento, título enlazado, extracto verificable de la fuente, procedencia, fecha y región cuando existe. Añade imagen únicamente si el adaptador la extrajo de una respuesta permitida. El contenido conserva el idioma de la fuente; no se inventa una traducción ni se usa texto libre del modelo para afirmar precios, stock o enlaces. Los resultados semánticos se indican como orientativos. Se mantienen menciones desactivadas, límites de longitud y reintentos persistentes.

WeeklyMTG aporta texto del feed y miniatura; no transcribe vídeo ni interpreta imágenes. Del mismo modo, una imagen en Bluesky no aporta automáticamente sus fechas o nombres al analizador de texto.

El formato respeta los [límites oficiales de embeds y menciones de Discord](https://docs.discord.com/developers/resources/message). La API de autor utilizada por Bluesky aparece en su [referencia oficial de endpoints](https://endpoints.bsky.app/).

## Actualizar un stack existente

1. Conserva una copia de seguridad y el volumen `drop_alerts_data` del stack actual.
2. Si utilizas TOML propio, incorpora los nuevos bloques y reglas del ejemplo. Mantén `BOOTSTRAP_MODE=silent`.
3. En Portainer, abre el stack vinculado al repositorio y utiliza **Pull and redeploy** para obtener `refs/heads/main` y reconstruir `docker-compose.yml` desde Git.
4. Consulta los logs y ejecuta `python -m drop_alerts status` desde la consola del contenedor para ver las comprobaciones de cada fuente.

La migración SQLite de esquema **1 a 2** se aplica automáticamente al abrir la base de datos y añade el registro de identidad compartida de anuncios. Conserva estados, eventos, colas y entregas. No necesitas eliminar el contenedor manualmente, borrar SQLite ni recrear el volumen para incorporar fuentes.

Con arranque silencioso, la primera comprobación válida de cada fuente nueva registra su referencia sin alertas históricas. Los inventarios añadidos de anuncios/sitemap de Magic reciben su propia referencia silenciosa, aunque `magic_news` ya estuviera inicializada. Una estructura fallida no se considera una referencia correcta. No cambies a `notify` solo para comprobar la actualización: ese modo permite avisos iniciales de contenido ya existente.

La consulta desde desarrollo no acredita acceso desde la red de Proxmox. El diagnóstico `python -m drop_alerts doctor` permite revisar la conectividad dentro del contenedor; el estado de extracción y entregas se consulta con `status` y los logs.

## Fuentes investigadas que siguen sin adaptador

Correo y newsletters, X, Instagram/Facebook, Twitch, newsroom de Hasbro, sitios de colaboradores, Scryfall, calendarios ICS y Reddit siguen fuera de los monitores implementados. Tampoco se recorren todos los subdominios de ciudades de MagicCon ni tiendas minoristas individuales. La [investigación ampliada](source-expansion-research.md) explica su utilidad y las limitaciones observadas; no implica suscripciones, acceso a buzones ni nuevas credenciales.
