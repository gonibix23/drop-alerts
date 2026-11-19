# Seguimiento de Zial TCG

La versión 1.4.2 incorpora la fuente `zial_tcg`, activada por defecto con rondas cada **300 segundos**. Sigue productos y accesorios TCG, novedades, reservas, cambios de precio y disponibilidad verificable. No necesita una inferencia del modelo para detectar esos hechos ni añade dependencias de ejecución, puertos o servicios.

El adaptador consulta los catálogos públicos de [juegos de cartas](https://www.zialtcg.com/categoria-producto/juegos-cartas/), [preventa](https://www.zialtcg.com/categoria-producto/preventa/) y [accesorios](https://www.zialtcg.com/categoria-producto/accesorios/). Usa HTML de WooCommerce y contrasta la ficha principal con sus metadatos `Product`/`Offer`. El método comprobado y sus límites están en [la investigación de Zial TCG](research-zial.md).

## El producto enlazado y las reservas

El [Commander Deck Display Warhammer 40K de Magic](https://www.zialtcg.com/producto/commander-deck-display-warhammer-40k-magic-the-gathering/) se consulta expresamente en cada ronda, aunque deje de aparecer en los listados. Comparte persistencia, reglas y deduplicación con el resto del catálogo; añadirlo no provoca un aviso repetido en cada consulta.

La ficha examinada publica una cantidad disponible, pero su categoría y descripción indican **preventa**. El estado es `UPCOMING`: ese cupo permite reservar y no demuestra stock para entrega inmediata. El monitor no convierte una reserva en `AVAILABLE` por el botón de compra o por una cantidad positiva. Un importe de señal o reserva tampoco se presenta como coste completo del producto.

Los estados agotado, disponible y bajo pedido se apoyan en los indicadores de la ficha. La ausencia en una página, un error HTTP o una extracción incompleta conservan la última observación correcta. Las fichas con variantes sin ofertas individuales verificables no se tratan como si todos sus idiomas o versiones compartieran precio y stock.

## Configuración y selección de juegos

La configuración incluida en la imagen contiene:

```toml
[sources.zial_tcg]
enabled = true
interval_seconds = 300

[[rules]]
id = "zial-drops"
sources = ["zial_tcg"]
kinds = ["product", "collection"]
event_types = ["product.new", "collection.new", "availability.changed", "price.changed", "release_date.changed", "change.uncertain"]
require_analysis = false
```

Los productos con juego identificado respetan `ENABLED_TCGS` o `[games].enabled`. Se mantienen Magic, One Piece y Pokémon como selección predeterminada. Para recibir también productos Gundam o Jurassic Park TCG de la tienda, añade `gundam` o `jurassic_park`, por ejemplo:

```dotenv
ENABLED_TCGS=magic,one_piece,pokemon,gundam,jurassic_park
```

Esto amplía las alertas de productos de tienda, sin crear monitores de anuncios oficiales de esos juegos. Las cartas y accesorios se clasifican a partir de sus propios datos, sin tomar los juegos del menú general. Los productos identificados de Gundam o Jurassic Park TCG mantienen su etiqueta de juego y sólo pueden avisar si está habilitado. El alcance excluye figuras sueltas y entradas de eventos. Los accesorios generales para cartas pueden no tener juego asignado.

La regla inicial omite cambios genéricos de texto, como una cantidad que disminuye mientras el producto sigue disponible al mismo precio. Esas observaciones se conservan en SQLite. Si necesitas avisos de ese tipo, añade `content.changed` a la regla correspondiente.

## Límites, actualización y prueba

Cada ronda revisa una ventana de hasta doce fichas, incluido el producto enlazado. El catálogo se recorre por páginas y los productos conocidos permanecen en revisión aunque salgan de portada. Los cursores se conservan tras reinicios. El intervalo de cinco minutos no garantiza revisar cada ficha de la tienda en ese plazo ni detectar una venta que se agote entre consultas.

En Portainer, actualiza el stack desde `main`, con `docker-compose.yml`, reconstruyendo la imagen. Conserva el volumen `drop_alerts_data` y `BOOTSTRAP_MODE=silent`; la primera referencia se registra sin enviar el catálogo histórico. Se mantiene el esquema SQLite 2.

Si montas un TOML propio, incorpora **la fuente y su regla** del ejemplo conservando los demás bloques y sin duplicar identificadores. Actualizar la imagen no modifica ese archivo. No necesitas variables adicionales para activar Zial con la configuración incluida.

Desde la consola del contenedor:

```sh
python -m drop_alerts events --source zial_tcg --kind product --limit 10
python -m drop_alerts events --source zial_tcg --tcg magic --limit 10
python -m drop_alerts preview --source zial_tcg --kind product
```

Añade `--send` al último comando para enviar expresamente una vista previa al webhook configurado. Conserva la cola y la deduplicación y lleva la marca de prueba manual. También permite consultar eventos guardados durante el arranque silencioso; espera a la primera comprobación correcta si todavía no hay resultados. Los filtros de juego y reglas actuales siguen aplicándose.

Las comprobaciones realizadas y lo pendiente desde el entorno real de Portainer se describen en [verificación](verification.md). Consulta también [las tiendas online](retail-stores.md) y [cómo inspeccionar alertas](inspecting-alerts.md).
