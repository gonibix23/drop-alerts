# Consultar alertas y probar un mensaje

La consulta de alertas guardadas funciona dentro del contenedor, sin abrir puertos ni añadir servicios. Puedes ejecutarla desde **Portainer → Containers → contenedor de Drop Alerts → Console**, con `/bin/sh`. Desde una terminal del host, añade `docker compose exec drop-alerts` delante de cada comando.

## Ver las últimas alertas de un TCG

```sh
python -m drop_alerts events --tcg one_piece --limit 10
python -m drop_alerts events --tcg pokemon --kind article --limit 10
python -m drop_alerts events --tcg magic --kind announcement --limit 10
python -m drop_alerts events --tcg one_piece --kind event --limit 10
python -m drop_alerts events --source tabletop_gamers --kind product --limit 10
```

Sin `--tcg`, muestra las alertas que coincidan con los juegos habilitados y las reglas actuales. Se aceptan aliases como `mtg`, `onepiece` o `Pokémon`; los nombres se normalizan a identificadores estables. Un juego sin eventos o desactivado no devuelve alertas. `--limit` admite de 1 a 100.

`--kind` permite `announcement`, `article`, `event` o `product`. Si lo omites, se incluyen los distintos tipos de elementos conservados. La lista también incluye cambios posteriores de un elemento, no solamente su primer anuncio. Las fuentes desactivadas y los registros que no cumplen las reglas actuales quedan excluidos; por ejemplo, una noticia general de Magic no se muestra si la regla requiere Secret Lair.

`--source` limita a un identificador de fuente, como `tabletop_gamers` o `jjcollection`. Se combina con los demás filtros y no evita la selección de juegos ni las reglas actuales.

Para integraciones o un resultado estructurado:

```sh
python -m drop_alerts events --tcg pokemon --limit 10 --json
```

El JSON incluye título, juego, fuente, fecha de detección original, tipo de evento, tipo de elemento y enlace. La lista legible presenta la fecha usando `TIMEZONE`.

## Ver el último mensaje sin enviarlo

```sh
python -m drop_alerts preview --tcg one_piece
python -m drop_alerts preview --tcg pokemon --kind article
python -m drop_alerts preview --tcg magic --kind announcement
```

Se imprime el payload del mensaje con el formato actual de Discord. No se consulta ninguna web, no se llama al modelo y no se envía nada. El render puede calcular fechas a partir del texto ya guardado, manteniendo su incertidumbre y su fecha de detección original.

## Enviar una vista previa explícitamente

```sh
python -m drop_alerts preview --tcg one_piece --send
python -m drop_alerts preview --tcg pokemon --kind article --send
python -m drop_alerts preview --tcg magic --kind announcement --send
python -m drop_alerts preview --source tabletop_gamers --kind product --send
python -m drop_alerts preview --source jjcollection --kind product --send
```

`--send` hace **una petición** al webhook ya configurado, mediante `DISCORD_WEBHOOK_URL` o su archivo de secreto. El mensaje lleva la marca **VISTA PREVIA MANUAL** para distinguirlo de una nueva detección. No necesitas copiar el webhook en la consola ni incorporarlo al comando.

La vista previa no cambia la cola, los intentos de entrega, el historial de notificaciones ni la deduplicación. Tampoco marca el evento como enviado. Si pruebas un evento pendiente, el monitor conserva su entrega normal; repetir `--send` vuelve a enviar expresamente una vista previa. Si todas las reglas coincidentes exigen análisis, el evento solo puede seleccionarse cuando lo tenga guardado; la prueba manual no evita esa condición.

Ante HTTP 429 se indica cuánto esperar y no se reintenta automáticamente. Otros errores muestran el código HTTP o el tipo de fallo de conexión, sin imprimir el webhook, claves ni el cuerpo de la respuesta. Si una respuesta se pierde tras aceptar Discord el mensaje, comprueba el canal antes de repetir: una nueva prueba manual podría duplicar esa vista previa.

## Persistencia y referencia inicial

Los comandos abren SQLite con `mode=ro` y no instancian el almacén de escritura: no crean una base, no aplican migraciones ni cambian su estado. Son compatibles con el servicio ejecutándose. También permiten ver eventos registrados durante `BOOTSTRAP_MODE=silent`, aunque no exista una notificación en la cola.

Si todavía no existe SQLite, espera a la primera comprobación del servicio. Si no hay coincidencias, revisa el TCG habilitado, las fuentes y las reglas; no borres el volumen ni cambies a `BOOTSTRAP_MODE=notify` solo para probar un mensaje. Los eventos cuyo contenido completo ya haya sido eliminado por retención no se pueden previsualizar.
