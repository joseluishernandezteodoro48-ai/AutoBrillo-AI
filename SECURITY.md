# Seguridad de AutoBrillo AI

## Principios

- Los secretos y credenciales deben permanecer fuera del código fuente.
- Las operaciones administrativas y financieras deben estar protegidas por autenticación y autorización del servidor.
- Las publicaciones, cobros, compras y transferencias no se ejecutan desde texto del usuario sin pasar por controles y conectores oficiales.
- `AUTOBRILLO_DRY_RUN` permanece activado hasta validar de forma independiente cada integración.
- `AUTOBRILLO_KILL_SWITCH` debe permitir detener operaciones del agente.
- Los webhooks deben autenticarse antes de procesar acciones.
- Los errores y logs deben redactar tokens, contraseñas y claves.
- Las operaciones críticas deben ser auditables e idempotentes.

## Variables sensibles

Configurar en el gestor de secretos de Render, nunca en GitHub como texto del repositorio:

- `ML_CLIENT_ID`
- `ML_CLIENT_SECRET`
- `ML_REDIRECT_URI`
- `AUTOBRILLO_TOKEN_KEY`
- `AUTOBRILLO_ADMIN_KEY`
- `AUTOBRILLO_WEBHOOK_KEY`

No reutilizar ni publicar credenciales que hayan sido expuestas anteriormente.

## Respuesta ante incidentes

Si una credencial se expone, revocarla/rotarla en el proveedor correspondiente y sustituirla en Render antes de volver a activar operaciones protegidas.
