# Investigación de El Cartón Peleón

Comprobaciones realizadas el **21 de noviembre de 2026** mediante peticiones HTTP reales con `httpx`, TLS verificado y el identificador público `drop-alerts/1.4.3 (self-hosted source monitoring)`. No se han utilizado navegador, cuentas, carrito, formularios de compra, IA ni Discord. Las capturas completas de investigación permanecen en `work/research/carton-peleon/`, excluido de Git; las pruebas incluyen fragmentos pequeños de las respuestas reales sin tokens CSRF.

## Descubrimiento ligero

- [Portada](https://www.elcartonpeleon.com/): HTTP 200, HTML renderizado en servidor con enlaces al catálogo.
- [robots.txt](https://www.elcartonpeleon.com/robots.txt): HTTP 200. Declara `Sitemap: https://www.elcartonpeleon.com/sitemap.xml`; la respuesta consultada no contiene restricciones adicionales.
- [Sitemap](https://www.elcartonpeleon.com/sitemap.xml): HTTP 200, XML público de aproximadamente 255 KB. Sirve como evidencia de descubrimiento; no se descarga entero en cada ronda.
- [Juegos de Cartas](https://www.elcartonpeleon.com/shop/category/juegos-de-cartas-204?order=publish_date+desc) y [Accesorios](https://www.elcartonpeleon.com/shop/category/accesorios-160?order=publish_date+desc): HTTP 200. La opción visible «Llegadas más recientes» enlaza exactamente `?order=publish_date+desc`. Se utiliza ese enlace observado, sin adivinar parámetros.
- La paginación pública utiliza `/page/2?order=publish_date+desc` y los siguientes números. Se observaron 21 tarjetas por página, 36 páginas de juegos y 24 de accesorios. Estas cantidades son una observación de ese día, no límites permanentes del programa.
- No se identificó un feed RSS anunciado en las respuestas consultadas. El HTML y la consulta de stock descrita abajo hacen innecesario instalar un navegador o intentar endpoints de catálogo privados.

El HTML identifica Odoo: las tarjetas reales son `#o_wsale_products_grid form.oe_product_cart`, con título en `h2.o_wsale_products_item_title a`. Los identificadores se corroboran con `product_template_id`, `product_id` y los atributos de la lista de deseos. Se leen esos atributos; no se pulsa ni modifica la lista de deseos.

Los enlaces de catálogo añaden una categoría contextual a `/shop/<slug>-<id>`. Las fichas y su JSON-LD publican la ruta canónica sin esa categoría. El adaptador normaliza únicamente ese patrón observado, admite slugs Unicode y restringe origen/rutas/parámetros. No sigue enlaces de cuenta, carrito, búsqueda libre ni destinos externos.

## Identidad, categorías y ámbito

El producto solicitado tiene **plantilla 19822 y variante 23219**. El identificador estable guardado es `variant:23219`; el número final de la URL identifica la plantilla. SKU/EAN son referencias comerciales independientes. Los idiomas o ediciones vendidos en fichas separadas conservan sus identificadores propios.

Se exige una ficha principal única (`section#product_detail` y `#product_details #o_wsale_product_details_content.js_product.js_main_product`), título concordante, Product JSON-LD único y oferta individual. El selector real `.js_add_cart_variants` está vacío y su contrato de exclusiones tiene contenedores vacíos. Una ficha con opciones, combinaciones múltiples, identidades contradictorias o contrato incompleto se rechaza conservando el estado anterior; no se combinan metadatos agregados de variantes.

El ámbito procede de las **migas de pan de la ficha**, nunca del menú global: raíz 204 para TCG y 160 para accesorios. Los accesorios requieren además una denominación de material para cartas, como fundas, tapete, deckbox o archivador. Se excluyen figuras independientes, entradas, torneos, tarjetas regalo, naipes, tarot y accesorios de rol sin relación verificable con cartas. Un producto de sobres que incluye una figura sigue siendo un producto de cartas.

Las categorías específicas verificadas permiten etiquetar Magic (113), One Piece (124), Pokémon (139), Riftbound (166), Lorcana (119), Digimon (144), Star Wars Unlimited (129), Yu-Gi-Oh! (149), Cyberpunk (192), Dragon Ball (179), Palworld (191), UniVersus (201) y Weiß Schwarz (206). Una funda genérica no se asigna arbitrariamente a un juego. La selección global `ENABLED_TCGS` sigue decidiendo qué juegos notifican.

La etiqueta de mercado ES se apoya en el [aviso legal](https://www.elcartonpeleon.com/aviso-legal), con domicilio de EL CARTÓN PELEÓN S.L. en Terrassa, y en [envíos y devoluciones](https://www.elcartonpeleon.com/envios-y-devoluciones), que contempla península española y condiciones específicas para islas y otras zonas. Ambas páginas devolvieron HTTP 200. `region=EU` expresa esa ubicación; no promete envíos a todos los países de la UE. El idioma español de la web no se usa por sí solo para deducir el mercado ni el idioma comercial del producto.

## Estados y precio público

La semilla [Commander Warhammer 40K](https://www.elcartonpeleon.com/shop/commander-pack-4-mazos-ingles-magic-the-gathering-warhammer-40k-deck-set-19822) devolvió HTTP 200 y el aviso visible `.cp-dispo-prox` decía **«Próximamente disponible para reservar»**. Por ello se guarda `UPCOMING`: todavía no acredita que puedan hacerse reservas ni que existan unidades para envío inmediato.

Su JSON-LD publicaba `InStock` y precio `0.0`, pero la zona `.product_price` estaba oculta con `d-none`; el importe 289,99 aparecía en un bloque exclusivo del editor. **Ninguno de esos valores se presenta como precio público ni como producto gratuito.** La ficha también mostraba una estimación 31/01/2027 junto al aviso **«FECHA POR DETERMINAR»**. Se conserva el aviso de incertidumbre y se omite esa fecha numérica del texto para el analizador de lanzamientos; no se anuncia como fecha confirmada.

Otras respuestas reales utilizadas como pruebas:

- Fundas Dragón Magenta, plantilla 19839/variante 23236: importe visible actual 4,49 EUR, frente a precio tachado/editorial 4,99. El HTML estático carecía de stock positivo explícito y por sí solo se clasifica `UNKNOWN`. La consulta pública de lectura confirmó posteriormente existencias.
- Tapete Mox Emerald, 19836/23233: chip visible «Reserva», 20,99 EUR; se clasifica `UPCOMING`, aunque los metadatos genéricos digan `InStock`.
- Spiderman Sobre Play ES, 17644/17644: aviso `.cp-dispo-agot` «Agotado online», JSON-LD `OutOfStock` y unidades solo en tienda física. Estado `UNAVAILABLE` para el canal web; la existencia en Terrassa no es reposición online.
- Deckbox Yuna, 19044/20887: «Reserva» y un aviso de unidades; la reserva sigue prevaleciendo sobre una afirmación de disponibilidad inmediata.

Los importes actuales se aceptan únicamente si el precio visible `.oe_price .oe_currency_value` y la oferta JSON-LD individual coinciden y expresan EUR. Se ignoran precio tachado, importe editorial, bloques ocultos, precio cero/ausente y señales o depósitos. Un precio contradictorio invalida esa ficha. La API de stock **no aporta ni reemplaza el precio que se muestra en las alertas**.

## Consulta pública de existencias

El JavaScript público enlazado por las fichas (`/web/assets/1/.../web.assets_frontend_lazy.min.js`, ruta versionada por la tienda) mostró una llamada de lectura a **`/website_sale/get_combination_info`**. El código utiliza `is_storable`, `free_qty`, `cart_qty`, `allow_out_of_stock_order` y, si existe, `max_combo_quantity`; también bloquea la venta cuando `prevent_zero_price_sale` es verdadero. No se ejecutó el JavaScript: se leyó el recurso enlazado para comprobar el contrato.

Se verificó HTTP 200 mediante una petición POST JSON-RPC de lectura sin sesión, cookies ni autenticación:

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "id": 1,
  "params": {
    "product_template_id": 19839,
    "product_id": 23236,
    "combination": [],
    "add_qty": 1,
    "uom_id": null,
    "context": {}
  }
}
```

La respuesta real de 923 bytes incluyó ambas identidades, nombre coincidente, `is_combination_possible=true`, `is_storable=true`, `allow_out_of_stock_order=false`, `prevent_zero_price_sale=false`, `free_qty=18` y `cart_qty=0`. La cantidad es una observación puntual de investigación, no una garantía actual. Esta ruta consulta la combinación; **no añade unidades al carrito**. No se invocan rutas de compra o de suscripción.

El adaptador consulta esta RPC cuando el HTML no permite verificar disponibilidad, o cuando hay un aviso de unidades pero el precio público está oculto o sin confirmar. Los avisos explícitos de producto próximo, reserva y agotado online conservan prioridad y evitan consultas innecesarias. Se validan sobre JSON estricto el sobre, las identidades enteras, título, combinación y tipos booleanos/numéricos finitos. Unidades positivas verificadas permiten `AVAILABLE`; sin unidades y sin pedidos fuera de stock, `UNAVAILABLE`; pedidos fuera de stock, productos no almacenables o bloqueo de venta se mantienen `UNKNOWN`.

`SourceHTTP.post_json` comparte con GET la espera por host, límites de respuesta, tiempos de espera, reintentos y pausas HTTP 429/503. No cachea existencias ni sigue redirecciones de POST. Error de red, formato o identidad en la RPC descarta únicamente esa ficha y conserva la versión anterior; no transforma una caída de API en una falsa reposición o indisponibilidad.

## Ventanas, persistencia y verificación

La semilla solicitada se consulta **primero en cada ronda**, también con `max_items=1`. Tiene un inventario de arranque independiente: su primera recuperación puede registrarse silenciosamente aunque el catálogo ya se haya inicializado y el proceso se haya reiniciado.

Por defecto se consultan dos páginas por catálogo —la primera ordenada por novedades y una ventana rotatoria de archivo—, hasta 12 fichas incluyendo la semilla. Los cursores se guardan en SQLite. Las cuotas alternan novedades y rotación, y las fichas ya conocidas siguen revisándose cuando salen de la portada. Cada petición dispone de un máximo de 20 segundos dentro de un presupuesto global de 90. Un fallo parcial no borra estados ni demuestra desaparición; las tarjetas incompletas no cierran su inventario de descubrimiento.

La primera visita a cada ventana registra silenciosamente sus identidades aunque las fichas se procesen en rondas posteriores. Esto evita avisos históricos diferidos tras reinicios. Implica que el primer recorrido del archivo forma parte de la línea base; no ofrece garantía de captura de todos los movimientos anteriores a esa visita. Catálogos grandes y presupuestos finitos pueden retrasar revisiones de productos antiguos: no se promete cobertura instantánea ni un barrido total cada cinco minutos.

Pruebas reales con `SourceHTTP`, SQLite en memoria, `LLM_ENABLED=false` y webhook vacío:

- Ronda con valores por defecto: **12 fichas, 4 páginas de catálogo, 0 errores**, 4,63 segundos en este entorno. La semilla fue la primera y quedó `UPCOMING` sin precio ni fecha confirmada. La ingesta inicial generó 0 notificaciones pendientes; reingerir el mismo resultado generó 0 eventos nuevos.
- Ficha normal 19839/23236: GET real dejó `UNKNOWN`; `SourceHTTP.post_json` y el validador confirmaron `AVAILABLE`, manteniendo exclusivamente el precio público 4,49 EUR. Ingesta silenciosa: 0 notificaciones pendientes, repetición: 0 eventos nuevos.

Los tiempos anteriores son mediciones locales puntuales, no estimaciones de rendimiento de Proxmox. Las pruebas automatizadas usan exclusivamente capturas y servicios simulados; no requieren conexión al servidor de IA ni envían mensajes a Discord. No se ha comprobado el despliegue de esta fuente desde el Portainer del usuario.
