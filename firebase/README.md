# Firebase: configuración privada por usuario

Estado: configuración pública incorporada; `SHARPIE_FIREBASE_ENABLED=false` hasta verificar Authentication y reglas. Comprobación del 15/09/2026: API de proyecto responde correctamente; `azrocse.github.io` falta en los dominios autorizados; Firestore rechaza la lectura anónima de preferencias. Esto no verifica todavía el aislamiento entre cuentas autenticadas.

Proyecto elegido: `sharpie-dashboard`. El sitio permanece en GitHub Pages.

1. Configuración del proyecto → Tus apps: registrar una app web si no existe. Copiar solo el objeto público `firebaseConfig` a `firebase-config.js`. Nunca incluir claves de cuentas de servicio.
2. Authentication → Método de acceso: habilitar Google y Correo electrónico/contraseña. Configurar el correo de soporte del proveedor Google. El acceso por enlace de correo no es necesario.
3. Authentication → Configuración → Dominios autorizados: agregar `azrocse.github.io` y cualquier dominio propio que publique este dashboard.
4. Firestore: comprobar que existe la base `(default)`. Revisar sus reglas actuales antes de incorporar `firestore.rules`. Las reglas adjuntas permiten leer y modificar solo las preferencias del UID autenticado y no autorizan ninguna otra ruta. No reemplazar reglas de otros sistemas sin revisión.
5. Verificar con dos cuentas reales: acceso por Google y correo, edición y cambio de nombre, filtros en otro dispositivo, cierre de sesión y aislamiento entre usuarios.

Datos:

- `users/{uid}/settings/dashboard`: parámetros, orden, switches, tema y vista.
- `users/{uid}/settings/opportunities`: filtros y visualización de Opportunities.
- `users/{uid}/filters/{filterId}`: filtro guardado individual. Editar conserva ID. Borrar no reemplaza filtros ajenos.

Los filtros locales se importan mediante un botón explícito. La copia de invitado no recibe información de la cuenta. Firestore usa caché en memoria; no se habilita persistencia de documentos privados en disco. La sesión de Authentication persiste hasta cerrar sesión. Las preferencias no se incorporan a `picks.json`, al HTML ni al archivo público de oportunidades.

Los cambios simultáneos del mismo documento siguen la última escritura aceptada por el servidor. Se muestran los errores de sincronización; no equivalen a guardado confirmado. Firebase y los permisos de producción deben comprobarse antes de afirmar que la integración está activa.

Referencias: https://firebase.google.com/docs/auth/web/google-signin, https://firebase.google.com/docs/auth/web/password-auth, https://firebase.google.com/docs/firestore/security/rules-conditions.
