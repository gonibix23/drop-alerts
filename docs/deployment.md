# Despliegue en Docker y Portainer sobre Proxmox

## 1. Preparar el acceso al registro de imágenes

Portainer debe gestionar un Docker Engine en una VM o LXC con conectividad saliente HTTPS, DNS y almacenamiento persistente. Este proyecto no configura Proxmox ni modifica el host. La instalación de Docker dentro de un LXC depende de su configuración de permisos y aislamiento; utiliza un entorno Docker que ya funcione.

El stack descarga la imagen privada `ghcr.io/gonibix23/drop-alerts:main`. GitHub Actions la construye y publica después de superar las pruebas de `main`, para Linux amd64 y arm64. Antes del primer despliegue, comprueba en la pestaña **Actions** del repositorio que haya terminado correctamente la publicación. Tener el código en GitHub o haber construido una imagen en el runner no basta: la imagen debe estar publicada en el registro.

En GitHub crea un **personal access token (classic)** con permiso `read:packages` y acceso al paquete privado. Si el token está sujeto a SSO o políticas de una organización, autorízalo también allí. Configúralo directamente en Portainer; no lo guardes en `.env`, en el repositorio, en capturas ni en el chat. GitHub documenta este método en [autenticación de Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-to-the-container-registry).

En Portainer, abre **Registries → Add registry → Custom registry** y completa:

| Campo | Valor |
| --- | --- |
| Nombre | `GitHub Container Registry` |
| URL | `ghcr.io` |
| Authentication | Activado |
| Username | `gonibix23` |
| Password | El token classic con `read:packages` |

Guarda el registro y permite su acceso al entorno Docker y a tu usuario si tu versión de Portainer lo requiere. Selecciónalo al desplegar el stack. Véase [añadir un registro personalizado en Portainer](https://docs.portainer.io/admin/registries/add/custom). La autenticación para leer el repositorio Git y la autenticación para descargar imágenes son independientes; configurar una no configura la otra. La contraseña de tu cuenta de GitHub no sustituye al token del registro.

Para utilizar Docker Compose desde una terminal Bash, autentica Docker sin poner el token en la línea de comandos ni en el historial:

```bash
read -r -s -p 'Token de GitHub (read:packages): ' DROP_ALERTS_GHCR_TOKEN
printf '\n'
printf '%s' "$DROP_ALERTS_GHCR_TOKEN" | docker login ghcr.io --username gonibix23 --password-stdin
unset DROP_ALERTS_GHCR_TOKEN
```

Después descarga el proyecto y la imagen:

```sh
git clone https://github.com/gonibix23/drop-alerts.git
cd drop-alerts
cp .env.example .env
# Editar .env y configurar DISCORD_WEBHOOK_URL.
docker compose pull
docker compose up -d
```

`docker-compose.yml` referencia la imagen publicada y no necesita construirla desde el editor de Portainer. Conserva `DROP_ALERTS_IMAGE=ghcr.io/gonibix23/drop-alerts:main` o elimina esa variable para usar el valor predeterminado del Compose. Una variable antigua `DROP_ALERTS_IMAGE=drop-alerts:1.0.0` tiene prioridad sobre ese valor y provocará que Docker busque de nuevo la imagen local antigua.

La imagen final contiene el paquete instalado y la configuración predeterminada, sin pruebas, documentación ni herramientas de compilación. Ejecuta como UID/GID `10001:10001`, con raíz de solo lectura y `/tmp` temporal. SQLite y el latido se escriben en `/data`. La fase de construcción exige ruedas binarias para las dependencias: si una arquitectura no dispone de ellas, falla explícitamente en vez de añadir compiladores a la imagen.

Las dependencias tienen rangos acotados en `pyproject.toml`; la base `python:3.12-slim` y esos rangos pueden resolver versiones distintas al reconstruir. No se entrega un bloqueo de versiones o digest que no se haya comprobado. Para una publicación reproducible, fija el digest de la base y genera en CI un bloqueo de dependencias con hashes verificado para tus arquitecturas, guarda el inventario de la imagen construida y despliega por digest o etiqueta inmutable. Construir una vez y distribuir esa misma imagen evita que cada host resuelva dependencias por separado.

El 21 de octubre de 2026 se completó una descarga de las dependencias de ejecución y sus dependencias transitivas usando solo ruedas binarias para CPython 3.12 en Linux `manylinux_2_17_x86_64` y `manylinux_2_17_aarch64`. Se resolvieron httpx 0.28.1, Beautiful Soup 4.15.0, Pydantic 2.14.1 y pydantic-core 2.50.1. Esto comprueba la disponibilidad de esos artefactos para ambas arquitecturas; no ejecuta las ruedas ni sustituye una construcción y prueba de la imagen Docker. El motor Docker local no estaba disponible para esa construcción.

## 2. Crear el stack

1. En Portainer selecciona el endpoint Docker adecuado.
2. Abre **Stacks → Add stack**, escribe `drop-alerts` y elige **Web editor**.
3. Pega el contenido de `docker-compose.yml`.
4. Selecciona el registro `ghcr.io` configurado en el paso anterior. Añade las variables de `.env.example` en **Environment variables** o carga un archivo `.env` local si tu versión ofrece esa opción. Como mínimo configura `DISCORD_WEBHOOK_URL`; revisa que `DROP_ALERTS_IMAGE` apunte a `ghcr.io/gonibix23/drop-alerts:main`.
5. Revisa `LLM_BASE_URL` y `LLM_MODEL`; añade `LLM_API_KEY` solamente si el servidor la exige.
6. Pulsa **Deploy the stack**. No necesitas puertos publicados ni otro servicio.
7. Abre **Containers → drop-alerts → Logs** y comprueba el estado de salud.

El volumen se llama normalmente `<nombre_del_stack>_drop_alerts_data`. No borres el volumen al recrear o actualizar el stack. El primer arranque registra la situación actual silenciosamente. `BOOTSTRAP_MODE=notify` permite avisar también de los elementos presentes en la primera comprobación; puede generar muchas notificaciones.

### Alternativa: construir localmente

Si prefieres construir la imagen en el host Docker, ejecuta allí `docker build -t drop-alerts:local .` desde el proyecto. En las variables de Portainer establece `DROP_ALERTS_IMAGE=drop-alerts:local` y desactiva cualquier opción que fuerce descargar esa imagen. Debe estar en el mismo Docker Engine que usa el stack; una imagen construida en otro host o en GitHub Actions no aparece automáticamente en ese Engine.

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
2. Espera a que las pruebas y la publicación de la nueva versión de `main` terminen correctamente en GitHub Actions.
3. Conserva `ghcr.io/gonibix23/drop-alerts:main` y pulsa **Update the stack**, activando la descarga de la nueva imagen. Para fijar una revisión concreta, usa `ghcr.io/gonibix23/drop-alerts:sha-<SHA_COMPLETO_DEL_COMMIT>` o el digest publicado por el flujo.
4. Comprueba logs, salud y `status`.

Cada publicación conserva además la etiqueta `sha-` seguida del SHA completo de su commit. `main` se actualiza con cada publicación correcta; usa una etiqueta de commit o un digest para poder repetir exactamente la elección de imagen. Para volver a una versión anterior cambia a su etiqueta o digest publicado. Comprueba antes la compatibilidad de su esquema de base de datos; si no es compatible, restaura también la copia de seguridad correspondiente con el servicio detenido. No ejecutes dos versiones contra el mismo archivo SQLite. Si utilizas la alternativa local, reconstruye la imagen en el mismo host y no fuerces una descarga del registro.

## 6. Copias de seguridad y mantenimiento

Para una copia sencilla, detén el contenedor, copia el volumen completo y vuelve a arrancar. Incluye los archivos `-wal` y `-shm` si existen; copiar solamente el `.db` mientras se está escribiendo puede perder transacciones. También puedes utilizar la API de backup de SQLite para una copia en caliente.

Con el stack en marcha:

```sh
docker compose logs --tail=100
docker compose exec drop-alerts python -m drop_alerts status
docker stats --no-stream
docker image inspect ghcr.io/gonibix23/drop-alerts:main --format '{{.Size}}'
```

La limpieza por retención se ejecuta automáticamente cada día. Para forzarla manualmente, detén el servicio antes de iniciar un proceso de mantenimiento contra su volumen:

```sh
docker compose stop drop-alerts
docker compose run --rm drop-alerts prune
docker compose up -d
```

La rotación de logs limita el almacenamiento de Docker. La retención mantiene compactos los registros operativos, conservando la información necesaria para no repetir eventos. El archivo SQLite puede conservar espacio libre interno después de una limpieza; no ejecutes `VACUUM` desde otro proceso mientras el servicio está escribiendo sin planificar el mantenimiento.

La construcción y la conectividad de tu despliegue solo quedan comprobadas cuando ejecutes estos pasos en tu endpoint. El estado de verificación entregado con el proyecto distingue las pruebas locales de esos pasos pendientes.
