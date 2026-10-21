# Arquitectura y garantías

## Módulos y contratos

| Componente | Responsabilidad y contrato |
| --- | --- |
| Configuración (`config.py`) | Lee variables y TOML, valida límites, zonas horarias y reglas; resuelve secretos directos o desde archivos. |
| Monitorización (`runtime.py`) | Programa consultas por fuente y trabajadores independientes para análisis y notificación; cierra conexiones al terminar. |
| Transporte (`http.py`) | Reutiliza HTTP, limita respuestas, espacia peticiones y conserva ETag/Last-Modified junto con el cuerpo necesario para interpretar un 304. |
| Adaptadores (`sources/`) | Implementan `SourceAdapter.fetch(http) -> FetchResult`; extraen evidencia y producen `Item`, sin enviar notificaciones. |
| Detección (`detection.py`) | Compara identidad, huellas y estados previos y produce `Event`; un resultado del modelo no cambia esos hechos. |
| Reglas (`rules.py`) | Filtran eventos por condiciones configuradas y deciden si requieren análisis válido antes del envío. |
| IA (`ai/`) | Implementa `Analyzer.analyze(task, content) -> dict | None`; interpreta datos con esquemas estrictos, caché y fallback. |
| Persistencia (`storage.py`) | Guarda estados, revisiones, eventos, trabajos, caché, diagnóstico y entregas de forma transaccional. |
| Notificación (`notifications.py`) | El canal implementa `NotificationChannel.send(event)`; el trabajador consume la outbox y guarda resultado o próxima espera. |
| Exclusión (`lock.py`) | Mantiene un bloqueo del sistema operativo durante la ejecución para impedir dos procesos de servicio con la misma base de datos. |

Las interfaces compartidas están en `models.py`. Un adaptador no conoce Discord ni el servidor de inferencia. El cliente de IA no conoce la política final de notificaciones. El transporte de Discord solo recibe el evento persistido.

## Datos genéricos

`Item` identifica un elemento por `(source, id)`, conserva título, URL verificada sintácticamente, categoría, estado, datos estructurados y fragmento de contenido. La huella usa esos datos y excluye la hora de observación para que consultar de nuevo el mismo contenido no genere cambios.

`Event` incluye identidad estable, fuente, elemento, tipo extensible, hora, título, URL, huella, instantáneas anterior/actual y análisis opcional. La identidad del evento deriva de la fuente, elemento, revisión, tipo y huellas comparadas. Así una transición `AVAILABLE → UNAVAILABLE → AVAILABLE` puede generar dos eventos distintos; un reintento de la misma observación conserva la identidad.

Las categorías y los datos JSON permiten representar publicaciones, versiones, eventos, tiendas y productos sin una tabla por integración. Los tipos iniciales incluyen `product.new`, `collection.new`, `announcement.new`, `publication.new`, `item.new`, `availability.changed`, `price.changed`, `content.changed` y `change.uncertain`. Los estados de Secret Lair no son una enumeración global obligatoria para todos los dominios.

Los errores de extracción no son elementos. Una página vacía, inaccesible o incompatible falla antes de aceptar una nueva referencia. La ausencia en una portada limitada no equivale a una desaparición o agotamiento. Un `UNKNOWN` expresa incertidumbre de la observación, no un estado de compra confirmado.

## Límite de confianza

Todo HTML, metadato y texto obtenido de una web es entrada no confiable. La extracción determinista comprueba su estructura y procedencia, y solo acepta señales concretas para afirmar precio o disponibilidad. Una señal publicada por la fuente es una observación; no implica una compra garantizada.

El modelo recibe únicamente contenido limitado y las instrucciones de la tarea, sin webhook ni claves. Sus esquemas rechazan campos adicionales, tipos incorrectos, resultados fuera de rango y evidencia que no aparezca literalmente en la entrada. La evidencia literal prueba dónde apareció una frase; no garantiza que esa frase sea verdadera ni elimina por sí sola los intentos de prompt injection.

La defensa principal es limitar la autoridad del modelo: no tiene herramientas y el programa no ejecuta su texto, no visita URLs propuestas, no modifica configuración ni reescribe hechos de disponibilidad o precio con sus respuestas. El análisis almacenado se marca `engine=model` y `verified=false`. Las decisiones deterministas se identifican con su motor. Los avisos reflejan incertidumbre y no presentan el resumen libre del modelo como hecho verificado.

Las tareas `classification`, `extraction`, `relevance`, `semantic_match`, `change` y `summary` tienen esquemas independientes. El flujo inicial programa clasificación de elementos ambiguos y noticias y análisis de cambios de contenido cuando procede; las demás tareas están disponibles para integraciones que las necesiten. No se ejecutan todas por elemento.

## Transacciones y recuperación

SQLite usa WAL, `synchronous=FULL`, claves foráneas y espera limitada ante bloqueos. Cada lote válido se ingiere con una transacción `BEGIN IMMEDIATE`: referencia de fuente, elemento, revisión, evento, outbox y trabajo de IA asociado se aceptan juntos o se deshacen. Un cierre entre esos pasos no debe dejar un evento detectado sin su trabajo de entrega.

El arranque silencioso se aplica por fuente después de su primera lectura válida. Un fallo inicial no marca esa fuente como inicializada. Los elementos de referencia se guardan pero no llenan Discord con novedades históricas. `BOOTSTRAP_MODE=notify` cambia explícitamente ese comportamiento.

Las consultas HTTP tienen una caché de transporte separada del estado aceptado. Un cuerpo HTTP 200 incompatible puede estar en esa caché y seguirá fallando al interpretarse incluso si la siguiente respuesta es 304; no reemplaza los productos almacenados por una lista vacía.

Los trabajos de IA se identifican por contenido/elemento, revisión y tarea y se guardan antes de ejecutarse. La cola prioriza trabajos recientes y marca los más antiguos como superados al exceder el límite. Al terminar un análisis, su resultado y la liberación de la notificación que lo esperaba se actualizan juntos. Un reintento de análisis no crea otro evento ni otra notificación.

Las reglas normales permiten notificar evidencia determinista sin esperar al modelo. Una regla con `require_analysis=true` espera un análisis válido; si está desactivado, falla definitivamente o el trabajo se descarta por límite de cola, esa entrega pasa a `dead`. No se transforma el fallo en una clasificación afirmativa.

## Entrega con reintentos

La outbox conserva `pending`, `waiting_analysis`, `sent` y `dead`, número de intentos y próxima fecha. Se envía el evento ya guardado y después se confirma el resultado en una transacción. HTTP 429 respeta la espera de Discord; el bloqueo del canal se conserva para respetarlo también tras reiniciar. Los errores temporales usan espera progresiva y los permanentes terminan la entrega. Los reintentos tienen un límite, por lo que no se promete entrega eventual ante fallos persistentes.

El diseño usa reintentos con semántica de entrega al menos una vez: existe una ventana inevitable si Discord acepta el mensaje y la aplicación no llega a registrar el éxito. Después del reinicio, ese envío aún pendiente puede repetirse. Los webhooks entrantes no proporcionan una clave de idempotencia que permita garantizar exactamente una vez. La deduplicación interna evita repetir eventos por comprobaciones idénticas o reintentos de IA, pero no elimina esa ventana de confirmación externa.

`allowed_mentions` desactiva menciones automáticas. Se limitan los campos del mensaje y las respuestas HTTP. No se registran claves ni el webhook completo.

## Una instancia y conservación

Ejecuta una réplica por base de datos. El bloqueo se mantiene abierto durante la vida del servicio y el sistema operativo lo libera al terminar o fallar el proceso. No borres manualmente el archivo de bloqueo para iniciar una segunda instancia. No uses un volumen de red ni varios hosts como mecanismo de coordinación distribuida: este proyecto no implementa consenso o bloqueo entre nodos.

La limpieza automática diaria por retención borra historia operativa, caché y diagnósticos antiguos. Conserva identidades, revisiones actuales y los registros mínimos de eventos/entregas para deduplicar. Los datos de eventos pendientes y de análisis necesarios no se eliminan antes de terminar su trabajo. La cantidad de identidades retenidas puede crecer con el número total de elementos vistos; esa persistencia es parte de la garantía de recordar el pasado. Los comandos de mantenimiento que escriben, como `prune` y `retry-notifications`, exigen detener previamente el servicio para adquirir el mismo bloqueo.

El latido del proceso comprueba actividad del servicio, mientras que `status` expone por separado última comprobación correcta, fallos de fuentes y colas. Un contenedor sano puede tener una fuente bloqueada o el modelo inaccesible; se necesita consultar también ese diagnóstico.
