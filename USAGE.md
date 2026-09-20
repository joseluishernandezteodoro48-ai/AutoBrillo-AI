# AutoBrillo AI · Guía de uso (listo para producción)

Versión: **v7.3**

## 1. Despliegue en Render

1. Sube el código a GitHub y conecta el repo en Render (Blueprint con `render.yaml`).
2. Configura **secretos** en el dashboard (nunca en el repo):

| Variable | Descripción |
|----------|-------------|
| `ML_CLIENT_ID` | App ID de Mercado Libre |
| `ML_CLIENT_SECRET` | Secret de la app |
| `ML_REDIRECT_URI` | Ej: `https://TU-SERVICIO.onrender.com/oauth/mercadolibre/callback` |
| `AUTOBRILLO_TOKEN_KEY` | Clave Fernet (32 bytes url-safe). Generar: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `AUTOBRILLO_ADMIN_KEY` | Clave para endpoints admin |
| `AUTOBRILLO_WEBHOOK_KEY` | Clave para webhooks |
| `ML_DEFAULT_CATEGORY_ID` | Categoría ML válida (ej. `MLM1055`) — **obligatoria para publicar** |

3. Confirma que la base `autobrillo-ai-db` esté Available.
4. `AUTOBRILLO_DRY_RUN` debe quedar en `true` hasta validar todo.

## 2. Conectar Mercado Libre

1. Abre `https://TU-SERVICIO.onrender.com/oauth/mercadolibre/start`
2. Autoriza con la cuenta vendedor.
3. Debe mostrar: “Mercado Libre conectado correctamente”.

Prueba:
```bash
curl -H "X-Admin-Key: TU_ADMIN_KEY" https://TU-SERVICIO/api/mercadolibre/me
```

## 3. Flujo comercial (dry-run)

```bash
# 1) Buscar y analizar
curl -X POST https://TU-SERVICIO/api/brillo \
  -H "Content-Type: application/json" \
  -d '{"command":"busca 5 auriculares"}'

# 2) Ver plan de Tygo
curl https://TU-SERVICIO/api/plan

# 3) Ciclo (prepara páginas y listings; NO publica si dry_run=true)
curl -X POST https://TU-SERVICIO/api/cycle

# 4) Preparar payload de un producto
curl -X POST https://TU-SERVICIO/api/listing/prepare \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: TU_ADMIN_KEY" \
  -d '{"product_name":"NOMBRE_EXACTO_DEL_PRODUCTO","category_id":"MLM1055"}'
```

## 4. Publicar de verdad (cuando estés listo)

Orden obligatorio:

1. Valida OAuth + `/api/mercadolibre/me`.
2. Configura `ML_DEFAULT_CATEGORY_ID` (o pásalo en cada request).
3. Habilita permiso sales:
```bash
curl -X POST https://TU-SERVICIO/api/permissions \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: TU_ADMIN_KEY" \
  -d '{"name":"sales","enabled":true}'
```
4. En Render: `AUTOBRILLO_DRY_RUN=false` (y redeploy).
5. Publica un producto:
```bash
curl -X POST https://TU-SERVICIO/api/listing/publish \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: TU_ADMIN_KEY" \
  -d '{"product_name":"NOMBRE_EXACTO","category_id":"MLM1055","quantity":1}'
```

Si dry_run sigue en true, la respuesta será `status: dry_run_blocked` con el payload preparado (no se envía a ML).

## 5. Órdenes y webhooks

```bash
# Listar órdenes (requiere OAuth + admin)
curl -H "X-Admin-Key: TU_ADMIN_KEY" https://TU-SERVICIO/api/mercadolibre/orders

# Webhook (configura la URL en el panel de ML)
# Header: X-Autobrillo-Webhook-Key: TU_WEBHOOK_KEY
POST /webhooks/mercadolibre
```

## 6. Proveedores

Edita `suppliers.json` o apunta `AUTOBRILLO_SUPPLIER_FEED` a tu feed.

Solo productos con `verified: true` y `cost > 0` marcan `cost_known=true`.

## 7. Kill switch de emergencia

```
AUTOBRILLO_KILL_SWITCH=true
```
Detiene ciclos y ejecuciones del agente.

## 8. Health check

```bash
curl https://TU-SERVICIO/health
```

Esperado:
- `status: ok`
- `version: v7.3`
- `mercadolibre_configured: true` (tras OAuth)
- `business_storage: postgresql` (si DATABASE_URL resuelve)

## Seguridad

- Nunca desactives dry-run sin haber probado OAuth y un listing de prueba.
- No subas secretos al repo.
- Rota `AUTOBRILLO_TOKEN_KEY` / admin / webhook si se exponen.
