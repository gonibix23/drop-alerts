# Añadir fuentes, reglas, categorías y análisis

## Adaptador de fuente

La interfaz `SourceAdapter` define `id` y `async fetch(http) -> FetchResult`. Un adaptador debe devolver `Item` con:

- `id`: identidad estable dentro de su fuente, derivada de un identificador publicado o URL canónica verificada.
- `source`, `title`, `url`: procedencia y enlace HTTP(S) reales.
- `kind`: categoría extensible, por ejemplo `product`, `publication`, `release` o `event`.
- `state`: estado propio del dominio. No tienes que usar estados de tienda para una versión de software.
- `data`: hechos estructurados, incluida la evidencia usada para precio o disponibilidad.
- `content`: fragmento relevante para interpretación, sin toda la navegación de la página.

`observed_at` registra cuándo se observó y `engine` identifica la clasificación determinista o del modelo. `Item.digest` excluye el instante de observación para que una comprobación repetida no parezca un cambio.

Implementa el módulo en `drop_alerts/sources/`, regístralo donde se construyen los adaptadores y añade su opción de activación al archivo TOML. Utiliza el transporte compartido para conexiones, límites y consultas condicionales. Nunca conviertas una excepción HTTP, un documento vacío o un selector que dejó de existir en una lista de productos agotados: lanza `ExtractionError` y conserva el último estado correcto.

El punto de registro es `SOURCE_FACTORIES` en `drop_alerts/registry.py`: cada fábrica recibe `(settings, store)` y devuelve el adaptador. La validación de configuración consulta ese registro, sin mantener otra lista de fuentes en el núcleo. Si un catálogo se consulta por ventanas, devuelve `metadata.bootstrap_ids` con todas las identidades descubiertas al establecer la referencia para silenciar también su primera lectura detallada posterior. Los fallos parciales pueden declararse en `metadata.errors`, conservando solo elementos extraídos correctamente.

Prioriza feeds anunciados por la fuente, sitemaps, JSON-LD, metadatos y HTML del servidor. Antes de fijar un endpoint o selector, guarda una respuesta real y documenta fecha y procedencia. Descubre enlaces desde la fuente oficial, restringe el origen y limita el número de detalles visitados. No permitas que la IA sugiera nuevas URLs para el monitor.

Añade pruebas con respuestas guardadas: estructura válida, vacía, parcialmente cambiada, JSON malformado, redirección o enlace fuera del origen, límites y fallo de un detalle. Especifica la cobertura: una portada limitada no equivale a un catálogo histórico completo.

## Reglas

Las reglas del TOML son datos, no código ejecutable. Admiten `sources`, `kinds`, `event_types`, `keywords` y `states`:

```toml
[[rules]]
id = "software-releases"
enabled = true
sources = ["my_releases"]
kinds = ["release"]
event_types = []
keywords = []
states = []
require_analysis = false
```

Los filtros no vacíos deben coincidir y los valores de cada filtro ofrecen alternativas. Una lista vacía acepta cualquier valor de ese campo. Mantén identificadores de regla estables. Para una condición nueva, amplía el motor de reglas con un predicado determinista y una prueba que muestre cuándo coincide y cuándo no. Una categoría nueva puede viajar en `kind`, los datos y el evento sin crear una tabla por dominio.

`require_analysis=true` reserva una regla para casos cuya interpretación necesita un análisis válido. No debe convertir un fallo del modelo en un cambio de disponibilidad ni impedir el seguimiento de otras fuentes. Para avisos respaldados por datos explícitos, conserva reglas con `require_analysis=false`.

## Analizadores

La interfaz `Analyzer` es `async analyze(task, content) -> dict | None`. La implementación inicial usa un cliente HTTP independiente. Para cambiar de servidor, configura la URL base, modelo y autenticación. Para una API distinta, implementa otro cliente que cumpla la interfaz; el núcleo no necesita importar una SDK del proveedor.

Las tareas se separan por intención: clasificación, extracción, relevancia, coincidencia semántica, interpretación de cambios y resumen. Al añadir una:

1. Define un esquema estricto con campos requeridos, límites de texto/listas, tipos y campos desconocidos rechazados.
2. Versiona el esquema e incluye esa versión y la tarea en la clave de caché.
3. Especifica evidencia literal y un resultado incierto cuando no alcance la información.
4. Delimita el contenido como datos no confiables y prohíbe obedecer instrucciones en él.
5. Limita entrada, salida, reintentos y trabajos pendientes.
6. Devuelve `None` o un fallo tipado cuando no se pueda validar, y prueba el fallback.

El resultado no es una orden. Antes de usar campos propuestos, comprueba evidencia, procedencia y restricciones del dominio. Nunca permitas que precios o estados inventados por el modelo sustituyan indicadores verificables; su confianza no es una probabilidad calibrada. No uses un resumen libre para construir URLs o ejecutar comandos.

## Canales de notificación

La interfaz `NotificationChannel` define `async send(event)`. Implementa otro canal sin acoplarlo a fuentes o IA. Reutiliza eventos persistidos y conserva el estado de reintentos, identificadores estables y separación entre fallo temporal y permanente. No incluyas secretos ni contenido completo de las páginas en las notificaciones.

## Base de datos y compatibilidad

Los identificadores se separan por fuente y los datos extensibles se guardan como JSON. Añadir un dominio no necesita una tabla propia. Los cambios de esquema sí requieren una migración versionada y una copia de seguridad previa. No cambies la fórmula de identidad sin un plan para conservar la deduplicación; cambiar IDs puede hacer que elementos conocidos parezcan nuevos.
