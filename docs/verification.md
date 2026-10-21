# Estado de verificación de la entrega

Comprobado el 21 de octubre de 2026. El proyecto utiliza la rama `main` y su repositorio de GitHub es privado: [gonibix23/drop-alerts](https://github.com/gonibix23/drop-alerts).

## Ejecutado correctamente

- Instalación del paquete y dependencias de desarrollo en un entorno aislado.
- `python -m pytest -q --basetemp work/pytest-final-complete`: **124 pruebas aprobadas**, Python 3.14 en Windows. Las pruebas no hacen peticiones reales ni publican en Discord.
- `python -m pip check`: sin dependencias incompatibles.
- Compilación de los módulos Python con `compileall`.
- `docker compose config --quiet`: configuración válida, sin necesidad de motor Docker.
- Disponibilidad de ruedas binarias de dependencias para CPython 3.12 Linux amd64 y arm64. No equivale a ejecutar pruebas en esas plataformas.

## Fuentes reales

Se hicieron consultas HTTPS con TLS verificado a las fuentes y a los endpoints públicos descubiertos en sus páginas. Una pasada real del servicio con IA desactivada y sin webhook guardó referencias de ambas fuentes sin enviar mensajes. La consulta ampliada descubrió 67 productos; algunas páginas usan JSON-LD `Thing`, por lo que se añadió una extracción conservadora comprobada con esos cuerpos reales guardados.

La reproducción final sin red de las respuestas capturadas extrajo **70 elementos de Secret Lair** (67 productos y 3 anuncios) y **8 artículos de Magic**, sin errores de extracción. Entre los productos: 14 con `AVAILABLE`, 8 con `UPCOMING` y 45 con `UNKNOWN`, sin inventar stock o precio en los documentos `Thing`. Repetir la reproducción contra el estado persistido produjo **0 eventos nuevos y 0 notificaciones pendientes**. Estos recuentos pertenecen a esa captura y no describen necesariamente el catálogo actual de tu despliegue. Véase `source-research.md` para procedencia, señales utilizadas y límites de cobertura.

## Modelo remoto

La raíz del servidor y `/v1/models` respondieron HTTP 401 sin credencial; `/api/tags` agotó el saludo TLS. Se comprobó la respuesta de la infraestructura, pero **no la compatibilidad de chat, la existencia del modelo ni una inferencia autenticada**. El cliente y sus fallos están probados con respuestas simuladas. Configura la autenticación real y ejecuta `doctor` y `check-llm` desde el contenedor; instrucciones en `llm-verification.md`.

## Pendiente en Docker y Portainer

Se intentó construir la imagen. La configuración Docker del usuario no era legible en este entorno; usando una carpeta de configuración aislada el intento llegó a la conexión con el motor y falló porque no existía el pipe `docker_engine`. No se ha construido ni ejecutado la imagen localmente. La integración continua incluye pruebas Python 3.12/3.14 y una construcción en Linux, pendiente de ejecutarse tras publicar el repositorio.

No se ha accedido a tu Proxmox, Portainer, VM/LXC o Discord. Quedan pendientes la construcción real, permisos del volumen UID 10001, red/DNS/TLS/proxy/autenticación desde ese contenedor y una entrega real a tu webhook. No se ha medido tamaño de imagen, RAM o CPU.

La deduplicación interna y los reintentos se han probado. Una confirmación perdida después de que Discord acepte un mensaje puede causar una repetición; los webhooks no permiten prometer entrega exactamente una vez.
