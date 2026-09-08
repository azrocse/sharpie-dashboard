"""Vista de consulta del registro de oportunidades; no altera sus valores."""

import json
from pathlib import Path

from dashboard.template_loader import read_utf8, render_template
from storage import atomic_write_text


CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent.parent


def generate_opportunities_viewer(source_path=None, output_dir=None):
    output_dir = Path(output_dir or BASE_DIR)
    source_path = Path(source_path or output_dir / "data" / "opportunities.json")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or not isinstance(payload.get("picks"), list):
        raise ValueError(f"Registro de oportunidades inválido: {source_path}")
    html = render_template(CURRENT_DIR / "templates" / "opportunities.html", {
        "DASHBOARD_CSS": read_utf8(CURRENT_DIR / "assets/css/dashboard.css"),
        "IDENTITY_CSS": read_utf8(CURRENT_DIR / "assets/css/identity.css"),
        "THEME_INIT_JS": read_utf8(CURRENT_DIR / "assets/js/theme-init.js"),
        "VIEWER_CSS": read_utf8(CURRENT_DIR / "assets/css/opportunities.css"),
        "VIEWER_JS": read_utf8(CURRENT_DIR / "assets/js/opportunities.js"),
        "EXCEL_JS": read_utf8(CURRENT_DIR / "assets/js/xlsx.full.min.js"),
        "OPPORTUNITIES_JSON": json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
    })
    output = output_dir / "opportunities.html"
    atomic_write_text(output, html)
    return output


if __name__ == "__main__":
    print(generate_opportunities_viewer())
