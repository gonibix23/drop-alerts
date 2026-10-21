# Procedencia de las respuestas

Respuestas HTTP reales descargadas el 21 de octubre de 2026 mediante urllib, TLS validado y User-Agent `drop-alerts/1.0`.

- `secret-lair-home.html`: extractos literales de https://secretlair.wizards.com/eu/ (200, 517709 bytes originales): enlaces a productos, controles ng-init, propiedades de configuración públicas y JSON de anuncios. Se omiten analítica, scripts ajenos y formularios.
- `secret-lair-product.html`: h1 y JSON-LD literal de https://secretlair.wizards.com/eu/product/1253140 (200, 480734 bytes originales).
- `secret-lair-catalog.json`: respuesta JSON completa del endpoint público declarado por la tienda: `https://storesearch.eu.scalefast.com/StoreSearch?userID=10751401&locale=en_REU&currency=EUR&sort=featured&offset=0&count=20&env=prod&crit=ALL&filters=feedID%3A73824` (200, 23881 bytes originales). Solo datos públicos de catálogo.
- `magic-news.html`: bloques de enlaces/artículos de https://magic.wizards.com/en/news (200, 716299 bytes originales), sin analítica ni navegación global.
- `magic-article.html`: article literal de https://magic.wizards.com/en/news/announcements/reality-fracture-secret-lair-bundle-delayed (200, 163547 bytes originales).
- `secret-lair-thing.html`: h1 y JSON-LD literal del cuerpo HTTP real de https://secretlair.wizards.com/eu/product/1254818/festival-in-a-box-atlanta-2026 conservado en SQLite durante la comprobación ampliada. Usa `@type=Thing`, nombre y descripción, sin Offer; no prueba precio ni disponibilidad.

Las pruebas de fallos alteran deliberadamente estos datos o usan respuestas sintéticas y no prueban la disponibilidad futura de las fuentes.
