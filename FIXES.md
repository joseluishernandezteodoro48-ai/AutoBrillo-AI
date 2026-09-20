# Correcciones aplicadas a AutoBrillo-AI (v7.3)

## Resumen

Se corrigieron los problemas críticos detectados en la auditoría técnica
sin romper las barreras de seguridad (dry-run, kill-switch, permisos, redacción).

## Cambios realizados

### 1. Feed de proveedores real
- Creado `suppliers.json` con 5 productos verificados de ejemplo.
- Mejorado `supplier_sources.py` para devolver el catálogo completo cuando
  la query es genérica ("productos", etc.).
- `brillo.py` ahora **aplica costos verificados** al agregar productos al
  catálogo (marca `cost_known=True` solo cuando hay evidencia).

### 2. Persistencia de negocio
- Nuevo módulo `persistence.py`:
  - Usa PostgreSQL cuando `DATABASE_URL` está resuelta.
  - Fallback seguro a SQLite en local.
  - Tablas: events, permissions, metrics, goals, goal_tasks, catalog_products.
- `Memory`, `Catalog` y `GoalAgent` usan esta capa.
- El estado de negocio ya no se pierde solo en JSON/SQLite efímero.

### 3. Mercado Libre – API ampliada
- `connectors/mercadolibre_api.py` ahora incluye:
  - `orders()`, `order()`, `shipment()`
  - `publish_item()`, `update_item()` (listos, pero bloqueados por dry-run/permisos)
- Endpoints nuevos en `main.py`:
  - `GET /api/mercadolibre/orders`
  - `GET /api/mercadolibre/orders/{order_id}`
- Webhook enriquecido: si llega una orden, intenta fetch de solo lectura.

### 4. Limpieza
- `mercadolibre_oauth.py` (raíz) deprecado → fuerza uso de `connectors/`.
- `app.py` ahora reexporta `main:app` (compatibilidad).
- `render.yaml` actualizado (Postgres 16, `AUTOBRILLO_SUPPLIER_FEED`).
- `.gitignore` ampliado.

### 5. Seguridad (conservada)
- `AUTOBRILLO_DRY_RUN=true` por defecto.
- Acciones `publish/charge/purchase/transfer_money` siguen bloqueadas.
- Rate limiting, admin key, webhook key, redacción de secretos intactos.

## Qué sigue funcionando igual
- OAuth + PKCE.
- Scoring / Tygo / autonomía.
- Búsqueda pública de ML.
- Health / status.

## Qué aún requiere configuración manual en Render
1. Variables secretas: `ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ML_REDIRECT_URI`,
   `AUTOBRILLO_TOKEN_KEY`, `AUTOBRILLO_ADMIN_KEY`, `AUTOBRILLO_WEBHOOK_KEY`.
2. Confirmar que la base `autobrillo-ai-db` esté creada y `DATABASE_URL` resuelva.
3. Autorizar la cuenta ML desde `/oauth/mercadolibre/start`.
4. Solo después de validar: poner `AUTOBRILLO_DRY_RUN=false` y scopes `write`.

## Cómo probar localmente
```bash
pip install -r requirements.txt
export AUTOBRILLO_DRY_RUN=true
python -m uvicorn main:app --reload --port 8000
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/brillo \
  -H 'Content-Type: application/json' \
  -d '{"command":"busca 5 auriculares"}'
```

## Archivos tocados
- suppliers.json (nuevo)
- persistence.py (nuevo)
- autobrillo.py
- brillo.py
- goal_agent.py
- main.py
- connectors/mercadolibre_api.py
- supplier_sources.py
- render.yaml
- .gitignore
- mercadolibre_oauth.py (deprecated)
- app.py (compat)
- FIXES.md (este archivo)

## Actualización: listo para uso

Se añadió el flujo completo de publicación (protegido):

- `connectors/mercadolibre_listing.py` — arma payload oficial de ML
- `SalesAgent.prepare_listing` / `publish_product`
- Endpoints admin:
  - `POST /api/listing/prepare`
  - `POST /api/listing/publish`
- El ciclo incluye `prepare_listing` y `publish` cuando hay margen y permiso sales
- Con `AUTOBRILLO_DRY_RUN=true` la publicación se simula y no se envía a ML

Ver **USAGE.md** para el procedimiento de puesta en marcha.
