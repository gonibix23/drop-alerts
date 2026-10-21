# Despliegue en Docker y Portainer sobre Proxmox

## 1. Preparar el acceso al repositorio

Portainer debe gestionar un Docker Engine en una VM o LXC con conectividad saliente HTTPS, DNS y almacenamiento persistente. Este proyecto no configura Proxmox ni modifica el host. La instalación de Docker dentro de un LXC depende de su configuración de permisos y aislamiento; utiliza un entorno Docker que ya funcione.

El Compose predeterminado utiliza `build:`, con contexto `.` y `Dockerfile`. Portainer obtiene el repositorio y construye la imagen en el Docker Engine del entorno elegido. El acceso necesario es el del repositorio Git privado; puedes utilizar las credenciales o la fuente Git que ya tengas configuradas para tus otros repositorios privados.

Utiliza **Repository** al crear el stack. Ese modo proporciona el Dockerfile y el código a la construcción. Pegar solamente el YAML en **Web editor** no incluye el contexto de construcción. El despliegue desde Git está descrito en [la documentación de Portainer](https://docs.portainer.io/user/docker/stacks/add#option-3-git-repository).

Para utilizar Docker Compose desde una terminal, autentica Git para leer el repositorio privado y ejecuta en la VM o LXC donde corre Docker:

```sh
git clone https://github.com/gonibix23/drop-alerts.git
cd drop-alerts
cp .env.example .env
# Editar .env y configurar DISCORD_WEBHOOK_URL.
docker compose up -d --build
```

`docker-compose.yml` contiene el contexto de construcción y no declara una imagen de aplicación que deba descargarse. Elimina `DROP_ALERTS_IMAGE` de las variables de intentos anteriores: el Compose actual no utiliza esa variable. Docker sí necesita acceso a los repositorios de la imagen base y de las dependencias durante la construcción.

La imagen final contiene el paquete instalado y la configuración predeterminada, sin pruebas, documentación ni herramientas de compilación. Ejecuta como UID/GID `10001:10001`, con raíz de solo lectura y `/tmp` temporal. SQLite y el latido se escriben en `/data`. La fase de construcción exige ruedas binarias para las dependencias: si una arquitectura no dispone de ellas, falla explícitamente en vez de añadir compiladores a la imagen.

Las dependencias tienen rangos acotados en `pyproject.toml`; la base `python:3.12-slim` y esos rangos pueden resolver versiones distintas al reconstruir. No se entrega un bloqueo de versiones o digest que no se haya comprobado. Para una publicación reproducible, fija el digest de la base y genera en CI un bloqueo de dependencias con hashes verificado para tus arquitecturas, guarda el inventario de la imagen construida y despliega por digest o etiqueta inmutable. Construir una vez y distribuir esa misma imagen evita que cada host resuelva dependencias por separado.

El 21 de octubre de 2026 se completó una descarga de las dependencias de ejecución y sus dependencias transitivas usando solo ruedas binarias para CPython 3.12 en Linux `manylinux_2_17_x86_64` y `manylinux_2_17_aarch64`. Se resolvieron httpx 0.28.1, Beautiful Soup 4.15.0, Pydantic 2.14.1 y pydantic-core 2.50.1. Esto comprueba la disponibilidad de esos artefactos para ambas arquitecturas; no ejecuta las ruedas ni sustituye una construcción y prueba de la imagen Docker. El motor Docker local no estaba disponible para esa construcción.

## 2. Crear el stack

1. En Portainer selecciona el endpoint Docker adecuado.
2. Abre **Stacks → Add stack**, escribe `drop-alerts` y elige **Repository**.
3. Selecciona o configura el repositorio privado `https://github.com/gonibix23/drop-alerts.git`, la referencia `refs/heads/main` y la ruta de Compose `docker-compose.yml`. Utiliza tus credenciales Git o una fuente Git ya configurada.
4. Añade las variables de `.env.example` en **Environment variables** o carga un archivo `.env` local si tu versión ofrece esa opción. Como mínimo configura `DISCORD_WEBHOOK_URL`. Elimina la variable antigua `DROP_ALERTS_IMAGE` si sigue presente.
5. Revisa `LLM_BASE_URL` y `LLM_MODEL`; añade `LLM_API_KEY` solamente si el servidor la exige.
6. Pulsa **Deploy the stack**. No necesitas puertos publicados ni otro servicio.
7. Abre **Containers → drop-alerts → Logs** y comprueba el estado de salud.

El volumen se llama normalmente `<nombre_del_stack>_drop_alerts_data`. No borres el volumen al recrear o actualizar el stack. El primer arranque registra la situación actual silenciosamente. `BOOTSTRAP_MODE=notify` permite avisar también de los elementos presentes en la primera comprobación; puede generar muchas notificaciones.

### Alternativa opcional: descargar la imagen de GHCR

GitHub Actions sigue publicando `ghcr.io/gonibix23/drop-alerts:main` para amd64 y arm64 después de superar las pruebas. Si prefieres descargar esa imagen, sustituye únicamente el bloque `build:` del servicio por esta línea y conserva el resto del Compose:

```yaml
    image: ghcr.io/gonibix23/drop-alerts:main
```

Para esta alternativa puedes utilizar **Web editor**. El paquete es privado: en **Registries → Add registry → Custom registry** configura URL `ghcr.io`, usuario `gonibix23` y un token de GitHub **classic** con `read:packages` como contraseña; después selecciona ese registro al desplegar. Las credenciales Git y las del registro son independientes. Consulta [la autenticación de GHCR](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-to-the-container-registry) y [el registro personalizado de Portainer](https://docs.portainer.io/admin/registries/add/custom). Configura el token directamente en Portainer y conserva su privacidad. Esta credencial de registro solo se necesita para la alternativa GHCR.

Antes de usar GHCR comprueba que la publicación concreta haya terminado correctamente en Actions. Puedes fijar una revisión con `ghcr.io/gonibix23/drop-alerts:sha-<SHA_COMPLETO_DEL_COMMIT>` o su digest. Para autenticar Docker desde Bash sin poner el token en la línea de comandos ni en el historial:

```bash
read -r -s -p 'Token de GitHub (read:packages): ' DROP_ALERTS_GHCR_TOKEN
printf '\n'
printf '%s' "$DROP_ALERTS_GHCR_TOKEN" | docker login ghcr.io --username gonibix23 --password-stdin
unset DROP_ALERTS_GHCR_TOKEN
```

Un webhook permite publicar en su canal: trátalo como contraseña. Las variables de entorno pueden ser visibles para administradores de Docker y Portainer. Para usar archivos de secreto, monta archivos del host con permiso de lectura para UID 10001 y configura solo su ruta dentro del contenedor:

```yaml
volumes:
  - drop_alerts_data:/data
  - /opt/drop-alerts/secrets/discord:/run/secrets/discord:ro
  - /opt/drop-alerts/secrets/llm:/run/secrets/llm:ro
environment:
  DISCORD_WEBHOOK_URL_FILE: /run/secrets/discord
  LLM_API_KEY_FILE: /run/secrets/llm
```

Integra estas entradas en el servicio existente. Deja vacías las variables directas correspondientes. Los secretos de Docker Swarm requieren la configuración propia del endpoint; un stack Compose de Docker standalone no crea automáticamente secretos Swarm.

## 3. Diagnóstico desde el entorno real

En **Containers → Console** abre una consola con `/bin/sh`, o ejecuta desde el host:

```sh
docker compose exec drop-alerts python -m drop_alerts doctor
docker compose exec drop-alerts python -m drop_alerts status
```

El diagnóstico de conexión sirve para comprobar la red desde el contenedor. No lo confundas con una prueba de entrega a Discord. Puedes consultar los modelos publicados sin imprimir credenciales ni el webhook:

```sh
docker compose exec drop-alerts python -c 'import os,httpx; base=os.environ.get("LLM_BASE_URL","https://llama.gonibix23.com/v1").rstrip("/"); r=httpx.get(base+"/models",timeout=20); print("HTTP",r.status_code)'
```

Este ejemplo no envía clave; un HTTP 401 puede ser el resultado correcto cuando se exige autenticación. `doctor` consulta los modelos y no ejecuta inferencias ni envía mensajes a Discord. Una inferencia real requiere una comprobación adicional del contrato descrito en `llm-verification.md`, sin publicar respuestas o secretos en tickets.

Los problemas habituales son DNS de la VM/LXC, reglas de firewall, salida hacia el proxy, certificado expirado, autoridad certificadora privada o autenticación del proxy. La aplicación mantiene TLS verificado. Si usas una CA privada, monta un paquete PEM que incluya las CA públicas necesarias y tu CA privada y define `SSL_CERT_FILE` en el servicio:

```yaml
volumes:
  - drop_alerts_data:/data
  - /opt/drop-alerts/certs/ca-bundle.pem:/run/certs/ca-bundle.pem:ro
environment:
  SSL_CERT_FILE: /run/certs/ca-bundle.pem
```

El certificado debe ser legible por UID 10001. No desactives la verificación TLS. Si necesitas un proxy, añade `HTTPS_PROXY`, `HTTP_PROXY` y/o `NO_PROXY` según tu red; no incluyas credenciales del proxy en el repositorio.

## 4. Personalizar las reglas

Guarda una copia de `config.example.toml` en el host y móntala:

```yaml
volumes:
  - drop_alerts_data:/data
  - /opt/drop-alerts/config.toml:/app/config.toml:ro
```

La ruta es la del host Docker del endpoint, no la del servidor de Portainer si son distintos. Reinicia el servicio después de cambiar la configuración. Un error de configuración impide arrancar y queda registrado sin mostrar secretos.

## 5. Actualizar y volver atrás

1. Realiza una copia consistente de SQLite.
2. Espera a que las pruebas de la revisión que vas a desplegar terminen correctamente en GitHub Actions.
3. En Portainer actualiza el stack desde el repositorio y habilita la reconstrucción de la imagen si tu versión ofrece esa opción. Comprueba en el log de despliegue que construye el Dockerfile con el código actualizado. Desde terminal, ejecuta `git pull` y `docker compose up -d --build`.
4. Comprueba logs, salud y `status`.

Para volver a una revisión anterior, selecciona esa referencia Git y vuelve a construir. Si utilizas la alternativa GHCR, espera su publicación y actualiza descargando la nueva imagen, o fija la etiqueta por commit o el digest elegido. Comprueba antes la compatibilidad del esquema de base de datos; si no es compatible, restaura también la copia de seguridad correspondiente con el servicio detenido. No ejecutes dos versiones contra el mismo archivo SQLite.

## 6. Copias de seguridad y mantenimiento

Para una copia sencilla, detén el contenedor, copia el volumen completo y vuelve a arrancar. Incluye los archivos `-wal` y `-shm` si existen; copiar solamente el `.db` mientras se está escribiendo puede perder transacciones. También puedes utilizar la API de backup de SQLite para una copia en caliente.

Con el stack en marcha:

```sh
docker compose logs --tail=100
docker compose exec drop-alerts python -m drop_alerts status
docker stats --no-stream
docker compose images
```

La limpieza por retención se ejecuta automáticamente cada día. Para forzarla manualmente, detén el servicio antes de iniciar un proceso de mantenimiento contra su volumen:

```sh
docker compose stop drop-alerts
docker compose run --rm drop-alerts prune
docker compose up -d
```

La rotación de logs limita el almacenamiento de Docker. La retención mantiene compactos los registros operativos, conservando la información necesaria para no repetir eventos. El archivo SQLite puede conservar espacio libre interno después de una limpieza; no ejecutes `VACUUM` desde otro proceso mientras el servicio está escribiendo sin planificar el mantenimiento.

La construcción y la conectividad de tu despliegue solo quedan comprobadas cuando ejecutes estos pasos en tu endpoint. El estado de verificación entregado con el proyecto distingue las pruebas locales de esos pasos pendientes.
