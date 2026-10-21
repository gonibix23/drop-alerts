# Verificación del servidor de IA

Fecha del intento: 21 de octubre de 2026. Se intentaron peticiones GET de solo lectura a:

- `https://llama.gonibix23.com/`
- `https://llama.gonibix23.com/v1/models`
- `https://llama.gonibix23.com/api/tags`

El primer intento desde este entorno Windows quedó bloqueado por permisos de socket (`WinError 10013`). La herramienta de navegación tampoco pudo abrir la raíz del servidor. Se repitió la comprobación con permiso de red: tanto la raíz como `/v1/models` respondieron **HTTP 401 Unauthorized**; `/api/tags` agotó el tiempo durante el saludo TLS (12 segundos). No se envió una petición de generación al requerirse autenticación. El servidor/proxy es accesible desde el entorno de desarrollo, pero esas respuestas no permiten identificar la API ni comprobar el modelo. El 401 podría proceder del proxy antes de alcanzar el servidor de inferencia.

El cliente implementa el contrato documentado de chat compatible con OpenAI: `POST {LLM_BASE_URL}/chat/completions`, `messages`, `model`, `temperature`, `max_tokens`, `response_format: {type: json_object}`, y respuesta `choices[0].message.content`. La configuración inicial usa la base solicitada `https://llama.gonibix23.com/v1` y el modelo solicitado `qwen3:8b-q4_k_m`. **La compatibilidad real, la existencia de ese identificador y los requisitos de autenticación deben comprobarse desde el host Docker antes del despliegue.** No se han usado proveedores externos como alternativa.

La clave opcional se envía únicamente como `Authorization: Bearer ...`; no se registra. Se conserva la verificación TLS. No se siguen redirecciones al enviar la clave. Si el proxy expone otra ruta, configura `LLM_BASE_URL`; si usa autenticación distinta de Bearer, debe adaptarse el cliente explícitamente.

Las tareas independientes son `classification`, `extraction`, `relevance`, `semantic_match`, `change` y `summary`. Se validan esquemas estrictos, límites, valores y citas literales de evidencia. Todos los resultados son propuestas semánticas: disponibilidad, precio, identidad, URLs consultadas y reglas de notificación siguen bajo control determinista. Una cita literal acredita procedencia del texto, no la veracidad de la afirmación.

Los errores producen fallback local, con reintentos acotados, una sola reparación de JSON y una pausa de cinco minutos tras tres análisis fallidos consecutivos. La caché incluye tarea, contenido truncado, endpoint, modelo, esquema e instrucciones. Los esquemas y el cliente se prueban con respuestas simuladas; las pruebas no llaman al servidor real.

## Comprobar con tu credencial desde Portainer

Configura la ruta y la autenticación reales en el stack. Dentro del contenedor ejecuta:

```sh
python -m drop_alerts doctor
python -m drop_alerts check-llm
```

`doctor` hace GET a la lista de modelos y comprueba si aparece el identificador configurado; no genera texto. `check-llm` solicita explícitamente una clasificación breve de un texto de prueba mediante el cliente real, con sus límites y validación. Requiere `LLM_ENABLED=true`. Usa SQLite en memoria y no envía mensajes a Discord ni modifica el estado del monitor. Puede hacer los reintentos acotados configurados y una reparación de formato; no imprime claves ni la respuesta completa. Una salida `analysis_valid=true` confirma una respuesta compatible con el esquema en esa prueba, no la exactitud futura del modelo. Este segundo paso sigue pendiente de ejecutar con una credencial válida.
