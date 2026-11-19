# Seguimiento de Animefan

La versión 1.4.1 añade la fuente `animefan`, activada por defecto con rondas cada **300 segundos**. La tienda vende cartas, figuras y merchandising; el seguimiento inicial se limita a cartas y productos TCG. Los productos mixtos de cartas que incluyan una figura siguen siendo productos de cartas.

La investigación encontró categorías públicas de [cartas coleccionables](https://animefan.es/categoria-producto/grupo-producto/cartas-coleccionables/) y [Pokémon Juego de Cartas](https://animefan.es/categoria-producto/fabricante/pokemon-juego-de-cartas/). Las fichas se consultan por ventanas, con identidad estable, revisión de productos conocidos e inventarios iniciales silenciosos. No se necesita navegador, cuenta o acceso al carrito. El método y sus límites se detallan en [la investigación de Animefan](research-animefan.md).

## Activar figuras y coleccionables

En el TOML de configuración:

```toml
[sources.animefan]
enabled = true
interval_seconds = 300
include_collectibles = false

[[rules]]
id = "animefan-drops"
sources = ["animefan"]
kinds = ["product", "collection"]
event_types = ["product.new", "collection.new", "availability.changed", "price.changed", "release_date.changed", "change.uncertain"]
require_analysis = false
```

Cambia únicamente `include_collectibles` a `true` para ampliar esta fuente a figuras y coleccionables. Es un booleano TOML, sin comillas. La opción solo pertenece a Animefan; se rechaza en otras fuentes. Si montas un archivo propio, integra estos bloques conservando tus demás fuentes y reglas y sin duplicar identificadores. La imagen ya contiene los bloques con el valor inicial `false`.

Las cartas con juego identificado respetan `ENABLED_TCGS`. Las figuras llevan `domain=collectibles`, una categoría de producto y su franquicia cuando se puede identificar; no se etiquetan como juegos TCG. Una figura de One Piece no se convierte en cartas One Piece. Los coleccionables activados no dependen de `ENABLED_TCGS`: se controlan mediante esta opción, la fuente y las reglas.

Al volver a `false`, los coleccionables pendientes que dejan de estar permitidos se omiten antes del envío y tampoco se seleccionan para una vista previa. Rehabilitar la opción no resucita mensajes omitidos. Los datos y la deduplicación se conservan.

## Disponibilidad y precios

Los avisos distinguen las existencias explícitas, los productos agotados y las reservas. Poder añadir una reserva al carrito no demuestra stock para entrega inmediata. Una compra «bajo pedido» sin fecha o stock confirmados se trata como incierta. Un fallo de red, un cambio de estructura o una ficha ausente conservan la última observación correcta.

El precio mostrado exige una oferta comprobable en EUR. Un precio tachado, un importe de señal o depósito y un precio total son conceptos diferentes: no se presenta una señal como coste completo del producto. Los gastos de envío y las condiciones personales de compra no se calculan. El enlace permite consultar las condiciones vigentes de la tienda.

Las fechas sin día concreto o con información insuficiente no se completan inventando un día ni una hora. Una fecha de catálogo no demuestra que el producto ya tenga existencias.

## Actualizar y probar

Actualiza el stack desde `main` en Portainer, con `docker-compose.yml`, reconstruyendo la imagen. Conserva el volumen y `BOOTSTRAP_MODE=silent`. Si montas un TOML propio, añade la fuente y su regla: actualizar la imagen no modifica ese archivo.

Desde la consola del contenedor:

```sh
python -m drop_alerts events --source animefan --limit 10
python -m drop_alerts events --source animefan --tcg pokemon --limit 10
python -m drop_alerts preview --source animefan
```

Añade `--send` al último comando para enviar expresamente una vista previa del último evento guardado que cumpla la configuración actual. No modifica la cola ni la deduplicación. También se pueden probar eventos del arranque silencioso; espera a una comprobación correcta si todavía no hay resultados.

Cada ronda revisa un subconjunto acotado. El intervalo de cinco minutos no equivale a comprobar todas las fichas de la tienda en ese tiempo ni garantiza detectar una venta que se agote entre consultas. Consulta [las tiendas online](retail-stores.md) y [las comprobaciones realizadas](verification.md).
