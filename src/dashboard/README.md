# Carpeta `dashboard`

Esta versión separa la interfaz en módulos editables, pero conserva un despliegue simple: los generadores insertan CSS, JavaScript y componentes dentro de `index.html` y `results.html`. Los archivos publicados siguen siendo autónomos.

## Estructura

```text
dashboard/
├── __init__.py
├── generate_dashboard.py
├── generate_results_viewer.py
├── template_loader.py
├── template.html
├── templates/
│   ├── dashboard_body.html
│   ├── results.html
│   └── results_body.html
└── assets/
    ├── css/
    │   ├── dashboard.css
    │   └── results.css
    └── js/
        ├── dashboard.js
        ├── results.js
        └── theme-init.js
```

## Responsabilidad de cada módulo

- `generate_dashboard.py`: transforma `data/analyzed/sharpie.json`, guarda los picks con valor y genera el dashboard principal.
- `generate_results_viewer.py`: consolida `data/history/*/sharpie.json` y genera el visualizador histórico.
- `template_loader.py`: carga componentes, comprueba tokens y escribe archivos de forma atómica.
- `template.html`: shell mínimo del dashboard principal.
- `templates/dashboard_body.html`: estructura visible del dashboard.
- `templates/results.html`: shell mínimo del visualizador.
- `templates/results_body.html`: estructura visible del visualizador.
- `assets/css/*`: estilos responsivos.
- `assets/js/*`: filtros, gráficas, cards, interacción y carga de datos.

## Instalación

Reemplaza la carpeta `src/dashboard` completa por esta carpeta. No copies solamente `template.html`, porque ahora depende de los componentes incluidos aquí.

La estructura esperada del proyecto es:

```text
sharpie-dashboard/
├── data/
│   ├── analyzed/
│   ├── history/
│   └── snapshots/
├── src/
│   └── dashboard/   ← esta carpeta
├── index.html       ← generado
├── picks.json       ← generado
└── results.html     ← generado
```

## Ejecución directa

Desde la raíz del proyecto:

```powershell
python src/dashboard/generate_dashboard.py
python src/dashboard/generate_results_viewer.py
```

También se pueden importar desde `main.py`:

```python
from dashboard.generate_dashboard import generate_dashboard
from dashboard.generate_results_viewer import generate_results_viewer
```

## Reglas protegidas

- No se recalculan modelo, edge, EV, divergencia, señal o stake en el frontend.
- El dashboard consume esos valores desde el JSON analizado como única fuente de verdad.
- El historial guarda únicamente picks que cumplen los criterios vigentes de valor.
- La hora se normaliza con zonas reales `America/New_York` y `America/Mexico_City`; ya no usa un descuento fijo de dos horas.
- `index.html`, `picks.json` y `results.html` se escriben atómicamente para no dejar archivos truncados.
