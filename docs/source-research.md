# Investigación de fuentes oficiales

Este documento conserva la comprobación de las integraciones originales. La cobertura actual de la versión 1.1 se describe en [fuentes implementadas](announcement-sources.md).

Comprobado el **21 de octubre de 2026** desde el entorno de desarrollo, con peticiones HTTPS de solo lectura y verificación TLS. La herramienta web devolvía 403 para Secret Lair; una petición HTTP directa autorizada devolvió 200. Esto no demuestra conectividad desde Proxmox.

## Secret Lair EU

Página inicial: https://secretlair.wizards.com/eu/ — 200; HTML de 517709 bytes; cabeceras ETag y Last-Modified. No había JSON-LD de producto ni feed RSS anunciado. robots.txt no publica sitemap y prohíbe rutas de cuenta/pago/data; el adaptador no las visita.

El catálogo usa Angular, pero no necesita navegador: el HTML declara `sf_storesearch_config` y el código de `StoreSearchFactory` usa un endpoint público, **https://storesearch.eu.scalefast.com/StoreSearch**. La configuración publica userID, locale, currency, searchEnv; los controles `ExtraSectionController` publican feeds en sus atributos `ng-init`. El adaptador extrae esos valores, no ejecuta JavaScript y restringe el endpoint a esa URL exacta.

Se verificó una consulta GET con userID=10751401, locale=en_REU, currency=EUR, env=prod, sort=featured, offset=0, count=20, crit=ALL, filters=feedID:73824: devolvió 200 y `filters[0].products` con seis productos. Es una interfaz pública observada, sin garantía de estabilidad contractual; su estructura se valida. Se limita el número de feeds, páginas y productos por ciclo.

El catálogo se usa para descubrir identificadores. No se interpreta la presencia de botones Angular como prueba de stock. La página real https://secretlair.wizards.com/eu/product/1253140 devolvió 200 y JSON-LD `Product`, `sku` y `offers` con `price`, `priceCurrency`, `availability` y `url`. Ese es el dato verificable de precio/disponibilidad. Una respuesta incompleta genera error de extracción, nunca una desaparición. Solo se aceptan valores de disponibilidad de schema.org conocidos; el resto es UNKNOWN. PreOrder se normaliza a UPCOMING, que indica preventa y no necesariamente imposibilidad de compra.

Los anuncios próximos se leen de la lista JSON literal `upcoming_event_slides`, publicada en el HTML, con `visible=true` y destino home activado. `event_name`, `subtitle` y `description` permiten distinguir anuncios de productos de catálogo. No se envían formularios ni se sigue ninguna URL propuesta por IA.

Los productos conservados en SQLite se pueden volver a consultar aunque ya no figuren en la portada. El cupo de productos rota; la ausencia en un listado no cambia su estado. Los listados podrían no exponer el catálogo histórico completo ni productos protegidos/autenticados.

La comprobación ampliada detectó páginas reales de catálogo con JSON-LD `Thing` en lugar de `Product`, por ejemplo https://secretlair.wizards.com/eu/product/1254818/festival-in-a-box-atlanta-2026. Para no omitir esos productos o bundles, el adaptador confirma la identidad combinando una URL oficial de producto con ID numérico, `Thing.name` y un `h1` coincidente. Devuelve un elemento de producto con identidad verificada, disponibilidad UNKNOWN y sin precio. La presencia de Thing o de botones no demuestra stock. Si tampoco existe esa combinación coherente, se registra error de extracción y se conserva el estado previo.

## Noticias Magic

https://magic.wizards.com/en/news devolvió 200, 716299 bytes, ETag y HTML renderizado en servidor. Los enlaces observados tienen forma `/en/news/<categoría>/<slug>` y contienen títulos y párrafos. No se encontró RSS anunciado. https://magic.wizards.com/robots.txt anuncia https://magic.wizards.com/en/sitemap.xml; también se verificó ese sitemap (200, 662050 bytes), pero no es necesario descargar un índice histórico grande en cada ciclo.

Se prioriza el HTML de noticias recientes. Los detalles usan `article`, `h1`, párrafos y `time`, sin clases CSS generadas. El artículo https://magic.wizards.com/en/news/announcements/reality-fracture-secret-lair-bundle-delayed devolvió 200 y confirmó esas estructuras. La noticia sigue siendo una publicación; una mención de disponibilidad en ella no sustituye la disponibilidad de un producto EU.

La portada es una ventana de noticias recientes, no un archivo histórico exhaustivo: un artículo publicado y retirado entre dos comprobaciones puede pasar inadvertido. Si se necesita cobertura histórica, añadir un adaptador de sitemap incremental separado, con límites y filtro temporal.

## Transporte y límites

HTTP reutilizable con timeout y cota de tiempo total, límite de respuesta descomprimida, reintentos limitados, pausa mínima por host, ETag/If-Modified-Since persistidos. Un 304 reutiliza el cuerpo previo y vuelve a validarlo; la caché HTTP no constituye un estado aceptado. Las redirecciones se siguen manualmente solo dentro del mismo origen y con un máximo de tres saltos: se verificó que `/eu/product/1253140` responde 302 hacia la URL oficial con slug. Un cambio de dominio requiere actualizar el adaptador después de verificarlo. Los Retry-After largos dejan una pausa persistida por host; no se reintenta anticipadamente.

No se ha medido consumo del contenedor ni se ha verificado acceso desde el host Portainer. DNS, TLS, bloqueo geográfico o protección anti-bot pueden producir resultados distintos allí. No se añade Chromium, Playwright ni Selenium.

## Comprobación funcional realizada

Se ejecutaron los adaptadores implementados contra las fuentes reales, limitando la prueba a cuatro productos y tres artículos, sin webhook ni llamadas al modelo. Secret Lair descubrió **67 identificadores de producto**; devolvió tres anuncios próximos y cuatro productos con datos JSON-LD válidos (dos AVAILABLE y dos UPCOMING), sin errores de extracción en esa muestra. Magic devolvió tres artículos válidos sin errores. Esto verifica la muestra y la extracción actual; no es una prueba exhaustiva de los 67 productos ni de disponibilidad futura.

La consulta de catálogo está acotada a ocho feeds y tres páginas de veinte resultados por feed en cada ciclo. Un catálogo mayor exige ajustar conscientemente esos límites o añadir paginación incremental. La ventana de detalles por ciclo rota y conserva su posición en SQLite; reserva la mitad del cupo a productos nuevos cuando el cupo es al menos dos. Así un histórico amplio no retrasa todos los productos nuevos hasta completar una vuelta. El primer arranque puede registrar todos los IDs descubiertos como línea base, incluso si sus detalles quedan para ciclos posteriores, evitando alertas históricas tardías.

La caché HTTP usa una cota de 128 respuestas y 32 MB de cuerpos en SQLite, además de la retención temporal. Los cuerpos expulsados se vuelven a descargar normalmente; esto no afecta los estados, eventos ni las huellas de deduplicación. El archivo SQLite puede conservar espacio libre interno reutilizable tras expulsar filas.

Cada adaptador tiene además un presupuesto global de tiempo. Si se agota durante los detalles, devuelve los elementos ya verificados y errores parciales; los pendientes conservan sus estados previos. La ronda solo avanza por detalles realmente intentados. Los nuevos y los históricos se intercalan para que los fallos repetidos de los nuevos no consuman siempre todo el presupuesto antes de revisar antiguos.
