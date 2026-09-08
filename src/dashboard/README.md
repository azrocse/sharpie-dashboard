# Dashboard actual

`generate_dashboard.py` convierte el análisis actual en `index.html` y `picks.json`.

- `template.html`: documento principal y tokens de ensamblado.
- `templates/dashboard_body.html`: estructura visible.
- `assets/css/dashboard.css`: estilos.
- `assets/js/dashboard.js`: filtros, gráficas, seguimiento local y actualización de datos.
- `assets/js/theme-init.js`: tema inicial.
- `template_loader.py`: lectura de recursos y validación de tokens.

El generador usa la escritura atómica de `src/storage.py`. Consume las métricas del
analizador y las observaciones recientes contenidas en el estado actual. No consulta
archivos de snapshots ni genera liquidaciones o reportes de resultados. Guarda las
oportunidades finales en `data/opportunities.json` a través de `src/opportunities.py`.

Los cambios visuales se hacen en plantillas y assets; `index.html` es una salida
generada. Desde la raíz, para regenerarlo con el análisis existente:

```powershell
$env:PYTHONPATH = 'src'
python -B -m dashboard.generate_dashboard
```

Consulta `README.md` en la raíz para instalar, ejecutar y probar el flujo completo.
