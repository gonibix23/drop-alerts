# Calendarios locales comprobados e implementados

Revisión del **25 de octubre de 2026**, a partir de las tiendas del chat compartido. Se hicieron consultas públicas HTTPS con verificación TLS, sin iniciar sesión, inscribir jugadores ni enviar mensajes. Las capturas de trabajo están en `work/research/local-tcg/`, excluidas de Git; las pruebas contienen fragmentos mínimos de esas respuestas.

## Fuentes y cobertura

| ID / adaptador | Fuente comprobada | Extracción utilizada | Alcance y límites |
| --- | --- | --- | --- |
| `gladius_events` / `GladiusEventsSource` | [Torneos TCG de Gladius Games](https://gladiusgames.net/es/238-torneos-tcg) | Listado JSON-LD `ItemList`; fichas de entradas `Product` con nombre coincidente con el `h1` visible | Fecha completa `dd/mm/yyyy` del título, inscripción publicada en `Offer`, local en Alcalá de Henares. No se deduce hora ni se interpreta `InStock` como estado del torneo. La lista observada tenía cinco fichas; no representa un archivo histórico completo. |
| `nextdice_events` / `NextDiceEventsSource` | [Eventos de Next Dice](https://nextdice.es/eventos/) | Tarjetas HTML `article.ndep-card`, `data-start` ISO, categoría específica de esa tarjeta y tarifa del pie | Incluye archivo y futuros eventos de Algete. Se priorizan fechas más recientes con una ventana rotatoria. La categoría de cada evento permite identificar Magic aunque el título sea «Friday Night Next Dice»; se rechazan etiquetas contradictorias. No se utiliza el menú general como prueba del juego. |
| `arte9_events` / `Arte9EventsSource` | [iCal declarado por Arte9](https://arte9.com/torneos/?ical=1), descubierto en su [calendario](https://arte9.com/torneos/) | iCalendar: `UID`, URL del evento, `DTSTART`/`DTEND`, `TZID`, `CATEGORIES`, `STATUS` y descripción | El iCal comprobado ocupaba aproximadamente 144 KB, frente a más de 2 MB del HTML general. La [categoría One Piece](https://arte9.com/torneos/categoria/one-piece/) también respondió correctamente, pero se prefiere el iCal para cubrir varios juegos. No se eleva el límite general de respuesta. |
| `ludoteca_events` / `LudotecaEventsSource` | [Eventos de Ludoteca Maldita](https://ludotecamaldita.com/eventos/) | Tarjetas Mage Eventpress y fichas JSON-LD `Event` coherentes con el título visible | Separa horarios estructurados de ventanas de varias sesiones. «Price Starts» en el listado no demuestra una tarifa plana: solo se admite un precio inequívoco confirmado por la ficha del evento. |

Los cuatro devuelven elementos `kind=event`, con juego, idioma de la fuente, procedencia de tienda, región y lugar. No generan productos a la venta ni estados de stock. La fecha del torneo se guarda en `event_schedule`, separada de `release_schedule` de un producto. Las fechas normalizadas y sus valores originales se conservan en el contenido como evidencia para la presentación.

## Qué se ha comprobado

- Las páginas del listado, fichas de ejemplo e iCal respondieron correctamente en consultas directas con TLS. La categoría One Piece de Arte9 se recibió en aproximadamente 518 KB y el iCal en aproximadamente 144 KB; son tamaños de esas respuestas, no mediciones del contenedor ni garantías futuras.
- En la captura de Next Dice se reconocieron 110 eventos de los tres juegos objetivo. La fuente también contiene otras actividades, que se excluyen. No se interpreta que todas esas fechas sigan siendo futuras.
- El iCal de Arte9 incluía 30 registros; 19 correspondían a los juegos objetivo. Cuando el proveedor deja `SUMMARY` vacío se usa un título genérico derivado de la categoría explícita, indicando `title_derived`; no se inventa el nombre formal de un torneo a partir de su imagen.
- La ficha comprobada de Gladius publica un Challenge de Pokémon con día **14/11/2026**, sin hora en la información extraída y con inscripción de **6 EUR**. Esa tarifa es una entrada de torneo, no el precio de un producto Pokémon. La hora permanece por confirmar.
- La ficha de Ludoteca examinada describe sesiones el 24 y el 28 de octubre. No se presenta como un torneo continuo de cuatro días ni se crean instancias con horas deducidas: se conserva el período literal y se marca que hay varias sesiones.

## Identidad, reinicios y errores

Gladius conserva el identificador numérico del producto de entrada, aunque cambien el título o su fecha. Next Dice usa la URL canónica de la ficha. Ludoteca utiliza el `data-event-id` observado cuando está disponible. Arte9 conserva el ID numérico de su URL de evento: el `UID` publicado también se guarda, pero incluye timestamps y no conviene convertir un simple cambio de horario en un evento nuevo. `RECURRENCE-ID`, cuando existe, separa ocurrencias explícitas.

Las fuentes mantienen inventarios `bootstrap_ids` completos de la ventana descubierta y límites de elementos, fichas y tiempo. Las comprobaciones posteriores rotan mediante un cursor persistido; una ficha inaccesible no cancela ni elimina lo guardado. Una respuesta de mantenimiento, HTML incompleto o calendario roto falla como extracción. Solo un `STATUS:CANCELLED` del calendario o un estado estructurado equivalente cancela el evento; ausencia del listado o entradas agotadas no bastan.

El lector iCal admite líneas plegadas, fechas sin hora y horas con `TZID` válido. Las horas inexistentes o ambiguas durante el cambio estacional se rechazan. Las fechas sin hora conservan solo el día. Los registros con `RRULE`, `RDATE` o `EXDATE` se detectan pero no se expanden: no se inventan sesiones futuras ni se ignoran silenciosamente exclusiones de recurrencia. No se instala una biblioteca adicional. Si la respuesta solo contiene registros no admitidos o inválidos, la comprobación falla conservando el estado.

## Configuración y limitaciones

Los adaptadores tienen URLs oficiales de la propia tienda fijadas en su módulo; no siguen enlaces arbitrarios de las descripciones, grupos de WhatsApp ni plataformas de inscripción. Los enlaces externos quedan como contenido, sin acciones automáticas. No fue necesario acceder a APIs privadas ni suponer rutas WordPress: los calendarios HTML y el iCal declarado bastan.

Gladius y Ludoteca limitan las fichas consultadas por ronda; Next Dice y Arte9 limitan los eventos entregados por ronda. El alta inicial debe conservar `BOOTSTRAP_MODE=silent` y el volumen de SQLite. La configuración predeterminada del proyecto decide cuáles se activan; disponer del adaptador no implica que todos estén habilitados. No se ha probado la conectividad desde Proxmox/Portainer ni se ha hecho una entrega real a Discord en esta investigación.
