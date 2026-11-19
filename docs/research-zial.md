# Zial TCG: catálogo y producto vigilado

Comprobado el **19 de noviembre de 2026** con peticiones HTTPS, TLS verificado y el transporte real `SourceHTTP`. Las capturas completas y diagnósticos están en `work/research/zial/`, excluidos de Git. Los nueve fixtures de `tests/fixtures/zial_*` son extractos reducidos de las respuestas examinadas. No se hicieron compras, inferencias ni envíos a Discord.

## Métodos y rutas verificados

La [tienda Zial TCG](https://www.zialtcg.com/) utiliza WooCommerce y publica HTML del servidor. El [robots.txt](https://www.zialtcg.com/robots.txt) anuncia el [índice de sitemaps](https://www.zialtcg.com/sitemap_index.xml); se comprobó el índice y sus referencias de productos y categorías. El monitor no necesita descargar todo ese archivo histórico ni consultar una API privada.

La portada enlaza estos inventarios, que respondieron HTTP 200 y ofrecen paginación HTML:

- [Juegos de Cartas](https://www.zialtcg.com/categoria-producto/juegos-cartas/).
- [Preventa](https://www.zialtcg.com/categoria-producto/preventa/).
- [Accesorios](https://www.zialtcg.com/categoria-producto/accesorios/).

Los listados examinados mostraban 16 productos por página. `ul.products li.product.type-product` proporciona `post-<ID>`, categorías propias, título y enlace individual. La siguiente página se obtiene del enlace `.woocommerce-pagination a.next`; se validan origen y ruta antes de visitarla. No se construyen parámetros de búsqueda, filtros o acciones de carrito. Las exclusiones de robots de carrito, administración y registros internos se evitan.

Cada ficha principal usa `div.product.type-product#product-<ID>`, `.summary.entry-summary`, `h1.product_title`, `p.price`, `p.stock` y `#tab-description`. Su JSON-LD publica `Product`, URL canónica y una lista `offers` de una oferta `Offer`, con precio, moneda y disponibilidad. El adaptador contrasta los datos estructurados con el producto y el precio/stock visibles, sin tomar importes o existencias de recomendaciones.

El SKU es una referencia comercial independiente del ID de WooCommerce: puede ser un EAN, una referencia alfanumérica o coincidir con el ID. No se presupone que ambos números deban coincidir. Las fichas variables sin ofertas individuales verificables se rechazan conservando el estado; no se traslada el stock del padre a todas sus variantes.

## Producto enlazado y significado de la preventa

El [Commander Deck Display Warhammer 40K de Magic](https://www.zialtcg.com/producto/commander-deck-display-warhammer-40k-magic-the-gathering/) se mantiene como producto explícitamente vigilado, con identidad observada **`product:11533`**. Se revisa al principio de cada ronda, aunque salga de las primeras páginas del catálogo. `max_items=1` dedica esa única plaza a la ficha enlazada.

En la consulta, la ficha mostró **319,95 EUR** y unidades comprables, pero tanto su categoría como la descripción declaran **PREVENTA**. El resultado correcto es **`UPCOMING`**: las unidades reservables no acreditan existencias para entrega inmediata. No se utiliza el dato genérico `InStock` de WooCommerce para ocultar esa condición. El número publicado de unidades puede variar y no se interpreta como stock físico inmediato de una preventa.

La referencia inicial de esta ficha tiene un inventario independiente, `seed:commander-warhammer`. Si falla en la primera ronda pero el catálogo se inicializa correctamente, su primera lectura posterior sigue siendo silenciosa, incluso tras reiniciar. Un cambio real posterior de esa ficha sí puede generar un evento. Una ficha válida puede actualizarse aunque los catálogos fallen, registrando esos errores como parciales sin cerrar inventarios que no se pudieron consultar.

## Alcance, precio y estados

La fuente admite productos de cartas y accesorios de los catálogos comprobados. Exige categorías propias de juegos de cartas o accesorios; una categoría de franquicia como Pokémon o Gundam, por sí sola, no prueba que una figura sea TCG. Se excluyen entradas, torneos, rifas, ruletas, tarjetas regalo, naipes y figuras sin un producto de cartas explícito. Una colección de cartas que incluya una figura puede ser válida.

Las categorías del producto determinan el juego cuando es inequívoco. Se observaron Magic, Pokémon, One Piece, Riftbound, Gundam, Lorcana y Jurassic Park TCG. Las etiquetas `gundam` y `jurassic_park` respetan `ENABLED_TCGS`, igual que los juegos existentes; no se activan automáticamente por añadir la tienda. Los accesorios generales pueden no tener un juego único. Un título ambiguo con varios juegos no recibe arbitrariamente el primero.

El importe actual visible en EUR debe coincidir con `Offer.price` y su moneda. Los importes tachados y las especificaciones de precio anterior (`ListPrice`) no sustituyen la oferta actual: una ficha de Jurassic Park examinada tenía oferta **17,95 EUR** frente a **19,95 EUR** tachados. Si el sitio solo muestra «AGOTADO» en el campo de precio, se conserva el estado explícito pero se omite un precio que no se puede corroborar. Los depósitos y precios «desde» tampoco se presentan como precio total.

- `AVAILABLE`: existencias expresas corroboradas por la oferta y sin indicación de reserva.
- `UNAVAILABLE`: agotado o sin existencias explícitos, con oferta compatible.
- `UPCOMING`: preventa o reserva explícita, aunque el sistema permita comprar unidades.
- `UNKNOWN`: compra bajo pedido o reposición sin confirmación de existencias ni fecha.

Los textos negativos del campo de stock, como «No está disponible», no coinciden accidentalmente con la señal positiva. Los datos contradictorios o páginas incompletas son errores de extracción, conservando la observación anterior. Una ausencia, error HTTP o retirada de portada no se transforma en agotado. Las imágenes solo se aceptan del origen de la tienda y `/wp-content/uploads/`; no se descargan.

## Rotación y límites

El constructor es `ZialTCGSource(max_items=12, max_pages=2, max_duration_seconds=90)`. Las doce fichas incluyen la vigilada; las restantes plazas se reparten entre descubrimientos y revisión rotatoria de productos conocidos, incluso de los que salgan de los listados. Se alterna qué cuota va primero y el cursor persiste por trabajo realmente intentado. Las primeras páginas se consultan siempre, con una página adicional rotatoria por catálogo de forma predeterminada: hasta seis páginas de catálogo por ronda.

Cada petición tiene un límite adicional de 20 segundos y la ronda, 90 segundos. Una petición fallida no bloquea indefinidamente los demás productos. Cada página correctamente validada aporta su inventario inicial con IDs de fichas diferidas, conservando `BOOTSTRAP_MODE=silent` tras reinicios. Los inventarios incompletos no se cierran.

Cinco minutos entre rondas no garantizan revisar todas las fichas en cinco minutos ni detectar una venta que se agote entre consultas. Tampoco se confirma disponibilidad para cualquier destino, envío inmediato, gastos de envío o descuentos personalizados. El enlace conserva las condiciones actuales de la tienda.

## Verificación

- **41 pruebas locales** sin red: HTML/JSON-LD real, precios rebajados, oferta agotada sin precio visible, SKU independiente, reservas, textos negativos y compra bajo pedido, scope de TCG, aislamiento de recomendaciones, URLs, contradicciones, variantes, depósitos y moneda, límites, semilla con una plaza, recuperación inicial silenciosa tras reiniciar, nuevos productos y reposiciones fuera del catálogo.
- Consulta real con `SourceHTTP`, TLS activo y SQLite en memoria: **12 productos de seis páginas de catálogo**, **sin errores parciales**. Se observaron seis `UPCOMING`, cuatro `AVAILABLE` y dos `UNAVAILABLE`. El producto vigilado fue `UPCOMING` con **319,95 EUR**. El arranque silencioso dejó **0 notificaciones pendientes** y repetir los resultados generó **0 eventos nuevos**.
- No se llamó al modelo ni se envió nada a Discord. Los cambios posteriores y reposiciones completas se simulan en las pruebas; no se afirma haber observado un ciclo real completo durante el desarrollo. La conectividad y entrega en Proxmox/Portainer deben comprobarse en ese despliegue.
