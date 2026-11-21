# Seguimiento de El Cartón Peleón

La versión 1.4.3 incorpora la fuente `carton_peleon`, activada por defecto con rondas cada **300 segundos**. Sigue productos y accesorios TCG, novedades, reservas, cambios verificables de precio y disponibilidad. El alcance excluye figuras sueltas y entradas de eventos.

La tienda entrega HTML generado por Odoo para los catálogos de [juegos de cartas](https://www.elcartonpeleon.com/shop/category/juegos-de-cartas-204) y [accesorios](https://www.elcartonpeleon.com/shop/category/accesorios-160), y para las fichas enlazadas. El adaptador utiliza también la consulta pública de lectura de la propia web cuando debe corroborar un stock incierto o un posible bloqueo de venta por precio no verificable. No añade un navegador ni accede a una cuenta o al carrito.

El [pack de cuatro mazos Commander Warhammer 40K en inglés](https://www.elcartonpeleon.com/shop/commander-pack-4-mazos-ingles-magic-the-gathering-warhammer-40k-deck-set-19822) se consulta expresamente en cada ronda, aunque deje de aparecer en los listados. No se combina su precio o estado con los del display de otra tienda. Repetir una observación idéntica no crea una nueva entrega.

La ficha examinada indica que estará **próximamente disponible para reservar**, por lo que se clasifica como `UPCOMING`. Un valor cero de precio o `InStock` en metadatos, sin corroboración visible, no demuestra que sea gratuito o que se pueda comprar. El precio oculto y las señales contradictorias de fecha se mantienen sin confirmar; el monitor no completa esos datos mediante una inferencia.

La procedencia de los datos, el método de extracción y las condiciones de acceso se documentan en [la investigación de la fuente](research-carton-peleon.md). Un enlace de producto por sí solo no demuestra precio, existencias ni fecha de lanzamiento. La detección utiliza hechos de la respuesta consultada y no necesita una inferencia del modelo para compararlos.

## Configuración

La configuración incluida en la imagen contiene:

```toml
[sources.carton_peleon]
enabled = true
interval_seconds = 300

[[rules]]
id = "carton-peleon-drops"
sources = ["carton_peleon"]
kinds = ["product", "collection"]
event_types = ["product.new", "collection.new", "availability.changed", "price.changed", "release_date.changed", "change.uncertain"]
require_analysis = false
```

Los productos con juego identificado respetan `ENABLED_TCGS` o `[games].enabled`. Magic, One Piece y Pokémon mantienen su selección inicial. Los accesorios generales de cartas pueden carecer de un juego concreto. El idioma del producto y su oferta pertenecen a esa ficha; no se deducen de otras tiendas ni del idioma general de la web.

Los productos identificados de Palworld, UniVersus o Weiß Schwarz usan `palworld`, `universus` y `weiss_schwarz`. Para recibirlos también, amplía tu selección, por ejemplo:

```dotenv
ENABLED_TCGS=magic,one_piece,pokemon,palworld,universus,weiss_schwarz
```

Estas etiquetas permiten filtrar productos de tienda; no crean monitores de anuncios oficiales de esos juegos. La procedencia ES/EU describe el contexto de la tienda y no acredita envío a todos los países europeos. Comprueba las condiciones del destino en la tienda.

La regla inicial omite cambios genéricos de texto cuando el estado y el precio siguen iguales. Esas observaciones se conservan en SQLite. Para recibirlos también, añade `content.changed` a la regla correspondiente.

## Disponibilidad, límites y persistencia

Los avisos distinguen las existencias explícitas, los agotados y las reservas cuando la fuente permite verificarlos. El bloque propio de próxima reserva produce `UPCOMING` y el de agotado, `UNAVAILABLE`. El botón de compra y un `InStock` genérico en metadatos no bastan para confirmar existencias.

Para las fichas que siguen en `UNKNOWN` tras leer el HTML, se puede consultar `/website_sale/get_combination_info` mediante JSON-RPC `POST`, la misma operación pública de lectura usada por el frontend de la tienda. También se consulta cuando el HTML parece indicar `AVAILABLE`, pero el precio no está verificado, para comprobar si existe un bloqueo de venta. El programa comprueba los identificadores de plantilla y variante y valida los datos antes de utilizarlos. Esta llamada no crea carritos, pedidos ni compras. Comparte los límites de frecuencia, tiempos de espera y reintentos del transporte HTTP; sus respuestas de stock no se guardan como caché reutilizable.

Si la respuesta activa `prevent_zero_price_sale`, el estado queda `UNKNOWN` incluso si devuelve una cantidad positiva: no se anuncia como comprable un producto bloqueado por falta de precio. El programa no inventa un precio para resolverlo. Los avisos explícitos de próxima reserva y agotado no se sustituyen mediante esta consulta.

El resultado puede confirmar disponibilidad online para esa variante en el momento consultado; las cantidades cambian y no se fijan como constantes. No demuestra existencias en una tienda física ni una cobertura de envío distinta de la publicada. Un resultado válido pero insuficiente conserva la incertidumbre. Si la consulta falla, esa observación se descarta y se conserva el estado anterior: el error de red no se convierte en un cambio a `UNKNOWN` o agotado. El producto enlazado con aviso explícito de próxima reserva permanece `UPCOMING` y no hace esta consulta.

La API no se usa para revelar ni sustituir precios: sólo se muestra el precio público visible y corroborado de la ficha. Un precio visible puede estar confirmado mientras las existencias siguen inciertas, y un precio oculto permanece sin confirmar aunque la API devuelva un importe. Las reposiciones requieren nueva evidencia verificable de disponibilidad.

Poder reservar o añadir al carrito no basta para confirmar entrega inmediata. Un precio tachado, un importe parcial de señal y un precio total no se consideran equivalentes. Un precio cero u oculto no se presenta como gratuito y las fechas sin evidencia suficiente se mantienen sin confirmar.

Un error de red, un documento incompleto o una ficha que no aparezca en un listado conservan la última observación correcta; no generan por sí solos un cambio a agotado. Las variantes deben tener evidencia individual para no mezclar precio o disponibilidad entre idiomas y versiones.

Cada ronda revisa una ventana de hasta doce fichas, incluido el producto enlazado. Los productos conocidos se siguen revisando y los cursores se conservan tras reinicios. El intervalo de cinco minutos no significa que todas las fichas de la tienda se comprueben en ese plazo ni garantiza detectar una venta que se agote entre consultas.

Se conserva el esquema SQLite 2 y su volumen. Con `BOOTSTRAP_MODE=silent`, la primera referencia se registra sin enviar el catálogo histórico, incluidas las fichas cuyo detalle se lea más tarde. Los productos nuevos y los cambios posteriores que cumplan las reglas sí pueden producir avisos.

## Actualizar y probar

En Portainer, actualiza el stack desde `main`, con `docker-compose.yml`, reconstruyendo la imagen. Conserva `drop_alerts_data` y `BOOTSTRAP_MODE=silent`. Si montas un TOML propio, integra **la fuente y su regla** del ejemplo conservando tus demás bloques y sin duplicar identificadores. Actualizar la imagen no modifica ese archivo. No se añaden dependencias de ejecución, puertos o servicios.

Desde la consola del contenedor:

```sh
python -m drop_alerts events --source carton_peleon --kind product --limit 10
python -m drop_alerts events --source carton_peleon --tcg magic --limit 10
python -m drop_alerts preview --source carton_peleon --kind product
```

El último comando muestra el mensaje sin enviarlo. Para enviarlo expresamente al webhook configurado:

```sh
python -m drop_alerts preview --source carton_peleon --kind product --send
```

La vista previa conserva la cola y la deduplicación y lleva la marca de prueba manual. Incluye eventos guardados durante el arranque silencioso que sigan cumpliendo la configuración actual. Espera a una comprobación correcta si todavía no hay resultados.

Las comprobaciones realizadas y cualquier limitación pendiente del acceso real se recogen en [verificación](verification.md) y [la investigación de la fuente](research-carton-peleon.md). Consulta también [las tiendas online](retail-stores.md) y [cómo inspeccionar alertas](inspecting-alerts.md).
