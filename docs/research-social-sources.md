# Investigación de redes sociales, vídeo y correo oficiales

Revisión: **21 de octubre de 2026**. Comprobaciones HTTP realizadas entre las 20:42 y las 20:45 UTC, con TLS verificado, sin navegador completo, sin iniciar sesión y sin enviar formularios. Se conserva la investigación previa a la ampliación. **Estado actual:** Bluesky oficial de Secret Lair y WeeklyMTG ya tienen adaptadores activados dentro de las siete fuentes oficiales; consulta las [fuentes implementadas](announcement-sources.md). Las propuestas restantes de este documento no implican acceso a correo, suscripciones ni entregas de Discord.

## Conclusión práctica

La incorporación de mayor valor para anticipar Secret Lair es **Bluesky de Secret Lair**: la identidad está enlazada por Wizards y tanto su RSS como la API pública devolvieron contenido completo y reciente sin autenticación. Hay anuncios previos a la puesta a la venta, primeras revelaciones y recordatorios, además de promociones repetidas. **WeeklyMTG** dispone de un Atom ligero que permite detectar programas de revelación. **MTG Festivals/MagicCon** complementa las dos fuentes con agendas y paneles; una agenda anuncia una oportunidad de revelación, no confirma por sí sola un producto.

El correo de **Chaos Vault** merece una integración opcional: Wizards recomienda esa lista para próximos lanzamientos. Su recepción necesita una suscripción y un buzón autorizados expresamente. No se realizó ninguna de esas acciones.

## Cuentas y rutas verificadas

La procedencia de las cuentas de Secret Lair está documentada en el artículo oficial [Secret Lair at WPN Stores: How Does It Work?](https://wpn.wizards.com/en/news/secret-lair-at-wpn-stores-how-does-it-work), del 29 de octubre de 2025. Los enlaces de Magic se extrajeron del HTML de [Magic News](https://magic.wizards.com/en/news); los de MagicCon, de [MTG Festivals](https://www.mtgfestivals.com/) y [MagicCon News](https://www.mtgfestivals.com/global/en-us/magiccon-news.html).

| Fuente | Dirección exacta y procedencia | Comprobación y utilidad |
| --- | --- | --- |
| Secret Lair, Bluesky | [mtgsecretlair.com](https://bsky.app/profile/mtgsecretlair.com), enlazado por WPN | Perfil, API y RSS: HTTP 200. Prioridad alta para futuros superdrops, Chaos Vault, kits y primeras revelaciones. |
| Magic, Bluesky | [magic.wizards.com](https://bsky.app/profile/magic.wizards.com), identidad bajo el dominio de Wizards | API y RSS: HTTP 200. Cuenta general con mucho contenido de otras colecciones; filtrar temas. En los 30 registros examinados no había coincidencias con los términos Secret Lair/Chaos Vault/Festival in a Box; esa muestra no acredita ausencia histórica. |
| MagicCon, Bluesky | [mtgfestivals.com](https://bsky.app/profile/mtgfestivals.com), enlazado por MTG Festivals | Perfil, API y RSS: HTTP 200. Útil para horarios de escenarios, convenciones y paneles; también contiene entradas y actividades ajenas a drops. |
| WeeklyMTG, YouTube | [Lista oficial](https://www.youtube.com/playlist?list=PL3rP64NRtmbjdg_j75RqbTu5Ffpc-Q_9s), enlazada por Magic News | Atom HTTP 200, 13 vídeos en la respuesta. Prioridad media: títulos de programas y descripciones, sin transcribir vídeo por defecto. |
| Magic, YouTube | [UC8ZGymAvfP97qJabgqUkz4A](https://www.youtube.com/channel/UC8ZGymAvfP97qJabgqUkz4A), enlazado por Magic News | Atom HTTP 200, 15 vídeos. Incluye muchos Shorts y tutoriales; más ruido que la lista WeeklyMTG. |
| Secret Lair, X | [@MTGSecretLair](https://x.com/MTGSecretLair), WPN y tienda oficial | HTTP directo 200 y título de cuenta; otra vía de lectura devolvió 403. La respuesta puntual no constituye una interfaz estable. Preferir API oficial si se configura acceso. |
| Magic, X | [@wizards_magic](https://twitter.com/wizards_magic), Magic News | Enlace oficial descubierto; no se probó una API de publicaciones. |
| Juego organizado, X | [@PlayMTG](https://twitter.com/PlayMTG), MTG Festivals | Enlace oficial descubierto; útil para eventos, con ruido de torneos. No se probó su API. |
| Secret Lair, Instagram | [@mtgsecretlair](https://www.instagram.com/mtgsecretlair/), WPN y tienda oficial | HTTP directo 200, título de cuenta; otra vía devolvió 429. No se encontró RSS. El HTML no acredita una extracción continua fiable. |
| Magic, Instagram | [@wizards_magic](https://www.instagram.com/wizards_magic/), Magic News | Enlace oficial descubierto; no se verificó un feed público automatizable. |
| MagicCon, Instagram | [@mtgfestivals](https://www.instagram.com/mtgfestivals/), MTG Festivals | Enlace oficial descubierto; no se verificó un feed público automatizable. |
| Magic, Facebook | [MagicTheGathering](https://www.facebook.com/MagicTheGathering), Magic News y MTG Festivals | Enlace oficial descubierto; no se verificó una API accesible para la aplicación. |
| Magic, Twitch | [magic](https://www.twitch.tv/magic), Magic News | HTTP 200, principalmente aplicación web. Para monitorizar directos programados se necesita integración oficial y sus credenciales. |

Un HTTP 200 de una página social solo demuestra que se recibió esa respuesta en esta comprobación. No demuestra que todos los posts sean accesibles, que exista RSS ni que la plataforma permita una extracción estable sin autenticación.

## Feeds ligeros disponibles

### Bluesky

| Cuenta | RSS comprobado | API comprobada | Identidad persistente observada |
| --- | --- | --- | --- |
| Secret Lair | [RSS](https://bsky.app/profile/mtgsecretlair.com/rss) | [getAuthorFeed](https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=mtgsecretlair.com&limit=30) | `did:plc:5a2wvprzfv3cej7fxud66twr` |
| Magic | [RSS](https://bsky.app/profile/magic.wizards.com/rss) | [getAuthorFeed](https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=magic.wizards.com&limit=30) | `did:plc:rcyyjldt7topi6fz3dxnsaxx` |
| MTG Festivals | [RSS](https://bsky.app/profile/mtgfestivals.com/rss) | [getAuthorFeed](https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=mtgfestivals.com&limit=30) | `did:plc:nfh3wbmgrvhk5nbvw6sorom3` |

Los RSS redirigieron a la identidad DID y devolvieron XML de aproximadamente 13–14 KB. La API devolvió JSON de aproximadamente 61–197 KB para un máximo solicitado de 30 registros. Son tamaños de estas respuestas, no límites ni estimaciones de consumo del servicio. La [referencia oficial de Bluesky](https://endpoints.bsky.app/) documenta `app.bsky.feed.getAuthorFeed`, `app.bsky.actor.getProfile` y el acceso público a buena parte de las consultas `app.bsky.*`. El RSS es una ruta real observada; no se encontró aquí una garantía documental de conservación de esa ruta.

Para un adaptador: guardar URI estable del post, autor DID, fecha original, texto y enlaces explícitos; filtrar reposts o distinguir su autoría. No incluir likes/reposts en la huella de contenido relevante. Un cambio de nombre de cuenta no debe producir publicaciones nuevas. Comprobar identidad cuando cambie el handle y conservar el DID aprobado. Usar RSS o API como una sola fuente lógica para evitar alertar dos veces por el mismo post.

### YouTube

- [Atom del canal de Magic](https://www.youtube.com/feeds/videos.xml?channel_id=UC8ZGymAvfP97qJabgqUkz4A): HTTP 200, 18.482 bytes.
- [Atom de la lista WeeklyMTG](https://www.youtube.com/feeds/videos.xml?playlist_id=PL3rP64NRtmbjdg_j75RqbTu5Ffpc-Q_9s): HTTP 200, 15.757 bytes.

Deduplicar por `videoId`, compartido entre canal y lista. Son ventanas recientes, no un archivo completo: muchos vídeos nuevos pueden desplazar uno relevante. El feed permite detectar una emisión publicada o su título; no demuestra qué se dijo dentro del vídeo. [Google documenta las notificaciones Atom de YouTube](https://developers.google.com/youtube/data/guides/push_notifications), que requieren un receptor público para entrega push. El sondeo de estos feeds conserva el despliegue actual sin puertos públicos.

## Ejemplos concretos de aviso anticipado

Estos ejemplos proceden de textos y fechas devueltos por los feeds oficiales. Las fechas siguientes se expresan en UTC. No se afirma que cada canal publique siempre antes que los demás.

| Publicación | Qué permite detectar | Qué no permite concluir |
| --- | --- | --- |
| [Secret Lair, 29/09/2026](https://bsky.app/profile/mtgsecretlair.com/post/3mwo75g7xmq2g) | Corn Maze Superdrop anunciado para el 12 de octubre. | Stock o precio de un producto EU. |
| [Secret Lair, 05/10/2026](https://bsky.app/profile/mtgsecretlair.com/post/3mx5bwv4cgo25) | Festival in a Box/Secret Gallery Atlanta anunciado para el 19 de octubre. | Que todos sus componentes se vendan por separado o lleguen a todas las regiones. |
| [Secret Lair, 10/10/2026](https://bsky.app/profile/mtgsecretlair.com/post/3mxiacge5m22w) | Primeras cartas del kit Marvel’s History of Heroes reveladas en NYCC. | El producto completo a partir de una imagen parcial. El [artículo de lanzamiento en Magic](https://magic.wizards.com/en/news/announcements/secret-lair-countdown-kit-marvels-history-of-heroes) está fechado el 16/10/2026: en este caso el post precedió al artículo específico. |
| [Secret Lair, 13/10/2026](https://bsky.app/profile/mtgsecretlair.com/post/3mxrfoaxpqc2d) | Duality Distorted anunciado como próximo contenido de Chaos Vault. | Una fecha exacta si el texto no la proporciona. |
| [Secret Lair, 14/10/2026](https://bsky.app/profile/mtgsecretlair.com/post/3mxtw55krbd2d) | Strange School anunciado para Chaos Vault. | Disponibilidad comercial verificable. |
| [Secret Lair, 16/10/2026](https://bsky.app/profile/mtgsecretlair.com/post/3mxyx2yq2js26) | Fecha del 2 de noviembre para el kit Marvel’s History of Heroes. | Que un recordatorio posterior sea otro producto nuevo. |
| [WeeklyMTG, 13/10/2026](https://www.youtube.com/watch?v=OJHzx9BDLyg) | Programa titulado Secret Lair Drop Reveal, junto a discusión de cambios de reglas. | Los detalles del drop antes de extraer evidencia adicional del contenido. |
| [MTG Festivals, 07/10/2026](https://bsky.app/profile/mtgfestivals.com/post/3mxcjlbygjp2d) | Publicación de la agenda Mana Stage de MagicCon Atlanta. | Que cada actividad de esa agenda vaya a anunciar un drop. |

También aparecen incidencias de colas de compra, recordatorios y marketing. Deben ser tipos de evento distintos o no notificar según las reglas. Los anuncios globales se modelan como anuncios; la disponibilidad EU sigue dependiendo de la tienda EU y de indicadores verificables.

## Correo, convenciones y colaboradores

En la [página EU de Chaos Vault](https://secretlair.wizards.com/eu/chaosvault) se comprobaron dos formularios diferentes: uno dedicado a avisos de nuevos lanzamientos de Chaos Vault y el boletín general de Secret Lair. El artículo oficial [What Is the Secret Lair Chaos Vault?](https://magic.wizards.com/en/news/announcements/what-is-the-secret-lair-chaos-vault), del 10/01/2025, recomienda el correo para estos lanzamientos de calendario poco convencional. No se sometieron formularios ni se investigó una API privada de suscripciones.

WPN confirma en su [explicación de Secret Lair para tiendas](https://wpn.wizards.com/en/news/secret-lair-at-wpn-stores-how-does-it-work) que los miembros reciben correos para determinadas distribuciones. Es una vía para tiendas participantes; no debe prometerse ese acceso a un consumidor ni buscarse un buzón ajeno.

Una futura entrada de correo requiere configuración expresa del usuario: buzón dedicado y acceso IMAP de lectura o reenvío controlado. Antes de habilitarla, comprobar remitentes y autenticación a partir de mensajes reales autorizados, sin inventar direcciones. Deduplicar con Message-ID y huella de campaña; excluir datos personales, seguimiento, pedidos y enlaces de baja antes del análisis. No ejecutar adjuntos ni visitar automáticamente enlaces recibidos. El correo documenta un anuncio, no demuestra stock.

Las colaboraciones merecen una lista permitida por proyecto, porque el socio puede anunciar algo durante NYCC u otra convención. Se localizó el [anuncio oficial de Marvel sobre Darkhold y un cómic relacionado](https://www.marvel.com/articles/culture-lifestyle/magic-the-gathering-marvel-darkhold-destiny-original-story-tie-in-comic), pero devolvió **403** tanto por lectura web como por HTTP directo: su contenido no quedó verificado en esta revisión y no se propone un selector. Para campañas benéficas sí existe un ejemplo primario accesible en Magic: [Secret Lair x Global Fund for Women](https://magic.wizards.com/en/news/announcements/secret-lair-x-global-fund-for-women-their-magic-is-limitless), publicado el 06/07/2026. Los socios, convenciones y acciones benéficas amplían el descubrimiento; deben enlazar evidencia primaria y mantener región y canal de venta separados.

## Restricciones y decisiones para una futura implementación

1. **Primero Bluesky Secret Lair**, mediante un adaptador RSS o API pequeño, con intervalo prudente, límites de tamaño y persistencia. Después WeeklyMTG y MTG Festivals. Magic general requiere filtros de relevancia más estrictos.
2. **X, Instagram y Facebook** quedan como canales complementarios. No introducir Chromium ni depender de un HTML sujeto a login, bloqueos y cambios. La [documentación actual de X](https://docs.x.com/x-api/introduction) describe acceso con credenciales y pago por uso; verificar condiciones de la cuenta antes de configurar una integración. No se ha probado una API de Meta autorizada para estas cuentas.
3. **Twitch** puede señalar un directo de revelaciones, pero no reemplaza la extracción de productos. Su [documentación oficial](https://dev.twitch.tv/docs/api/get-started) requiere registro de aplicación y autenticación para los recursos de API descritos. No se solicitó ni usó ninguna credencial.
4. **Imágenes y vídeo:** un texto breve puede omitir nombre, fecha o cartas presentes en una imagen. El modelo textual configurado no convierte automáticamente esas imágenes en evidencia. Guardar el enlace y marcar incertidumbre; OCR, visión o transcripción serían tareas adicionales expresas, con límites y pruebas propios. No inventar un nombre a partir de marcas de copyright.
5. **Análisis y reglas:** tratar las publicaciones como entrada no confiable. El LLM puede resumir o proponer categorías a partir del texto recibido; su memoria no es una fuente de primicias. Las fechas, URLs y disponibilidad necesitan evidencia. Una inferencia no debe activar navegación arbitraria ni convertir un teaser en una venta confirmada.
6. **Cruce y deduplicación:** una campaña aparece en varias redes, vídeo, correo y artículos. Conservar identificadores por origen y relacionarlos con un mismo acontecimiento cuando exista evidencia determinista; no fusionar productos solo porque el modelo los considere parecidos. Una nueva fuente no debe generar una avalancha histórica.

Las respuestas de las comprobaciones se conservaron localmente como material de investigación en `work/research/social/`, con metadatos de URL, hora, estado y tamaño. No forman parte de una garantía de disponibilidad futura ni de una medición del contenedor. No se ha comprobado acceso a estas fuentes desde la red de Portainer/Proxmox.
