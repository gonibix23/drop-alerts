# Fecha prevista de venta o lanzamiento

Drop Alerts intenta extraer del anuncio **cuándo se abre la venta, la preventa o el lanzamiento**. Guarda la fecha, su evidencia y la incertidumbre; Discord la presenta separada de **Detectado**, que indica cuándo el monitor observó el evento.

Una fecha anunciada puede cambiar y no acredita stock. El estado comercial y los precios siguen dependiendo de indicadores verificables de la fuente y de su región.

El día anunciado se conserva aunque ya haya pasado: no se desplaza al año siguiente para hacerlo parecer futuro ni se interpreta como prueba de que el producto siga a la venta.

## Qué aparece en Discord

| Datos del anuncio | Presentación |
| --- | --- |
| Fecha de venta y hora con zona explícita | **Venta prevista**, convertida a `TIMEZONE` cuando la hora es válida e inequívoca |
| Fecha de preventa | **Preventa prevista** |
| Fecha de lanzamiento | **Lanzamiento previsto** |
| Fecha sin hora | Día anunciado y **hora sin confirmar** |
| Hora sin zona horaria | Hora original y **zona horaria no especificada**; no se convierte a Madrid |
| Año inferido o expresión tentativa | **Orientativa**, con la indicación de año inferido cuando corresponda |
| «Coming soon», mes sin día, fecha incompleta sin contexto suficiente | **Sin fecha confirmada** |
| Fechas incompatibles sin resolución fiable | **Fechas contradictorias · consultar fuente** |

Por ejemplo, `November 2, 2026, at 9 a.m. PT` puede mostrarse como **02/11/2026 · 18:00 CET · hora de Madrid**. El mismo horario del Pacífico en verano se convierte usando las reglas de cambio de hora de la fecha concreta. No se aplica un desplazamiento fijo a todos los anuncios ni se añade automáticamente la habitual hora de venta de Secret Lair.

Las horas ambiguas o inexistentes durante un cambio de horario quedan pendientes de confirmar. Cuando existe una ventana de venta, su cierre conserva la fecha indicada por la fuente: no se inventa una hora de cierre para convertirla a otra zona.

La [vista previa HTML](discord-preview.html) y el [JSON de ejemplo](examples/discord-announcement.json) contienen una fecha ficticia para ilustrar el formato.

## Cómo se obtiene la fecha

El extractor determinista examina fragmentos acotados del título y texto extraído. Reconoce expresiones en inglés y español relacionadas con venta, preventa y lanzamiento, y conserva citas literales que respaldan la fecha. Si aparecen varios hitos, prioriza la venta y mantiene la distinción con el lanzamiento general del producto.

Las fechas de **publicación del artículo, envío, entrega, legalidad de cartas o celebración de una convención** no se convierten por sí solas en fecha del drop. Tampoco se trata `lastmod` de un sitemap como una apertura de ventas. Una mención a «poco después del 23 de octubre» no establece automáticamente el día 23 como fecha exacta.

Si el anuncio omite el año, el extractor solo puede inferirlo a partir de una fecha de publicación utilizable, conservando la marca **Orientativa**. Puede resolver un cambio de diciembre a enero con ese contexto; no toma el año actual del contenedor como prueba de un año ausente. Si falta contexto suficiente, la fecha queda desconocida. Las expresiones relativas, como «mañana», también necesitan una referencia de publicación y se mantienen como estimaciones cuando corresponde.

Los resultados conservan `date`, `time`, `timezone`, `end_date`, `date_kind`, `certainty`, `evidence`, `engine` y `year_inferred` dentro de `data.release_schedule`. El esquema valida fechas de calendario, horas, zonas y coherencia de la ventana antes de mostrarlas.

## Ayuda opcional del modelo

Cuando el texto contiene una fecha concreta pero su relación con la venta necesita interpretación, el servicio puede utilizar la tarea independiente `release_schedule` del modelo configurado. El modelo selecciona una **cita literal** y propone qué hito describe. El programa vuelve a contrastar esa cita con su segmento original, conservando encabezados y negaciones. Solo puede normalizar una fecha literal única, válida y sin contexto excluyente; su relación con la salida sigue siendo orientativa cuando la propone la IA.

Una fecha ISO inventada por el modelo, una cita ausente o un fragmento que omita una negación no bastan para mostrar una fecha. Una confianza alta tampoco resuelve por sí sola una contradicción. Una interpretación semántica admitida queda marcada como orientativa y no sustituye una fecha determinista explícita diferente.

La tarea utiliza la caché y los límites existentes. Para dar oportunidad a esa ayuda opcional, la primera entrega puede esperar **como máximo 60 segundos**; con `LLM_ENABLED=false` no hay espera por IA. Si falla el modelo se libera la entrega con el resultado local, y si la cola está ocupada o no hay trabajador disponible, el plazo también vence. El resultado tardío no vuelve a enviar un mensaje que ya se entregó. Este plazo corresponde a la ayuda opcional para fechas; las reglas que exigen expresamente análisis conservan su comportamiento.

## Persistencia y cambios de fecha

La información temporal se guarda en los JSON existentes de SQLite. Esta ampliación **no introduce otra migración de esquema**: se mantiene el esquema 2 y la información existente.

Los elementos ya guardados se enriquecen silenciosamente cuando vuelven a comprobarse. Añadir estos campos por primera vez no crea por sí mismo una revisión, un evento ni una entrega histórica. Cuando el texto real de la fuente cambia y permite comparar dos fechas normalizadas diferentes con evidencia, se genera `release_date.changed`; Discord muestra **Cambio de fecha** y la comparación anterior → nueva.

El render de eventos antiguos también intenta calcular la fecha a partir del texto ya guardado. Por eso el script de vista previa del último anuncio entregado en el chat sigue funcionando tras actualizar: usa el nuevo formato y conserva la fecha de detección original, sin reconsultar la web ni modificar la deduplicación. La fecha obtenida corresponde al texto de ese evento, no necesariamente a una revisión posterior de la página.

## Actualizar el stack

En Portainer, actualiza el stack desde el repositorio de `main` y reconstruye la imagen con `docker-compose.yml`. Conserva el volumen actual y `BOOTSTRAP_MODE=silent`. La extracción usa la configuración existente de fuentes, zona horaria y modelo; el procedimiento completo está en [despliegue](deployment.md).
