# Fuentes oficiales de One Piece Card Game

Comprobación del **25 de octubre de 2026** mediante peticiones HTTPS de lectura, con TLS verificado, sin navegador completo, registro, credenciales ni mensajes. Se conservan capturas y metadatos de trabajo en `work/research/one-piece/`, excluido de Git. Los fixtures de prueba contienen fragmentos semánticos de esas respuestas, no copias completas de las páginas.

## Adaptadores implementados

| ID | Consulta real | Cobertura y límites |
| --- | --- | --- |
| `one_piece_products` | [Catálogo oficial en inglés](https://en.onepiece-cardgame.com/products/) y fichas enlazadas | Última página de productos, incluidos boosters, decks, colecciones, accesorios y publicaciones etiquetadas Premium Bandai. Revisa por ventanas las fichas conocidas para detectar cambios. No representa todo el archivo histórico de 18 páginas observado. |
| `one_piece_news` | [Noticias oficiales](https://en.onepiece-cardgame.com/news/), su API pública observada y [portada](https://en.onepiece-cardgame.com/) como alternativa HTML | Promociones y anuncios especiales; eventos con promociones o premios especiales. Omite los registros de productos que ya vigila el catálogo, cardlists, reglas, resultados y erratas. Un periodo de evento se conserva aparte de una fecha de venta. |

El editor identifica la edición de la web inglesa como **NA/EU/OC/LATAM/ME**. Los elementos llevan `tcg=one_piece`, `region=WESTERN`, `regions=[NA,EU,OC,LATAM,ME]` y `language=en`. Ese idioma describe la página de origen; no debe interpretarse automáticamente como idioma de todas las cartas que menciona. El código no convierte una fecha o un MSRP de esta web en stock de una tienda española ni en precio de compra en euros.

Ambos adaptadores producen estados `ANNOUNCED`: un anuncio de catálogo no demuestra que se pueda comprar el producto en este instante. El MSRP se conserva como `msrp_text`, separado de `price`/`currency`, por lo que no se presenta como un precio de compra verificado. Cuando aparece un código de producto, se conserva literalmente en `product_code`. La etiqueta Premium Bandai se registra como canal de distribución; no acredita inventario del sitio de comercio.

## Métodos comprobados

El catálogo devuelve HTML del servidor con `main .linkListColInner`, tarjetas `li.linkListColBox`, enlaces `a.linkListColItem` y título `.linkListColTitle`. Las fichas examinadas usan `main article.articleCol`, `.detailColStatus` con pares `dt`/`dd`, encabezado y galería. Se comprobaron dos estructuras: ficha de booster con título dentro de detalles y ficha especial con `.articleColHead h2`.

Las noticias nuevas cargan su lista con Vue, pero **no necesitan ejecutar JavaScript para extraer los datos**. El archivo público enlazado por la página, `/renewal/js/news_async.js`, declara la llamada:

```text
GET /common/templates/api/article_list.php
start=0
limit=10
data={"category":"INFORMATION","subcategory":[""],"is_history":true}
```

Se comprobó que devuelve HTTP 200 y JSON con `statusCode`, `data.apiStatus`, `data.total_count` y `data.article_list`. La primera respuesta contenía 10 registros de un total de 137. Se solicitan como máximo dos páginas de diez registros por comprobación; no se recorren todos los resultados. Los destinos se obtienen de `onepiece.related_item.en` según el tipo real `article`/`link`, y solo se consultan rutas individuales del origen oficial permitido. Los tiempos internos, contadores y parámetros variables de miniaturas no generan cambios de contenido.

Si la API falla temporalmente, se intenta el bloque de noticias HTML de la portada, con la misma identidad de URL para un anuncio. El inventario de la API tiene una referencia inicial independiente para evitar alertas históricas cuando vuelva a estar accesible. Una página de bloqueo, estructura rota o fallo completo de detalles no sustituye el último estado correcto.

El enlace **Archive** de la web apunta a [Topics](https://en.onepiece-cardgame.com/topics/). Aunque respondió HTTP 200 con 999 registros, en esta captura sus primeras entradas eran de marzo de 2026 mientras la portada y la API ya contenían novedades de octubre. Por ese motivo no se utiliza como única lista reciente ni se importa su archivo entero al arrancar.

## Ejemplos primarios y separación de fechas

- [The Dominance of God OP-18](https://en.onepiece-cardgame.com/products/op18.html): la ficha distingue `Release Date` del texto de legalidad de torneos. La fecha literal de lanzamiento y el código se conservan; no se deduce disponibilidad por haber llegado ese día.
- [Chinese 3rd Anniversary Set](https://en.onepiece-cardgame.com/products/3rd_anniversary_set_cn.html): ejemplo de colección marcada Premium Bandai en el catálogo. La ficha examinada ofrece contenido y MSRP, pero no una fecha exacta; queda desconocida.
- [4th Anniversary Event / OP-18 Release Event](https://en.onepiece-cardgame.com/events/store-tournament-op18.html): describe promociones y premios de aniversario. Su periodo se guarda literalmente como `event_period_text`, con `kind=event` y `channel=event`; no es una apertura de venta de todos los productos mencionados.
- [Bandai Card Games Fest Dallas](https://en.onepiece-cardgame.com/events/2026/bcgfest26-27/dallas/): conserva una plantilla de landing distinta, con título publicado como texto alternativo de imagen. También se comprobó y se admite sin OCR ni navegador. La dirección de la sección oficial de información indica USA, por lo que este elemento concreto lleva `region=US`, no una supuesta ubicación europea por proceder de la web occidental.

## Cobertura pendiente

La [web japonesa](https://www.onepiece-cardgame.com/) también respondió HTTP 200 y ofrece su propia edición, calendario e idioma. Esta investigación no activa un monitor japonés ni mezcla su calendario con el occidental. Las versiones asiáticas y francesa aparecen enlazadas por el editor, pero no se han implementado como duplicados del adaptador inglés.

Tampoco se implementa una API de stock de Premium Bandai, reservas automáticas, compras ni acceso a Bandai TCG+ con credenciales. Los anuncios oficiales de productos Premium Bandai se cubren desde el catálogo verificado; la compra y la disponibilidad regional del comercio son otra integración. Los calendarios de tiendas españolas se gestionan por adaptadores independientes, sin asumir que todo anuncio internacional tiene un evento local.

## Verificación

Las **26 pruebas** de `tests/test_one_piece_sources.py` reproducen HTML y JSON guardados, comprueban identidad, región, separación de MSRP, exclusión de ruido, imágenes del origen permitido, fallos parciales y alternativa de API. No requieren red ni envían Discord. Una pasada real acotada recuperó **4 productos y 3 anuncios de eventos promocionales**, sin errores de detalle, usando TLS verificado y sin modelo, Discord ni base de producción. Estos recuentos describen esa consulta, no la totalidad del catálogo.

Los constructores aceptan `max_items` y `max_duration_seconds`; el de noticias añade `max_pages`. La identidad se basa en la URL oficial individual, no en el título ni en un horario calculado.
