# Alertas de varios TCG y torneos locales

Drop Alerts identifica cada elemento por su fuente e identidad estable y añade un perfil de juego, región, idioma de la fuente y canal. La cobertura implementada incluye `magic`, `one_piece` y `pokemon`. Los productos, anuncios y torneos comparten persistencia y reglas, pero conservan estados y fechas propios.

La configuración predeterminada activa **14 fuentes de las 26 registradas**: siete de Magic, dos de One Piece, dos de Pokémon y tres de torneos locales. Los adaptadores usan HTTP y contenido público estructurado o HTML, sin navegador ni otro contenedor. Esta guía describe la cobertura configurada; las comprobaciones y sus límites se documentan en [verificación](verification.md).

## Fuentes activadas por defecto

| Juego o ámbito | Identificador | Contenido y alcance | Intervalo inicial |
| --- | --- | --- | --- |
| Magic | `secret_lair_eu` | Tienda oficial Secret Lair EU: productos y disponibilidad verificable | 5 min |
| Magic | `chaos_vault_eu` | Chaos Vault EU: productos y anuncios especiales | 5 min |
| Magic | `magic_news` | Noticias de Magic, categoría de anuncios, sitemap y revisiones de artículos guardados; reglas de Secret Lair y lanzamientos especiales | 5 min |
| Magic | `secret_lair_bluesky` | Publicaciones de la cuenta oficial de Secret Lair | 5 min |
| Magic | `wpn_news` | Anuncios oficiales de Wizards Play Network relevantes para lanzamientos especiales | 15 min |
| Magic | `magiccon_news` | Noticias oficiales de MagicCon | 30 min |
| Magic | `weekly_mtg` | Publicaciones de WeeklyMTG | 15 min |
| One Piece | `one_piece_products` | [Catálogo oficial occidental](https://en.onepiece-cardgame.com/products/): expansiones, productos y fechas publicadas | 15 min |
| One Piece | `one_piece_news` | [Anuncios oficiales](https://en.onepiece-cardgame.com/news/): promociones y eventos con material promocional; el catálogo cubre los productos | 15 min |
| Pokémon | `pokemon_tcg_news_es` | [Noticias del portal oficial del JCC](https://tcg.pokemon.com/es-es/news/), en español | 15 min |
| Pokémon | `pokemon_press_es` | [Prensa oficial de Pokémon](https://pokemon.gamespress.com/es), filtrada para anuncios del JCC físico | 30 min |
| Torneos | `local_tcg_events` | Calendarios públicos de Donde Jugar TCG para seis tiendas cercanas | 30 min |
| Torneos | `mundicomics_events` | [Agenda de Mundicomics](https://www.mundicomics.com/torneos-tcg) | 30 min |
| Torneos | `gladius_events` | [Torneos de Gladius Games](https://gladiusgames.net/es/238-torneos-tcg), con detalle de cada evento | 30 min |

Los intervalos de cinco minutos siguen `POLL_INTERVAL_SECONDS`; los demás tienen `interval_seconds` propio en el ejemplo. Las consultas y los detalles tienen límites de tiempo, tamaño y número de elementos. Las ventanas rotan para revisar contenido conocido y nuevo: no se promete descubrir toda una hemeroteca en una sola comprobación.

Los adaptadores y reglas de Magic mantienen su funcionamiento anterior. El perfil de juego se aplica también a los registros antiguos de fuentes Magic conocidas, conservando sus identificadores y la deduplicación. El cambio multijuego mantiene el esquema SQLite 2; no requiere borrar ni recrear la base. Una fuente desconocida no se convierte automáticamente en Magic por su título.

## Fuentes opcionales

Estas doce fuentes están registradas y **desactivadas por defecto**. Activa expresamente su bloque en el TOML y comprueba que una regla permita sus eventos.

| Ámbito | Identificadores | Límites principales |
| --- | --- | --- |
| Medios de Magic | `magicspoiler`, `mtggoldfish`, `mtgdrops`, `scg_news` | Fuentes secundarias; no prueban stock ni precio europeo |
| Galerías Pokémon | `pokemon_products_es`, `pokemon_products_us` | Catálogos de productos; acceso observado intermitente o bloqueado, sin inferir disponibilidad comercial |
| Pokémon Japón | `pokemon_news_jp` | Noticias del mercado japonés; región `JP`, idioma `ja` |
| Madrid | `local_tcg_events_madrid` | Grupo adicional de perfiles públicos de tiendas; puede solaparse con calendarios directos que actives |
| Next Dice | `nextdice_events` | Calendario directo de Algete |
| Arte9 | `arte9_events` | Calendario ICS público; no se inventan instancias de reglas recurrentes |
| Ludoteca Maldita | `ludoteca_events` | Calendario directo; las sesiones múltiples sin horario individual quedan indicadas como inciertas |
| Júpiter Guadalajara | `jupiter_guadalajara_events` | Calendario directo opcional de Guadalajara |

Pokémon Center respondió con bloqueo durante la investigación y **no tiene adaptador de stock**. No se incluyen como monitorización las cuentas de Instagram, Facebook u otras redes de las tiendas del chat: se utilizan calendarios públicos alternativos. La cuenta oficial de Secret Lair en Bluesky es la integración social de Magic ya existente.

## Región, idioma y canal

Las tarjetas muestran el juego y distinguen el alcance de una publicación del idioma en que está escrita y de dónde se puede comprar un producto.

- One Piece utiliza la edición occidental oficial, publicada para Norteamérica, Europa, Oceanía, Latinoamérica y Oriente Medio. Su perfil es `WESTERN` y declara los mercados `NA`, `EU`, `OC`, `LATAM` y `ME`. Discord lo presenta como «Occidente · incluye Europa». Un MSRP en dólares se conserva como texto de referencia; no se transforma en precio de compra europeo.
- Las noticias de Pokémon en español tienen región `GLOBAL` e idioma `es`. Esto no confirma una fecha española, stock europeo ni el idioma de las cartas. La galería estadounidense tiene región `US`; las noticias japonesas tienen región `JP`.
- Los calendarios locales tienen región `EU`, país `ES`, ciudad y tienda cuando la fuente aporta esos datos. Una fecha de torneo o una promoción de Bandai no equivale a una fecha de venta.
- El canal describe el contexto del elemento: por ejemplo `news`, `online`, `retail`, `announcement` o `event`. No es el canal privado de Discord.

Un filtro `regions = ["EU"]` admite un anuncio occidental de One Piece que declara Europa, pero no una noticia Pokémon de alcance global. El filtro no añade pruebas de stock. Para recibir también noticias globales, incluye `GLOBAL` entre los valores permitidos.

## Torneos y tiendas locales

El [inventario del chat compartido](local-stores-coverage.json), fechado el 25 de octubre de 2026, recoge **25 tiendas**. Se comprobaron 23 perfiles públicos de Donde Jugar TCG; para Next Dice y Júpiter Guadalajara se dispone de calendarios directos sin perfil del agregador comprobado. Tener una alternativa de calendario no significa que todas las tiendas estén activadas ni que se cubran todas sus actividades.

La configuración inicial cubre **ocho tiendas**:

- Medusa Cómics, Alcalá Cómics, Torrejugones, Hobbyshop Wargames, TCG Academy Madrid y Tsuki Center, mediante `local_tcg_events`.
- Mundicomics y Gladius Games, con adaptadores directos independientes.

El grupo opcional de Madrid y los calendarios directos amplían esa zona a otras tiendas, Algete y Guadalajara. Solo se consultan los perfiles configurados; no se recorre todo el directorio del agregador ni se siguen direcciones propuestas por el modelo. Al habilitar un calendario directo y el perfil agregado de la misma tienda pueden coexistir registros distintos: no hay fusión universal entre proveedores.

Cada torneo es un elemento `kind="event"`. El detector contempla `event.new`, `event.schedule_changed`, `event.cancelled` y `event.updated`; conserva el identificador del evento cuando existe para reconocer una reprogramación. La ausencia en una lista, una página incompleta o un error de red no prueban que haya sido cancelado.

La tarjeta separa **horario del torneo**, lugar y **tarifa de inscripción** de las fechas, precios y disponibilidad de productos. Las fechas con día pero sin hora conservan solo el día; no se añade medianoche. Los períodos de eventos oficiales se presentan como períodos, no como lanzamientos de cartas. Las sesiones múltiples y las recurrencias no se expanden en fechas inventadas. En la agenda de Mundicomics, cuando el año debe inferirse del contexto del calendario, el horario se marca como orientativo.

Un precio cero del agregador se trata como tarifa desconocida, no como entrada gratuita confirmada. El aforo publicado no es un contador de plazas libres. El calendario tampoco garantiza que una actividad se celebre: el enlace conserva la procedencia y permite confirmarla con la tienda. Los detalles de extracción y límites están en [la investigación de calendarios directos](research-store-calendars.md).

## Seleccionar juegos y reglas

El ejemplo [config.example.toml](../config.example.toml) incluye todos los bloques de fuentes y reglas. Selecciona juegos con:

```toml
[games]
enabled = ["magic", "one_piece", "pokemon"]
```

También puedes definir una lista separada por comas en las variables del stack:

```dotenv
ENABLED_TCGS=one_piece,pokemon
```

Si `ENABLED_TCGS` está definida, prevalece sobre `[games].enabled`. Se aceptan aliases como `mtg`, `onepiece` o `Pokémon`, normalizados a identificadores estables. Habilitar un juego no activa fuentes cuyo bloque esté desactivado. El sistema conserva su núcleo genérico para otros dominios; escribir un nombre nuevo no crea su adaptador.

Si montas un TOML, sus secciones de fuentes y reglas sustituyen las listas predeterminadas: **una fuente ausente del TOML no se activa automáticamente al actualizar**. Revisa tu archivo al incorporar One Piece, Pokémon o calendarios locales.

Las reglas admiten `tcgs`, `regions`, `cities` y `channels`, además de `sources`, `kinds`, `event_types`, `keywords`, `states` y `require_analysis`. Por ejemplo, esta regla permite torneos de One Piece de dos ciudades:

```toml
[[rules]]
id = "one-piece-cercano"
tcgs = ["one_piece"]
kinds = ["event"]
regions = ["EU"]
cities = ["Alcalá de Henares", "Torrejón de Ardoz"]
channels = ["event"]
require_analysis = false
```

Los valores dentro de un filtro se combinan con OR y los filtros de una regla con AND. Basta con que coincida una de las reglas habilitadas. Para restringir las alertas a esas ciudades debes adaptar o desactivar otras reglas más amplias, como `local-tcg-tournaments`; añadir esta regla no reduce las que ya permiten otros eventos. Una lista vacía no restringe ese campo.

Los juegos, regiones, ciudades y canales se normalizan para diferencias de mayúsculas, acentos y separadores. Los identificadores de fuente, categoría, estado y tipo de evento usan los valores del programa; las palabras clave ignoran mayúsculas. Si falta la ciudad, un filtro de ciudad no coincide. La selección final es determinista y no depende de que el modelo esté disponible.

Al desactivar un juego, una fuente o una regla, los envíos pendientes que dejan de estar permitidos se marcan como `skipped`. No se reactivan por volver a habilitarlo; los cambios nuevos sí pueden generar alertas. La base conserva los registros existentes y no se requiere borrar el volumen.

## Ver alertas y probar una tarjeta

Desde **Portainer → Containers → Drop Alerts → Console**, abre `/bin/sh`. Estos comandos consultan SQLite sin volver a consultar las fuentes:

```sh
python -m drop_alerts events --tcg one_piece --kind event --limit 10
python -m drop_alerts events --tcg pokemon --kind article --limit 10
python -m drop_alerts events --tcg magic --kind announcement --limit 10
python -m drop_alerts events --tcg pokemon --limit 10 --json
```

Para preparar una tarjeta con el último evento guardado que coincide:

```sh
python -m drop_alerts preview --tcg one_piece --kind event
python -m drop_alerts preview --tcg pokemon --kind article
```

Para enviarla expresamente al webhook configurado:

```sh
python -m drop_alerts preview --tcg one_piece --kind event --send
python -m drop_alerts preview --tcg pokemon --kind article --send
```

Solo `--send` hace un envío, con la marca **VISTA PREVIA MANUAL**. No cambia la cola ni la deduplicación; repetirlo vuelve a enviar la vista previa. Sin coincidencias no hay mensaje. Los comandos respetan juegos, fuentes y reglas actuales, e incluyen los eventos conservados del arranque silencioso. Desde el host antepón `docker compose exec drop-alerts`. Consulta [la guía de inspección](inspecting-alerts.md) para retención, límites y manejo de errores.

La [vista previa HTML multijuego](multi-tcg-preview.html) y su [JSON](examples/multi-tcg-discord.json) contienen tres ejemplos ficticios y no realizan envíos. Las tarjetas mantienen las menciones desactivadas, indican incertidumbre y utilizan imágenes solo cuando el adaptador las respalda. El modelo no puede generar nuevas URLs de navegación ni modificar los datos comerciales verificados.

## Actualizar en Portainer

1. Abre el stack desplegado desde el repositorio `https://github.com/gonibix23/drop-alerts.git`, rama `refs/heads/main`, con `docker-compose.yml`.
2. Revisa las variables y tu TOML montado, si lo utilizas. Mantén `BOOTSTRAP_MODE=silent` para incorporar cada fuente nueva sin avisos históricos.
3. Usa **Pull and redeploy** con reconstrucción de la imagen. El stack construye desde el repositorio; no necesita descargar una imagen llamada `drop-alerts` de un registro público.
4. Conserva `drop_alerts_data` y comprueba los registros y `python -m drop_alerts status`. El perfil multijuego conserva el esquema SQLite 2 y la historia de Magic.
5. Ejecuta `python -m drop_alerts doctor` dentro del contenedor para comprobar la conectividad de ese entorno. El acceso desde un equipo de desarrollo no verifica DNS, TLS o firewall de tu VM/LXC.

No se añaden puertos ni servicios auxiliares. El modelo remoto sigue siendo opcional; el nuevo catálogo y los calendarios tienen extracción y reglas deterministas. La conexión autenticada a tu modelo y la entrega real al webhook deben comprobarse con tus secretos en el despliegue. Consulta [despliegue](deployment.md), [modelo](llm-verification.md) y [solución de problemas](troubleshooting.md).
