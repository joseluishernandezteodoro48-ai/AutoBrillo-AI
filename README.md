# AutoBrillo AI · Brillo + Tygo

Sistema de automatización de ventas con inteligencia local (Tygo) e interfaz de órdenes (Brillo), integrado con Mercado Libre.

**Versión:** 7.3

## Qué hace

1. Busca productos en Mercado Libre (descubrimiento público).
2. Compara con costos de proveedor verificados (`suppliers.json`).
3. Calcula margen, riesgo y decide prioridades (Tygo).
4. Prepara listings y, si lo autorizas, publica en Mercado Libre.
5. Recibe webhooks y consulta órdenes.

Por defecto corre en **dry-run**: no publica ni mueve dinero hasta que configures permisos y desactives el modo seguro.

## Inicio rápido (Render)

1. Conecta este repo a Render (Blueprint → `render.yaml`).
2. Configura secretos: `ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ML_REDIRECT_URI`, `AUTOBRILLO_TOKEN_KEY`, `AUTOBRILLO_ADMIN_KEY`, `AUTOBRILLO_WEBHOOK_KEY`.
3. Opcional: `ML_DEFAULT_CATEGORY_ID` (categoría válida de tu sitio).
4. Abre `/oauth/mercadolibre/start` y autoriza.
5. Sigue **USAGE.md** para el flujo completo.

## Local

```bash
pip install -r requirements.txt
export AUTOBRILLO_DRY_RUN=true
python -m uvicorn main:app --reload --port 8000
curl http://localhost:8000/health
```

## Documentación

- [USAGE.md](USAGE.md) — guía de uso y puesta en producción
- [SECURITY.md](SECURITY.md) — principios de seguridad
- [FIXES.md](FIXES.md) — correcciones aplicadas en v7.3

## Seguridad

- `AUTOBRILLO_DRY_RUN=true` por defecto
- `AUTOBRILLO_KILL_SWITCH` detiene el agente
- Endpoints admin y webhooks con claves
- Tokens OAuth cifrados (Fernet)
- Rate limiting y redacción de secretos en errores

## Licencia / uso

Código de automatización comercial. No ejecuta cobros ni publicaciones sin configuración explícita y desactivación de dry-run.
