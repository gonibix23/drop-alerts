# JJCOLLECTION: productos y disponibilidad por variante

Investigación del **19 de noviembre de 2026**, con GET HTTPS y TLS verificado. Las capturas completas y el informe de trabajo están en `work/research/jjcollection/`, excluidos de Git. Los fixtures de `tests/fixtures/jjcollection_*` son fragmentos pequeños de respuestas reales y omiten scripts ajenos y datos de seguimiento.

## Fuentes y método comprobados

- [La tienda](https://www.jjcollection.es/) respondió HTTP 200. Su HTML identifica Shopify y enlaza productos, colecciones y variantes; no requiere ejecutar un navegador.
- [robots.txt](https://www.jjcollection.es/robots.txt) respondió HTTP 200 y permite páginas públicas de productos y sitemaps. Declara el [sitemap principal](https://www.jjcollection.es/sitemap.xml). Se respetan las exclusiones de carrito, cuenta, recomendaciones y consultas de ordenación; no se utiliza ninguna de ellas.
- El índice XML enlazaba `sitemap_products_1.xml` con sus parámetros numéricos reales `from` y `to`. La captura de productos ocupó unos 121 KB y contenía 216 entradas, incluidas la raíz y algunas duplicadas; la pasada del adaptador identificó 213 URLs de producto distintas. El código descubre esos parámetros del índice y no los fija como valores permanentes.
- Las fichas contienen JSON-LD `Product` o `ProductGroup.hasVariant`. Cada oferta de variante publica URL `?variant=<ID>`, `availability`, `price` y `priceCurrency`. El HTML incluye además el objeto literal `uppushOrderLimitProduct`, con el identificador, handle, tipo, etiquetas y variantes del producto. Se decodifica únicamente JSON mediante `JSONDecoder`; no se ejecuta JavaScript ni se utiliza una API privada.

`JJCollectionSource` utiliza el índice de sitemaps, hasta dos mapas de productos por ronda y hasta doce fichas por defecto. Las fichas pueden producir más elementos que páginas porque cada idioma o variante conserva su propio identificador. El presupuesto total de consulta es de 90 segundos y cada petición tiene un límite adicional de 20 segundos, incluso si el transporte general permite más. Una ficha lenta deja continuar a las siguientes mientras quede presupuesto total. No se descargan imágenes; solo se conserva la URL publicada del origen permitido.

## Qué se notifica y qué se conserva

Cada elemento es `kind=product`, con ID `variant:<ID de Shopify>` y enlace directo a esa variante. Los juegos se determinan a partir del título, tipo, marca y etiquetas del propio producto, nunca del menú global. Los accesorios genéricos de cartas pueden carecer de etiqueta de juego. Se excluyen tarjetas regalo, torneos y merchandising identificado como tal; una colección de cartas que incluya una figura sigue siendo un producto de cartas.

El precio procede de la oferta **de esa variante**, en EUR, y debe coincidir con el precio en céntimos del objeto de producto. No se usa el precio mínimo de la ficha, el precio tachado, una suma de distintas variantes ni el coste de transporte. Se normaliza a dos decimales para que `29.9` y `29.90` no generen cambios falsos.

El estado exige que el `availability` de la oferta y el booleano de disponibilidad de esa misma variante concuerden:

- `InStock` sin preventa explícita: `AVAILABLE`.
- Variante agotada: `UNAVAILABLE`, aunque otra variante esté disponible.
- Etiqueta del producto `Preventa`/`sd_preorder` o oferta `PreOrder` y pedidos admitidos: `UPCOMING`. Una preventa no acredita existencias para entrega inmediata.
- `BackOrder` sin preventa explícita: `UNKNOWN`, con indicación de pedido pendiente de reposición y fecha sin confirmar.
- Oferta incompleta, contradictoria, identidad distinta o un estado no reconocido: error de extracción; se conserva el estado anterior.

Por ejemplo, la ficha de [Chaos Rising](https://www.jjcollection.es/products/pokemon-tcg-booster-box-chaos-rising-ingles-espanol) publicó inglés a 230,00 EUR y español a 158,00 EUR, con disponibilidad distinta y etiqueta de preventa. El adaptador no atribuye el precio español a la variante inglesa disponible. La ficha de [Pokémon Day](https://www.jjcollection.es/products/pokemon-tcg-caja-pokemon-day-2026-special-collection-ingles-espanol) permitió comprobar inglés disponible y español agotado. Estos son datos de esa consulta, no garantías de precio o stock futuros.

## Rotación, arranque y límites

El mapa descubre productos nuevos y las fichas se revisan por ventanas. Se reserva e intercala una cuota rotatoria antes de los nuevos descubrimientos para volver a comprobar productos agotados, incluidos los que salgan del sitemap. El cursor se persiste incluso al fallar una ficha, de modo que una URL defectuosa no bloquee indefinidamente el resto.

La referencia inicial guarda las URLs de producto de los sitemaps iniciales. Cuando una ficha inicial se lee en una ronda posterior, su inventario de variantes se entrega al núcleo con una marca independiente, conservando el arranque silencioso también después de reiniciar. Un producto nuevo posterior y una variante añadida tras la primera lectura de su ficha sí pueden generar una novedad. Un fallo de red, HTTP 404 o ausencia en un sitemap nunca se transforma en agotado ni retirada.

Las consultas tienen límites: no se visita todo el catálogo cada cinco minutos ni se promete avisar en tiempo real. Un precio o stock solo describe la variante y el momento observados. Se conserva `country=ES`, `region=EU`, idioma de la fuente `es` y procedencia `retailer`; no se deduce que las cartas sean españolas ni que se envíe a cualquier destino. Las etiquetas de preventa pueden quedarse obsoletas en la tienda: se conserva su señal explícita y no se convierte una fecha pasada en disponibilidad inmediata.

## Verificación

- **33 pruebas** locales aprobadas: variantes e idiomas separados, preventa, pedido pendiente de reposición, precios y stock contradictorios, protección frente a enlaces e imágenes ajenos, bloqueo/estructura rota, inventarios diferidos silenciosos tras reiniciar, nuevo producto y nueva variante, reposición de un producto fuera del sitemap, errores parciales, cursor persistido y límites.
- Pasada real mediante `SourceHTTP`, TLS activo, SQLite en memoria y límites predeterminados: **12 variantes aceptadas**, de doce fichas, **sin errores parciales** y **0 notificaciones pendientes** durante la referencia inicial. Se extrajeron productos de Pokémon, Magic y Lorcana. No se llamó al modelo ni se envió nada a Discord.

El constructor admite `max_items`, `max_sitemaps` y `max_duration_seconds`. Los valores iniciales los fija el registro del servicio. La red real desde Proxmox/Portainer y una entrega al webhook deben comprobarse en ese despliegue.
