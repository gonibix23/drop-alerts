# Fuentes de Pokémon TCG comprobadas

Revisión del **25 de octubre de 2026**, mediante peticiones HTTPS de lectura con verificación TLS. Las capturas completas y diagnósticos están en `work/research/pokemon/`, excluidos de Git. Las pruebas conservan fragmentos breves de los documentos reales en `tests/fixtures/pokemon_*` y no requieren conexión.

## Fuentes implementadas

| ID del adaptador | Fuente oficial | Acceso observado y cobertura |
| --- | --- | --- |
| `pokemon_tcg_news_es` | [Noticias del portal de JCC Pokémon](https://tcg.pokemon.com/es-es/news/) | HTTP 200 con tarjetas de noticias en HTML estático. Se toman las tarjetas que el editor etiqueta como productos y se excluyen estrategia, entrevistas, retransmisiones, campeonatos y aplicaciones Pocket/Live. No necesita ejecutar JavaScript. |
| `pokemon_press_es` | [Prensa internacional oficial de Pokémon en español](https://pokemon.gamespress.com/es) | HTTP 200 en listado y artículos examinados. Admite comunicados físicos de JCC Pokémon y extrae el cuerpo completo, fecha editorial e imagen de la nota. Se excluyen anuncios exclusivamente digitales y se acotan las consultas de detalles. |
| `pokemon_products_es` | [Galería oficial de productos en español](https://www.pokemon.com/es/jcc-pokemon/galeria-de-productos) | La primera captura HTTP 200 contenía 37 fichas identificables sin JavaScript. Una consulta posterior con el transporte del servicio devolvió una pantalla de verificación con HTTP 200. El adaptador reconoce el bloqueo y falla conservando el estado; se recomienda mantenerlo opcional hasta comprobar la red del despliegue. |
| `pokemon_products_us` | [Galería oficial de productos estadounidense](https://www.pokemon.com/us/pokemon-tcg/product-gallery) | La captura inicial contenía 44 fichas, incluidas ediciones exclusivas de Pokémon Center. Después apareció la misma verificación. Consultar una ficha editorial no acredita stock en Pokémon Center. Fuente opcional y región US separada. |
| `pokemon_news_jp` | [Noticias de Pokémon Card Game Japón](https://www.pokemon-card.com/info/) | HTTP 200 con el inventario de noticias del año en HTML. Se toman anuncios de packs, barajas y conjuntos de cartas en la categoría de productos; se excluyen figuras y resultados de eventos. Fuente japonesa opcional, sin equiparar sus productos o fechas con una venta europea. |

La ejecución conjunta de los adaptadores mediante `SourceHTTP` obtuvo contenido válido de noticias TCG ES, prensa ES y noticias JP. Las dos galerías rechazaron correctamente la respuesta de verificación. Son resultados de esta consulta, no garantías de acceso futuro ni pruebas desde Proxmox.

Los constructores son `PokemonProductsSource(max_items=...)`, `PokemonUSProductsSource(max_items=...)`, `PokemonTCGNewsSource(max_items=...)`, `PokemonPressSource(max_articles=..., max_duration_seconds=...)` y `PokemonJapanNewsSource(max_items=...)`.

## Qué significan los elementos

Las galerías anuncian identidades de productos: colección, caja de Entrenador Élite, lata, lote de sobres, baraja o edición especial. El adaptador guarda `kind=product` y `state=UNKNOWN`, sin inventar precio, venta abierta ni existencias. El título, URL e imagen provienen de la tarjeta oficial. No se visitan fichas de productos durante cada comprobación porque las respuestas de detalle examinadas estaban bloqueadas.

El portal TCG genera anuncios a partir de las tarjetas publicadas. Su contenido puede incluir avances de cartas o lanzamientos, pero la tarjeta no demuestra la fecha editorial ni lo que se explica únicamente en el artículo enlazado. `coverage=listing_only` y `published_at=null` conservan esa limitación. Una palabra como «ya a la venta» en el título no transforma el estado comercial en `AVAILABLE`.

La prensa sí permite leer los párrafos de las notas. En el [comunicado de Megaevolución-Dominio Delta](https://pokemon.gamespress.com/es/ALERTA-INFORMATIVA-La-nueva-expansion-del-Juego-de-Cartas-Coleccionabl), por ejemplo, aparecen una fecha de lanzamiento físico, otra digital para JCC Pokémon Live y otra de torneos de Prelanzamiento. El adaptador separa la fecha editorial y omite del contenido de fechas físicas las secciones explícitas digitales o de Prelanzamiento. Registra cuántas secciones se omitieron y conserva el enlace para consultar la nota íntegra. No se utiliza la fecha de una aplicación como fecha de los sobres físicos.

Los datos incluyen `tcg=pokemon`, `language`, `region`, `channel`, `provenance=official`, resumen y evidencia. Las noticias españolas son `region=GLOBAL`, `language=es`: el idioma de una noticia no prueba que un producto esté disponible en España ni que sus cartas sean españolas. Las galerías estadounidenses y noticias japonesas conservan `US` y `JP`, respectivamente.

## Límites de acceso comprobados

- [Noticias generales en español](https://www.pokemon.com/es/noticias-pokemon) y [en inglés](https://www.pokemon.com/us/pokemon-news) redirigieron a las rutas nuevas `/es/noticias` y `/us/news`. La respuesta final fue HTTP 200 con título **Pardon Our Interruption**, sin noticias utilizables. No se da por extraída una página por su código HTTP.
- Las fichas de galería y artículos enlazados de `www.pokemon.com` probados también devolvieron esa verificación. Por eso el portal TCG conserva la información verificable del listado y no sustituye un artículo válido almacenado por el texto del bloqueo.
- [Pokémon Center US](https://www.pokemoncenter.com/) y [UK](https://www.pokemoncenter.com/en-gb) devolvieron **403**. No se incluyen monitorización de stock, precios, colas o API comercial no verificada de esa tienda. No se añade un navegador ni se modifica la identidad del cliente para sortear las protecciones.
- El [sitemap principal](https://www.pokemon.com/sitemap.xml) respondió, pero esta integración no lo trata como calendario de lanzamientos ni hace una descarga masiva del sitio. No se encontró aquí un RSS oficial anunciado que sustituya los listados implementados.

## Operación y pruebas

Los adaptadores de listados realizan una consulta por ronda y seleccionan una ventana acotada de elementos, con prioridad para identidades nuevas y revisión rotatoria persistida. Devuelven el inventario completo observado en `bootstrap_ids` para que la primera comprobación sea silenciosa también al importar sus ventanas posteriores. La prensa limita detalles y tiempo total; un artículo fallido no reemplaza la versión guardada y los demás pueden procesarse.

La desaparición de una tarjeta no significa agotado o retirada del producto. Los errores de red o estructura son errores de extracción. Una lista de noticias reconocible sin productos relevantes puede ser una comprobación correcta sin nuevos elementos.

Las pruebas cubren galerías ES/US, exclusivas editoriales Pokémon Center sin stock, noticias físicas frente a Pocket/Live, secciones digitales y de Prelanzamiento, región/idioma, imágenes y URLs permitidas, bloqueo HTTP 200, cambios de estructura, presupuesto de consulta, rotación y arranque silencioso tras reinicio. La interpretación de japonés es conservadora: el adaptador conserva texto y fecha editorial, pero no traduce automáticamente un cartel ni inventa la fecha de venta occidental.
