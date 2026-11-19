# Tiendas online: productos de cartas y coleccionables

Desde la versión 1.4, `tabletop_gamers` y `jjcollection` se activan por defecto y se consultan cada **300 segundos**. Generan avisos por productos nuevos, cambios explícitos de disponibilidad, reposiciones, precios y cambios de fecha detectables. La detección, SQLite, las reglas y la cola de Discord siguen siendo deterministas; no hace falta una inferencia para confirmar un stock o un precio.

La versión 1.4.1 añade también `animefan`, con el mismo intervalo y seguimiento de cartas por defecto. Sus figuras y coleccionables tienen una opción de activación independiente; consulta [la guía de Animefan](animefan.md).

## Qué se consulta

| Fuente | Método ligero | Cobertura |
| --- | --- | --- |
| [Tabletop Gamers](https://tabletopgamers.es/) | Catálogos HTML de WooCommerce, paginación pública y fichas con Product JSON-LD contrastado con información visible | Productos y accesorios de cartas, novedades y reservas. Revisión rotatoria de fichas conocidas. |
| [JJ Collection](https://www.jjcollection.es/) | Sitemaps públicos y fichas HTML de Shopify, con ofertas JSON-LD y metadatos de cada variante | Productos, cartas y accesorios TCG; cada variante mantiene precio y disponibilidad propios. |
| [Animefan](https://animefan.es/) | Categorías públicas y fichas de WooCommerce contrastadas con sus metadatos | Cartas y productos TCG; figuras y coleccionables solo si se activa su opción. |

Los métodos y respuestas reales comprobados el **19 de noviembre de 2026** están en los estudios de [Tabletop](research-tabletop.md) y [JJ Collection](research-jjcollection.md). No se usan cuentas, APIs privadas, carrito, navegadores ni acciones de compra. Las rutas restringidas en los robots examinados se evitan.

Cada ronda visita un número acotado de páginas y detalles. Parte del presupuesto busca identidades nuevas y otra parte rota los productos ya conocidos, incluidos los agotados, para detectar reposiciones aunque salgan de portada. Los cursores persisten tras reinicios. **Cinco minutos es el intervalo entre rondas, no una garantía de revisar todas las fichas cada cinco minutos.** El tiempo de revisión completa depende del catálogo, sus cambios y los errores de red. No se promete cobertura completa de todo el archivo ni detectar una venta que se agote entre dos consultas.

## Qué significa la disponibilidad

- `AVAILABLE`: la ficha aporta indicadores comprobables de compra disponible para ese producto o variante.
- `UNAVAILABLE`: la fuente indica expresamente agotado o sin existencias.
- `UPCOMING`: reserva o preventa expresamente identificada. Poder reservar no confirma stock para entrega inmediata.
- Información incompleta o contradictoria: se conserva el último estado correcto cuando no se puede extraer la ficha con seguridad. Un error, una ficha eliminada o salir de un listado no convierte automáticamente el producto en agotado.

El precio es el de la oferta actual comprobada, en EUR; los importes tachados y los rangos no se toman como precio de compra de una variante. No incluye un cálculo personalizado de envío, descuentos por cliente o condiciones del carrito. Los enlaces e imágenes proceden de orígenes permitidos de cada tienda. La fecha publicada de salida conserva su incertidumbre; no se infiere disponibilidad por haber llegado ese día.

La regla inicial omite los cambios genéricos de texto: pasar de «quedan 3 disponibles» a «quedan 2 disponibles» no manda otro mensaje si el estado y el precio siguen iguales. Esos cambios se guardan en SQLite; añade `content.changed` a `event_types` si quieres recibirlos también.

En JJ Collection, una variante española agotada y otra inglesa disponible son elementos distintos. En Tabletop, las fichas con variantes que no puedan comprobarse de forma individual se rechazan conservando el estado; no se presenta el stock del padre como si fuese el de todas las variantes. Dos tiendas que vendan el mismo producto mantienen estados independientes.

## Juegos y accesorios

Se mantienen los juegos seleccionados por `ENABLED_TCGS` o `[games].enabled`. Con el valor inicial se avisa de Magic, One Piece y Pokémon. Para recibir también otros juegos identificados explícitamente en las fichas, amplía la lista, por ejemplo:

```dotenv
ENABLED_TCGS=magic,one_piece,pokemon,riftbound,lorcana,dragon_ball,digimon,yugioh,star_wars_unlimited,cyberpunk
```

Las etiquetas adicionales permiten filtrar productos de las tiendas; no crean adaptadores de anuncios oficiales de esos juegos. La clasificación usa título y categorías del producto, nunca los menús generales de la web. Los accesorios generales para cartas pueden no tener un juego asignado y se permiten mediante la regla de tiendas. Las tarjetas regalo y entradas de torneo quedan fuera del seguimiento comercial. Tabletop y JJ Collection excluyen figuras sueltas; Animefan permite activarlas con `include_collectibles=true`, sin etiquetarlas como TCG ni vincularlas a `ENABLED_TCGS`.

Para limitar aún más, adapta `retail-card-drops` con `tcgs`, `keywords`, `states` o `event_types`. Una regla adicional no restringe otra regla más amplia que siga activada. Por ejemplo, para recibir solo novedades y entradas en stock, modifica la regla existente:

```toml
[[rules]]
id = "retail-card-drops"
sources = ["tabletop_gamers", "jjcollection"]
kinds = ["product", "collection"]
event_types = ["product.new", "availability.changed"]
states = ["AVAILABLE", "UPCOMING"]
require_analysis = false
```

## Actualizar el stack existente

En Portainer, actualiza el stack desde `main`, con `docker-compose.yml`, y reconstruye la imagen. Conserva el volumen y `BOOTSTRAP_MODE=silent`: la primera referencia de estas fuentes no envía el catálogo histórico, incluidas las fichas que se procesan en rondas posteriores. Los productos nuevos y los cambios posteriores sí pueden producir avisos.

Si tienes un TOML propio montado, actualizar la imagen **no añade fuentes ni reglas a ese archivo**. Incorpora los bloques de [config.example.toml](../config.example.toml):

```toml
[sources.tabletop_gamers]
enabled = true
interval_seconds = 300

[sources.jjcollection]
enabled = true
interval_seconds = 300

[[rules]]
id = "retail-card-drops"
sources = ["tabletop_gamers", "jjcollection"]
kinds = ["product", "collection"]
event_types = ["product.new", "collection.new", "availability.changed", "price.changed", "release_date.changed", "change.uncertain"]
require_analysis = false
```

Intégralos en tu archivo existente sin duplicar identificadores. Comprueba los logs y `python -m drop_alerts status` en el contenedor. No hacen falta variables nuevas para activar estas fuentes si utilizas la configuración incluida en la imagen.

## Consultar y probar un mensaje

Desde la consola del contenedor en Portainer:

```sh
python -m drop_alerts events --source tabletop_gamers --kind product --limit 10
python -m drop_alerts events --source jjcollection --tcg pokemon --limit 10
python -m drop_alerts preview --source tabletop_gamers --kind product
python -m drop_alerts preview --source jjcollection --kind product
python -m drop_alerts preview --source animefan --kind product
```

`preview` imprime el mensaje. Añade `--send` para enviarlo expresamente al webhook configurado, con la marca de vista previa manual. No modifica la deduplicación ni la cola. La consulta incluye los eventos conservados del arranque silencioso y respeta los juegos, fuentes y reglas actuales. Espera a la primera comprobación correcta si todavía no hay resultados. Véase [la guía de inspección](inspecting-alerts.md).
