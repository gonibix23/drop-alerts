# Animefan: cartas TCG y accesorios relacionados

Comprobado el **19 de noviembre de 2026**, mediante consultas HTTPS con TLS verificado y el transporte real `SourceHTTP`. La tienda ofrece principalmente figuras y merchandising, pero también tiene catálogos de juegos de cartas. El alcance predeterminado de `AnimefanSource` es **solo TCG y accesorios de esos juegos**: una figura de Pokémon, One Piece o Dragon Ball no se clasifica como un juego de cartas por su franquicia.

Las capturas completas y los diagnósticos se conservan en `work/research/animefan/`, excluido de Git. Los doce fixtures de `tests/fixtures/animefan_*` contienen fragmentos reales reducidos, sin scripts de seguimiento ni recursos completos. No se hicieron compras, peticiones al modelo ni envíos a Discord.

## Descubrimiento y extracción comprobados

El [robots.txt](https://animefan.es/robots.txt) anuncia el [índice de sitemaps](https://animefan.es/sitemap_index.xml), con mapas de productos y categorías. Los mapas de categorías examinados publicaban estas rutas, comprobadas con GET y HTTP 200:

- [Pokémon Juego de Cartas](https://animefan.es/categoria-producto/fabricante/pokemon-juego-de-cartas/): barajas, blísters, sobres, álbumes y conjuntos con cartas. La primera página examinada tenía 40 tarjetas y un enlace de paginación.
- [Cartas coleccionables](https://animefan.es/categoria-producto/grupo-producto/cartas-coleccionables/): productos de Magic y otras colecciones. El adaptador exige evidencia propia de que sea TCG; no acepta toda la categoría indiscriminadamente.

El catálogo [cartas](https://animefan.es/categoria-producto/grupo-producto/cartas/) incluye barajas `Playing Cards` de franquicias de anime y videojuegos. No se usa como inventario de TCG: un nombre como Yu-Gi-Oh! en una baraja de naipes no demuestra que sean cartas del juego. Las figuras y cartas coleccionables ambiguas sin evidencia de TCG se excluyen en el modo predeterminado.

Los listados estándar WooCommerce contienen `ul.products li.product.type-product`, ID estable `post-<número>`, categorías propias y enlace `a.woocommerce-LoopProduct-link`. La paginación usa los enlaces HTML `.woocommerce-pagination a.next`, sin construir consultas de búsqueda u ordenación. Cada página correctamente validada aporta su inventario inicial independiente.

Las fichas usan una plantilla Elementor con `div.product.type-product.elementor-location-single` y clases `post-<número>`. El título principal, precio y stock se leen de sus widgets específicos. Hay plantillas de productos recomendados anidadas en la misma página; se excluyen comprobando qué raíz de producto es propietaria de cada widget. El JSON-LD `Product`/`Offer` debe coincidir con la URL individual, el título y la identidad de la ficha consultada.

No se ejecuta JavaScript ni se usa REST, una API privada o un navegador. El monitor evita las rutas de carrito, cuenta y compra y las URLs con parámetros que excluyen los robots examinados. Los formularios sólo se leen para distinguir las modalidades de pago y nunca se envían.

## Qué se guarda y qué puede generar un aviso

La identidad es `product:<ID WooCommerce>`. Los productos separados por idioma conservan sus propios identificadores y precios. Las fichas examinadas eran simples; una ficha variable sin ofertas individuales verificables falla conservando el estado anterior, sin atribuir las existencias del padre a todos sus idiomas.

Las evidencias propias de TCG incluyen el fabricante `pokemon-juego-de-cartas`, la categoría de Magic y textos como TCG, JCC o Card Game, junto a formato de cartas o accesorios. Una categoría genérica «cartas coleccionables» y una franquicia de anime no bastan. Las colecciones de cartas que incluyen una figura siguen siendo productos de cartas. Los accesorios de TCG, por ejemplo un álbum Pokémon de su fabricante de cartas, se guardan como `card_accessory`.

Ejemplos de fichas comprobadas:

- [Blíster Eevee español](https://animefan.es/tienda/coleccion/pokemon/blister-cartas-30th-aniversario-pokemon-eevee-espanol/): el texto principal y la oferta indicaban agotado, independientemente de las recomendaciones disponibles de la página.
- [Álbum Pokémon español](https://animefan.es/tienda/coleccion/pokemon/album-juego-cartas-30th-aniversario-pokemon-espanol/): accesorio del juego de cartas, con precio y existencias propios.
- [Magic Aetherdrift en inglés](https://animefan.es/tienda/coleccion/magic-the-gathering/magic-the-gathering-aetherdrift-play-booster-display-30-english/): categoría y etiquetas de preventa; no se transforma en stock inmediato aunque se pueda reservar.

`AVAILABLE` requiere existencias expresas corroboradas por la oferta. `UNAVAILABLE` requiere agotado o sin existencias explícitos; los textos negativos no coinciden accidentalmente con «disponible». `UPCOMING` requiere reserva o preventa publicada por categoría, etiqueta o texto de stock. «Disponible bajo pedido» y un `BackOrder` genérico se guardan como `UNKNOWN`, con incertidumbre: no demuestran stock físico ni una fecha de lanzamiento. Los estados contradictorios o no reconocidos son errores de extracción.

El precio actual visible en EUR debe coincidir con la oferta principal. Se ignoran importes tachados, rangos y precios «desde». La tienda ofrece en algunas fichas pagar una reserva del 50 % o el importe completo: el depósito no se presenta como precio total. Cuando hay ese formulario, sólo se muestra precio verificado si la opción marcada y su texto acreditan pago completo. Un formulario sólo de señal, o marcado por defecto en depósito, deja el total sin confirmar. No se calculan envío ni descuentos del carrito.

Los datos incluyen `domain=tcg`, juego cuando está identificado, `product_category`, región EU, país ES, idioma de la fuente y procedencia de tienda. El idioma de la web no cambia el idioma publicado del producto. Las imágenes proceden únicamente de URLs de la propia tienda en `/wp-content/uploads/` y no se descargan durante la extracción.

## Rotación, límites y compatibilidad

El constructor es `AnimefanSource(max_items=12, max_pages=2, max_duration_seconds=90, include_collectibles=False)`. Por defecto se consulta la primera página de los dos catálogos y hasta una página adicional por catálogo. El archivo histórico rota mediante cursores persistidos. Después se comprueba una ventana de hasta doce fichas, intercalando novedades y productos conocidos; estos últimos se siguen revisando aunque dejen de aparecer en un listado.

Cada petición tiene un límite adicional de 20 segundos y cada ronda, 90 segundos. Una ficha lenta o fallida no bloquea indefinidamente las demás; se alterna el inicio de las cuotas de novedades y revisiones y el cursor avanza por trabajo realmente intentado. Cinco minutos entre rondas no significa que se revise cada ficha del catálogo cada cinco minutos ni garantiza detectar una venta fugaz.

`bootstrap_ids` contiene las identidades realmente observadas en los listados, incluidas las fichas diferidas. Los inventarios por página permiten registrar silenciosamente nuevos canales de descubrimiento y completar sus detalles tras reiniciar. Un error de consulta, una ficha eliminada o la ausencia en un listado no equivale a agotado. Los fallos parciales conservan los elementos extraídos correctamente y no sustituyen los anteriores por una página de bloqueo.

El código conserva una opción de coleccionables desactivada. Si se habilitara explícitamente, usaría además la portada Elementor y el catálogo general; los elementos tendrían `domain=collectibles`, franquicia separada y **ninguna etiqueta TCG inferida de su anime**. El inventario inicial de URLs de portada se resuelve a IDs WooCommerce por fichas, también de forma silenciosa en rondas posteriores. La configuración entregada mantiene este modo desactivado conforme al alcance solicitado de solo TCG.

## Verificación

- **34 pruebas** sin red aprobadas: catálogos reales, cartas y accesorios frente a figuras/naipes, precios rebajados, señal frente a total, stock y preventas, bajo pedido, recomendaciones anidadas, URLs e imágenes permitidas, variantes no verificadas, errores de estructura, paginación, límites, reposiciones fuera del listado y referencia inicial diferida tras reinicios.
- Consulta real del adaptador predeterminado con `SourceHTTP`, TLS activo, SQLite en memoria y sin IA/webhook: **12 productos Pokémon aceptados de cuatro páginas**, sin errores parciales; **0 notificaciones pendientes** al arrancar silenciosamente y **0 eventos nuevos** al repetir el mismo resultado. Esta ventana incluía un álbum, blísters y barajas; no representa el catálogo completo ni comprueba la conectividad desde tu Portainer.
- Los cambios de estado y reposiciones se simulan explícitamente en las pruebas; no se afirma haber observado un ciclo real completo de agotado a disponible durante el desarrollo.
