# Solución de problemas

## El stack falla con pull access denied

El Compose predeterminado construye la aplicación con `build:` desde el repositorio. Actualiza `docker-compose.yml` y despliega desde **Repository** con la ruta `docker-compose.yml`. Si aún aparece `image: drop-alerts:1.0.0` o una referencia GHCR, estás usando la configuración anterior o la alternativa de descarga. Elimina la variable antigua `DROP_ALERTS_IMAGE` y comprueba el contenido efectivo del stack. El modo Web editor por sí solo no proporciona el Dockerfile ni el código necesarios para construir.

La construcción desde Git utiliza el acceso al repositorio privado configurado en Portainer, igual que otros proyectos privados con `build:`. No requiere autenticar la imagen de aplicación en un registro. Si falla la descarga de la imagen base o de dependencias, revisa la conectividad del Docker Engine y el error concreto de la construcción.

Solo para la alternativa GHCR: el paquete es privado y necesita un registro personalizado `ghcr.io`, usuario `gonibix23` y un token de GitHub **classic** con `read:packages`. Selecciona ese registro para el stack y comprueba que la publicación y la etiqueta existan. El acceso Git y el acceso al registro son independientes. Instrucciones y enlaces oficiales en `deployment.md`.

## No llegan mensajes

Consulta logs y `python -m drop_alerts status`. En el arranque inicial, `BOOTSTRAP_MODE=silent` registra los elementos existentes sin avisar. Una regla debe coincidir con el evento. Verifica que el webhook esté configurado y siga existiendo, sin copiar su URL completa a tickets o capturas. Discord puede responder 429; la cola conserva el trabajo y respeta la espera indicada. Un error permanente puede terminar los reintentos: consulta el historial y corrige la configuración antes de reanudar operaciones.

Si reinicias con un volumen vacío, empiezas una referencia nueva. Conserva el volumen para recordar estados y entregas. No elimines SQLite como primer paso de diagnóstico. Tras corregir un webhook rechazado puedes detener el servicio, ejecutar `docker compose run --rm drop-alerts retry-notifications` y volver a arrancarlo. Este comando reactiva entregas `dead` por fallos del canal; no reactiva casos que fallaron por análisis obligatorio ni mensajes ya enviados. Reintentar puede volver a enviar un mensaje cuya confirmación se hubiera perdido.

## Fuente con HTTP 403, 429 o error de extracción

Una protección del sitio o una estructura cambiada puede impedir la lectura. Ese fallo no significa que los productos hayan desaparecido. Revisa `docs/source-research.md`, prueba desde el endpoint de despliegue y conserva la última respuesta correcta. No bajes el intervalo para forzar el acceso; respeta `Retry-After` y las condiciones de la fuente. Si hay un bloqueo, necesita resolverse con un método permitido por el propietario del sitio o una fuente oficial accesible. No se instala Chromium automáticamente.

## El modelo no responde o devuelve texto inválido

El seguimiento determinista continúa. Comprueba `LLM_BASE_URL` —incluye `/v1` cuando el servidor lo requiera—, el modelo publicado, el tiempo de espera y la autenticación del proxy. Un nombre de modelo configurado no demuestra que esté instalado. `docs/llm-verification.md` recoge los resultados observados durante el desarrollo.

La salida debe cumplir el esquema: valores fuera de rango, campos inesperados o evidencia no presente pueden descartarse. Hay un número limitado de reintentos y una pausa después de fallos repetidos; no se acumulan inferencias sin límite. Tras corregir el servidor, los trabajos que sigan pendientes podrán reintentarse. Para operar sin análisis semántico configura `LLM_ENABLED=false`.

## DNS, TLS, firewall y proxy

Haz el diagnóstico dentro del contenedor; la conexión desde tu navegador no prueba la red de la VM/LXC. Un timeout puede indicar firewall o proxy; un error de resolución apunta a DNS; un error TLS requiere revisar nombre del certificado, vigencia y cadena de confianza. Sincroniza el reloj del host. Para CA privada usa el paquete PEM y `SSL_CERT_FILE` como indica `deployment.md`. Mantén la verificación TLS activada.

Un HTTP 401/403 puede proceder del proxy en vez del servidor del modelo. Configura la autenticación que realmente admita. Una página de login HTML no es una respuesta compatible con el contrato JSON de chat. Evita registrar cabeceras de autenticación.

## Contenedor unhealthy o bucle de reinicio

Consulta primero los logs. Un fallo de validación, una ruta inexistente o un volumen no escribible puede impedir arrancar. El volumen debe permitir escribir a UID/GID 10001. En un bind mount prepara permisos desde el host; no cambies a root como solución permanente. El healthcheck no envía peticiones a Discord ni al modelo y no garantiza que todas las fuentes estén disponibles.

La raíz del contenedor es de solo lectura; guarda base de datos y latido en `/data`. Las rutas de secreto y CA deben estar montadas y ser legibles por el usuario del servicio. Una zona horaria desconocida o un valor booleano mal escrito deben corregirse en las variables.

## Crecimiento del almacenamiento

Docker rota los logs. Revisa la política `RETENTION_DAYS` y el estado de trabajos pendientes. El servicio limpia registros operativos antiguos diariamente. Si ejecutas `prune` manualmente, detén antes el servicio: el bloqueo de instancia impide dos procesos de escritura simultáneos. Los estados actuales y claves necesarias para deduplicar requieren persistencia; su tamaño depende del número de elementos únicos. SQLite puede conservar espacio interno reutilizable tras borrar registros. Planifica cualquier compactación con una copia de seguridad y el servicio detenido.

## Mensaje duplicado después de un fallo de red

El servicio evita duplicados por identidad, huella y estado persistido. Sigue existiendo una ventana si Discord acepta un mensaje pero la respuesta se pierde antes de guardar la confirmación. Los webhooks entrantes no tienen una clave de idempotencia utilizable para cerrar esa ventana. Un reintento puede producir un segundo mensaje; no se promete entrega exactamente una vez.
