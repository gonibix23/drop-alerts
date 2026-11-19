# Tabletop Gamers: productos y reservas

Comprobado el **19 de noviembre de 2026**, con peticiones HTTPS, TLS verificado y el transporte `SourceHTTP` del servicio. Las capturas completas están en `work/research/tabletop/`, excluido de Git; los fixtures contienen extractos reales reducidos. No se hicieron compras, consultas al modelo ni envíos a Discord.

## Método verificado

La [tienda](https://tabletopgamers.es/) utiliza WooCommerce y entrega HTML del servidor. El adaptador `TabletopGamersSource` (`tabletop_gamers`) consulta estos listados públicos y las fichas individuales enlazadas:

- [Categoría TCG](https://tabletopgamers.es/product-category/tcg/): se observaron tres páginas y 50 productos, con enlace HTML «Entradas anteriores» para la siguiente página.
- [Novedades](https://tabletopgamers.es/producto/novedades/): incluye otros juegos, por lo que solo se aceptan tarjetas con categorías de cartas o accesorios verificadas.
- [Preventa](https://tabletopgamers.es/producto/pre-venta/): destino real de la redirección del enlace `/product-tag/reserva/` anunciado en portada.
- [Fundas y protección](https://tabletopgamers.es/product-category/fundas/): se observaron 17 productos, incluidas hojas de álbum y accesorios para cartas.

Las tarjetas `ul.products li.product.type-product` proporcionan el ID estable `post-<número>`, nombre y URL individual. Las fichas se identifican por `div.product.type-product#product-<número>` y su `.summary.entry-summary`. El JSON-LD de All in One SEO contiene un `Product` dentro de `@graph`, con oferta `Offer`, precio, moneda y disponibilidad. El código exige que la URL, identidad, título y hechos de la oferta principal coincidan; no toma stock de recomendaciones, reseñas, carrito, cabecera o pie.

El [robots.txt](https://tabletopgamers.es/robots.txt) publica sitemaps y, para rastreadores generales, excluye `/wp-json/`, acciones de carrito y URLs con query strings. El monitor no utiliza REST, filtros, búsqueda ni parámetros de ordenación/paginación. La paginación usada es la ruta HTML explícitamente enlazada. No se añade navegador ni se usa otra identidad para sortear pantallas de acceso. Los grupos específicos de rastreadores de IA están bloqueados; el servicio se identifica como `drop-alerts`, que realiza monitorización determinista y no entrenamiento. Revisa las condiciones y robots del sitio si cambian.

## Qué se considera un producto y un cambio

Se admiten cartas, sobres, cajas, mazos, colecciones y protección de cartas en las categorías observadas. Los torneos, entradas y productos ajenos a las cartas se excluyen. Un kit físico de Prerelease puede ser un producto; una entrada «Prerelease One Piece OP18 día 21» es un evento y no se convierte en stock de cartas.

El juego se identifica a partir del propio título, categorías o etiquetas de la ficha. Por ejemplo, «Commander Marvel Super Heroes — Wakanda Forever» lleva etiqueta `magic-tg` y puede etiquetarse como `magic` aunque su título no diga Magic. Nunca se utiliza el menú completo para atribuir un juego. Se reconocen `magic`, `one_piece`, `pokemon`, `riftbound`, `lorcana`, `dragon_ball`, `digimon`, `yugioh`, `star_wars_unlimited` y `cyberpunk`. Un accesorio genérico conserva su condición de accesorio sin inventar un juego. La selección `ENABLED_TCGS` sigue aplicándose; reconocer una etiqueta adicional no activa por sí solo ese juego.

La identidad es `product:<ID WooCommerce>`. Dos productos separados por idioma o edición mantienen IDs y precios independientes. Las fichas examinadas eran de tipo simple. Las fichas variables futuras, sin variantes verificables, se rechazan como error de extracción: el padre no acredita que todas sus variantes estén disponibles ni un precio común.

La disponibilidad se apoya en el estado estructurado y el texto `.stock` de la ficha principal: `DISPONIBLE`/`InStock` → `AVAILABLE`; `AGOTADO`/`OutOfStock` → `UNAVAILABLE`; `RESERVA`/`PreOrder` → `UPCOMING`. Si WooCommerce marca una reserva comprable como `InStock` en sus metadatos, el rótulo explícito `RESERVA` mantiene `UPCOMING`. Una política genérica de pedidos pendientes no se transforma en existencias o preventa confirmada. Los estados contradictorios, incompletos o páginas HTTP fallidas conservan la observación anterior.

El precio debe estar en EUR tanto en la oferta como en el precio actual visible. Se ignora el importe tachado y no se utiliza un rango de variantes como precio único. Los importes se normalizan para que `120`, `120.0` y `120.00` no generen cambios diferentes. No se suman envío, descuentos de cuenta ni condiciones del checkout, que no se consulta.

Algunos listados mostraban «Lanzamiento aprox.» con día concreto, pero las fichas examinadas no repetían ese dato. Esta versión no mezcla esa fecha del listado con las consultas rotatorias de detalle: si la propia ficha no ofrece una fecha de lanzamiento interpretable, queda sin confirmar. No se deriva una fecha de venta por estar en reserva ni de una reseña.

## Límites y referencia inicial

Cada ronda consulta las cuatro portadas anteriores y, por defecto, una página adicional rotatoria del catálogo TCG (`max_pages=2`). El constructor del adaptador usa ocho fichas (`max_items=8`); el registro del servicio configura hasta `min(12, SOURCE_MAX_ITEMS)`, por lo que el stack predeterminado puede revisar doce fichas por ronda. Se intercalan novedades y productos conocidos, con presupuesto total de 90 segundos. Cada petición tiene además un máximo local de 20 segundos, aunque el tiempo HTTP global sea mayor; un detalle lento deja continuar los demás cuando queda presupuesto.

Los cursores y el primer turno de esas dos cuotas se conservan en SQLite. Se alterna la primera cuota entre rondas y el cursor solo avanza al intentar el trabajo rotatorio: agotar el tiempo no salta fichas que aún no se intentaron ni deja siempre las reposiciones detrás de una novedad lenta.

Los productos conocidos permanecen en la rotación aunque dejen de aparecer en una portada, para detectar reposiciones. La ausencia en un listado, un error HTTP o un cambio de estructura no significa agotado o retirada. El histórico no se explora de una vez: el catálogo TCG se recorre por páginas enlazadas y las fichas por ventanas. No se promete cobertura total de todas las categorías, stock por almacén ni detectar productos que aparezcan y desaparezcan entre dos consultas.

`bootstrap_ids` contiene los IDs realmente observados, incluso de fichas diferidas. Cada página correctamente validada tiene un inventario inicial independiente. Con `BOOTSTRAP_MODE=silent`, abrir una página histórica por primera vez o completar detalles tras un reinicio no genera una avalancha de avisos. Un producto nuevo en una página ya inicializada sí puede producir `product.new`. Los inventarios incompletos no se cierran y una ficha fallida no reemplaza su último estado guardado.

## Resultado de comprobación

Una consulta real final mediante `SourceHTTP`, SQLite en memoria, TLS activo y sin IA/webhook extrajo **ocho productos**, de cinco páginas de catálogo, sin errores parciales: reservas de Riftbound y Cyberpunk, además de artículos disponibles de Lorcana y Magic. El arranque silencioso dejó **cero notificaciones pendientes**. Estas cifras pertenecen a esa ventana concreta, no al inventario completo ni a tu entorno de Portainer.

Las **29 pruebas** de `tests/test_tabletop_source.py` no requieren red. Cubren extracción, precio rebajado, reservas, agotados y reposiciones simuladas, fallos parciales, límites y cursores, una novedad lenta junto a una reposición rápida, exclusión de eventos, kit de Prerelease, URLs e imágenes externas, variantes no verificadas, conservación de identidad, arranque silencioso y deduplicación tras reinicio. No se observó un producto TCG agotado en las capturas examinadas; el cambio a agotado y su reposición se validaron con modificaciones explícitas de esas respuestas guardadas.
