# Fuentes para anticipar Secret Lair y lanzamientos especiales de Magic

Investigación realizada el **21 de octubre de 2026**, con prioridad en España/UE. Se revisaron las fuentes del servicio, páginas oficiales, canales sociales, feeds editoriales y calendarios comunitarios. No es un inventario exhaustivo de Internet: las colaboraciones y exclusivas pueden anunciarse en canales nuevos.

**Estado del servicio:** siguen implementadas y activadas por defecto `secret_lair_eu` y `magic_news`. Este documento y sus anexos son investigación y propuestas de ampliación; no activan adaptadores nuevos ni suscripciones.

## Conclusión

La cobertura más útil combina la tienda EU, Chaos Vault, el archivo de anuncios de Magic y el canal oficial de Secret Lair en Bluesky. WPN y MagicCon aportan exclusivas de tiendas y convenciones que una vigilancia exclusiva de la tienda online puede pasar por alto. WeeklyMTG y los boletines oficiales añaden avances, aunque parte de su contenido necesita interpretación o acceso configurado por el usuario.

Los medios y calendarios comunitarios sirven para descubrir indicios y reunir fechas. Deben conservar su procedencia y confirmar los datos de compra en la fuente oficial correspondiente. Un calendario, una carta añadida a una base de datos o un anuncio no prueban disponibilidad en Europa.

## Selección priorizada

| Fuente | Qué aporta | Consulta comprobada o vía de acceso | Prioridad propuesta |
| --- | --- | --- | --- |
| [Secret Lair EU](https://secretlair.wizards.com/eu/) y sus fichas | Anuncios, productos, precio y disponibilidad de la región | HTML, catálogo público descubierto en la página y JSON-LD; integración actual | Esencial; mantener |
| [Chaos Vault EU](https://secretlair.wizards.com/eu/chaosvault) | Drops sorpresa, experimentales, bundles y productos especiales | Página oficial accesible por HTTP; requiere extracción propia de su estructura | Muy alta |
| [Magic: anuncios](https://magic.wizards.com/en/news/announcements), [archivo](https://magic.wizards.com/en/news/archive?author=all&category=all&order=newest&page=1) y [sitemap](https://magic.wizards.com/en/sitemap.xml) | Anuncios que desaparecen de la portada, detalles y correcciones | HTML de anuncios y sitemap comprobados; archivo localizado, con extracción completa pendiente de validar. No se encontró RSS anunciado en las páginas examinadas | Muy alta; ampliar el adaptador actual |
| [Secret Lair en Bluesky](https://bsky.app/profile/mtgsecretlair.com) | Revelaciones, avisos y recordatorios oficiales | [RSS público](https://bsky.app/profile/mtgsecretlair.com/rss) y API pública comprobados sin credencial; cuenta vinculada por WPN | Muy alta |
| [WPN: noticias](https://wpn.wizards.com/en/news) y [productos](https://wpn.wizards.com/en/products?type=magic) | Secret Lair distribuido a tiendas, exclusivas y promociones retail | HTML oficial comprobado; requiere separar producto, evento y promoción | Alta para especiales |
| [MagicCon: noticias](https://www.mtgfestivals.com/global/en-us/magiccon-news.html) y páginas de cada evento | Festival in a Box, Secret Gallery, Roadshow, promos y ventas presenciales | HTML y catálogos oficiales; algunos materiales son PDF | Alta para especiales |
| [WeeklyMTG en YouTube](https://www.youtube.com/playlist?list=PL3rP64NRtmbjdg_j75RqbTu5Ffpc-Q_9s) y [canal Magic](https://www.youtube.com/channel/UC8ZGymAvfP97qJabgqUkz4A) | Presentaciones y avances antes de la venta | Canal y playlist oficiales descubiertos desde Magic; feeds XML comprobados | Media como señal adicional; no acredita el contenido del vídeo |
| Boletines de Secret Lair y Chaos Vault | Notificación directa del editor, especialmente para lanzamientos sorpresa | Suscripción oficial; su lectura automática exige un buzón o reenvío autorizado | Alta; requiere configuración del usuario |
| [Magic](https://bsky.app/profile/magic.wizards.com) y [MTG Festivals en Bluesky](https://bsky.app/profile/mtgfestivals.com) | Anuncios generales, colaboraciones, convenciones y agendas | RSS y API públicos comprobados; necesitan filtros más estrictos que Secret Lair | Media/alta |
| [Hasbro Newsroom](https://newsroom.hasbro.com/) y comunicados de colaboradores | Anuncios de asociaciones y exclusivas especiales | Contenido visible en búsqueda/web; el acceso HTTP al newsroom devolvió bloqueo en esta investigación | Complementaria |
| [Beadle & Grimm's](https://beadleandgrimms.com/pages/secret-lair-x-beadle-grimms-faq) y [campañas benéficas oficiales](https://magic.wizards.com/en/news/announcements/secret-lair-x-global-fund-for-women-their-magic-is-limitless) | Colaboraciones especiales, productos exclusivos y ventas con finalidad benéfica | Páginas primarias localizadas; Here Be Dragons es un antecedente histórico, no un próximo drop. No se ha validado un feed específico de B&G | Complementaria, con categorías propias |
| [MTGGoldfish](https://www.mtggoldfish.com/feed), [MagicSpoiler](https://www.magicspoiler.com/feed/), [MTGDrops](https://mtgdrops.com/feed.xml) y [Star City Games](https://articles.starcitygames.com/feed/) | Descubrimiento editorial de anuncios y recopilaciones | Atom/RSS comprobados; cobertura, campos y ruido diferentes | Complementaria, con confirmación oficial |
| [SecretLair.gg](https://secretlair.gg/) y su [calendario ICS](https://secretlair.gg/calendar.ics) | Calendario agregado y clasificación de drops | ICS comprobado, con intervalo de actualización anunciado de 12 horas y señales de retraso | Calendario auxiliar |
| [Scryfall](https://scryfall.com/docs/api/sets) | Identificación de cartas y colecciones reveladas | API de sets comprobada; SLD agrupa muchos drops, no representa su calendario de ventas | Enriquecimiento, no alerta principal |
| Comunidades Reddit de Secret Lair y Magic | Avisos, capturas, calendarios y rumores de la comunidad | La consulta HTTP de comunidades no proporcionó una lista de publicaciones utilizable; además cambia el acceso de la plataforma | Investigación manual o integración aprobada específica |

Los enlaces y las pruebas detalladas se encuentran en los tres anexos. La prioridad es una valoración técnica para este servicio, no una garantía de que un canal publique siempre antes que los demás.

## Huecos detectados en la cobertura actual

1. **La portada de Magic no equivale al archivo de anuncios.** En la captura examinada, el adaptador reconoció ocho artículos de portada y solo uno mencionaba Secret Lair en el título. El [Countdown Kit: Marvel's History of Heroes](https://magic.wizards.com/en/news/announcements/secret-lair-countdown-kit-marvels-history-of-heroes), anunciado el 16 de octubre para una venta el 2 de noviembre de 2026, no figuraba entre esas ocho URLs. El anuncio sí estaba representado en la portada de Secret Lair; es un ejemplo de cobertura complementaria, no de un aviso que necesariamente se haya perdido en ambas fuentes.
2. **Chaos Vault merece una consulta explícita.** La página existe y está enlazada oficialmente, pero no hay que asumir que su estructura o todos sus productos se incluyen en los feeds extraídos de la portada EU.
3. **Las correcciones y nuevas ventanas de venta merecen seguimiento.** Conviene volver a comprobar anuncios futuros guardados, además de descubrir URLs nuevas. Por ejemplo, la [actualización de The Zeta Set del 1 de octubre](https://www.magic.wizards.com/en/news/announcements/an-update-on-the-zeta-set-sale) anuncia una nueva venta de 24 horas el 9 de diciembre de 2026: no es un producto distinto ni un simple restock ya disponible.
4. **El filtro actual de noticias busca «secret lair».** Para otros especiales faltan reglas que identifiquen, con contexto, Festival in a Box, Secret Gallery, Roadshow, exclusivas WPN y promociones con cartas. «MagicCon», «Commander» o «Universes Beyond» por sí solos producirían demasiado contenido ajeno a drops especiales.
5. **La deduplicación actual es por fuente e identidad.** Añadir varios medios que repitan un lanzamiento necesita correlación adicional para evitar varios avisos equivalentes. No deben fusionarse regiones, ediciones o eventos distintos solo por compartir un título parecido.

## Hallazgos que evitan falsas alertas

- **Sitemap:** una URL nueva para el monitor no es necesariamente una publicación nueva. Se comprobó que un artículo de 2016 tenía `lastmod` de octubre de 2026. `lastmod` sirve para seleccionar páginas a revisar; la fecha editorial y el contenido determinan qué se anunció.
- **Fechas:** venta, preventa, salida, envío, legalidad de cartas y celebración de un evento son conceptos diferentes. La [tabla oficial de producción y envíos](https://secretlair-support.wizards.com/hc/en-us/articles/5149533669652-Secret-Lair-Production-and-Shipping-Status) distingue regiones y varios de esos hitos. Un envío previsto no es una apertura de ventas.
- **Región:** un aviso global o estadounidense puede adelantar el anuncio, pero precio, moneda y disponibilidad EU deben comprobarse en EU. Las exclusivas presenciales necesitan lugar y restricciones de compra.
- **Calendarios:** la página de SecretLair.gg aún presentaba el evento del 19 de octubre como próximo en la captura del 21 de octubre; su ICS conservaba marcas de actualización del 13 de octubre. Es útil para contrastar, no para afirmar el siguiente drop sin otra evidencia.
- **Timestamps de feeds:** el Atom de MTGGoldfish mostraba valores `updated` idénticos en entradas diferentes. No deben usarse automáticamente como cambios semánticos del artículo. Algunas entradas RSS de MTGDrops no llevan `pubDate`; debe mantenerse la fecha como desconocida.
- **Reddit:** el [anuncio oficial de octubre de 2026](https://www.reddit.com/r/modnews/comments/1x6rjnd/mod_monthly_your_october_2026_newsletter_is_here/) comunica el fin del soporte RSS el **13 de noviembre de 2026** y una transición de su API. No conviene crear ahora una dependencia nueva de RSS de Reddit.
- **HTTP 200:** puede contener una pantalla de acceso, mantenimiento o una aplicación sin publicaciones. La respuesta HTTP no sustituye la validación del contenido.
- **Vídeos e imágenes:** un feed informa del título y publicación, pero no demuestra qué se anunció verbalmente o en una imagen. El modelo de texto actual no aporta lectura de imágenes ni transcripción de vídeos por sí solo.

## Cómo ampliaría el servicio

**Primera fase:** extender el descubrimiento de Magic con anuncios/archivo y revisión de anuncios futuros; añadir Chaos Vault EU y el RSS oficial de Secret Lair en Bluesky. Reutilizar la identidad canónica de los artículos de Magic para que portada y archivo no creen dos eventos del mismo artículo.

**Segunda fase:** WPN, MagicCon y WeeklyMTG, con reglas específicas para productos y promociones especiales. Conservar una etiqueta de venta online EU, retail, presencial u otra región. Añadir los boletines únicamente cuando el usuario configure su recepción.

**Tercera fase:** una selección de medios RSS y el calendario comunitario como indicios secundarios. Asociar las referencias al lanzamiento identificado y mostrar claramente la procedencia y lo que falta confirmar.

El alta de fuentes debe tener referencia inicial silenciosa, reintentos limitados, caché, deduplicación y pruebas con respuestas guardadas. No deben generarse avisos históricos por importar un sitemap o un calendario. Para informar de futuros drops ya anunciados al instalar el servicio sería útil un resumen inicial separado; actualmente esa modalidad no existe y no se debe simular vaciando la base de datos.

La planificación por fuente también necesita ampliación: el servicio actual tiene un intervalo global. Como orientación futura, las señales ligeras de tienda/Bluesky pueden revisarse cada pocos minutos, WPN/MagicCon y medios con menos frecuencia, y el ICS respetando su horizonte de actualización. No son variables de entorno nuevas que ya se puedan configurar.

El modelo puede interpretar relevancia, fechas y diferencias cuando el texto lo permita. Los resultados siguen siendo propuestas: el código debe preservar evidencias, regiones, tipos de fecha y el origen de cada afirmación. Las URLs a visitar deben proceder de adaptadores y listas permitidas, no de decisiones libres del modelo.

## Anexos y evidencias

- [Fuentes oficiales](research-official-sources.md).
- [Redes, vídeo y correo](research-social-sources.md).
- [Medios, calendarios y comunidad](research-secondary-sources.md).
- [Investigación de las dos integraciones originales](source-research.md).

Las respuestas completas y registros de sondeo utilizados durante el trabajo están en `work/research/`, excluidos de Git. Los anexos distinguen las consultas HTTP directas de lo observado mediante la herramienta web, los errores de acceso y las propuestas aún no implementadas. Las pruebas desde el equipo de desarrollo no confirman la conectividad desde Proxmox/Portainer.
