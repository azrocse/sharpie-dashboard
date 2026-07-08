import json
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        ".."
    )
)

INPUT_FILE = os.path.join(
    BASE_DIR,
    "data",
    "analyzed"
)

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "data",
    "dashboard"
)

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


def get_latest_file():
    direct_file = os.path.join(INPUT_FILE, "sharpie.json")
    if os.path.exists(direct_file):
        return direct_file

    if not os.path.exists(INPUT_FILE):
        return None
    folders = sorted(os.listdir(INPUT_FILE))
    if not folders:
        return None
        
    latest = folders[-1]
    fallback_path = os.path.join(INPUT_FILE, latest, "sharpie.json")
    if os.path.exists(fallback_path):
        return fallback_path
        
    return None


def parse_match_datetime(time_raw):
    current_year = 2026
    try:
        if "," in time_raw:
            date_part, time_part = [p.strip() for p in time_raw.split(",")]
            full_str = f"{date_part}/{current_year} {time_part}"
            
            dt_et = datetime.strptime(full_str, "%m/%d/%Y %I:%M%p")
            dt_cdmx = dt_et - timedelta(hours=2)
            
            return dt_cdmx.strftime("%Y-%m-%d"), dt_cdmx.strftime("%I:%M %p"), dt_cdmx.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        pass
    
    return "2026-07-08", time_raw, "2026-07-08T00:00:00"


def generate_html(leagues_data):
    rows = ""

    for league_obj in leagues_data:
        markets = league_obj.get("markets", [])
        
        for market in markets:
            date_part, time_part, full_iso = parse_match_datetime(market.get('time', ''))
            league = market.get("league", "UNKNOWN")
            trend = market.get("market_trend", "🟡 Mixto")
            action = market.get("action", "🔴 PASAR")

            rows += f"""
            <tr data-iso="{full_iso}">
                <td data-label="Fecha">{date_part}</td>
                <td data-label="Hora">{time_part}</td>
                <td data-label="Liga"><span class="badge league-badge">{league}</span></td>
                <td data-label="Partido"><strong>{market.get('game', '')}</strong></td>
                <td data-label="Mercado">{market.get('market', '')}</td>
                <td data-label="Pick">{market.get('pick', '')}</td>
                <td data-label="Sharpie">{market.get('sharpie', '')}</td>
                <td data-label="Market">{market.get('market_score', '')}</td>
                <td data-label="Trend">{trend}</td>
                <td data-label="Acción">{action}</td>
                <td data-label="Stake">{market.get('stake', 0)}u</td>
                <td data-label="Prioridad">{market.get('priority', '')}</td>
            </tr>
            """

    html = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Sharpie Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
            padding: 20px; background: #0f0f12; color: #e4e4e7; line-height: 1.5;
        }}
        h1 {{ margin-bottom: 20px; font-size: 1.8rem; color: #fff; }}
        .filters-container {{
            margin-bottom: 25px; display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 15px; background: #18181b; padding: 20px; border-radius: 8px; border: 1px solid #27272a;
        }}
        .filter-group {{ display: flex; flex-direction: column; gap: 6px; }}
        .filter-group label {{
            font-size: 11px; color: #a1a1aa; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
        }}
        .filters-container select {{
            padding: 10px; background: #27272a; color: white; border: 1px solid #3f3f46;
            border-radius: 6px; cursor: pointer; font-size: 14px; width: 100%; outline: none;
        }}
        .filters-container select:disabled {{
            opacity: 0.4; cursor: not-allowed; background: #1f1f23;
        }}
        .table-responsive-container {{ width: 100%; background: #18181b; border-radius: 8px; border: 1px solid #27272a; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; }}
        th {{ background: #202024; padding: 14px 16px; font-size: 13px; font-weight: 600; text-transform: uppercase; color: #a1a1aa; border-bottom: 2px solid #27272a; }}
        td {{ padding: 14px 16px; font-size: 14px; border-bottom: 1px solid #27272a; color: #e4e4e7; }}
        tr:hover {{ background: #202024; }}
        .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
        .league-badge {{ background: #3f3f46; color: #fff; }}
        
        @media (max-width: 900px) {{
            body {{ padding: 10px; }}
            .table-responsive-container {{ background: transparent; border: none; }}
            table, thead, tbody, th, td, tr {{ display: block; }}
            thead {{ display: none; }}
            tr {{ background: #18181b; margin-bottom: 15px; border-radius: 8px; border: 1px solid #27272a; padding: 10px 5px; }}
            td {{
                text-align: right; padding: 8px 15px; font-size: 14px; border-bottom: 1px solid #202024;
                position: relative; display: flex; justify-content: space-between; align-items: center;
            }}
            td:last-child {{ border-bottom: none; }}
            td::before {{ content: attr(data-label); font-weight: 600; color: #a1a1aa; text-transform: uppercase; font-size: 11px; text-align: left; }}
        }}
    </style>
</head>
<body>

    <h1>📊 Sharpie Dashboard</h1>

    <div class="filters-container">
        <div class="filter-group"><label>Fecha</label><select id="dateFilter" onchange="filterData()"><option value="">Todas</option></select></div>
        <div class="filter-group"><label>Hora</label><select id="timeFilter" onchange="filterData()" disabled><option value="">Selecciona Fecha</option></select></div>
        <div class="filter-group"><label>Liga</label><select id="leagueFilter" onchange="filterData()"><option value="">Todas</option></select></div>
        <div class="filter-group"><label>Trend</label><select id="trendFilter" onchange="filterData()"><option value="">Todos</option></select></div>
        <div class="filter-group"><label>Acción</label><select id="actionFilter" onchange="filterData()"><option value="">Todas</option></select></div>
    </div>

    <div class="table-responsive-container">
        <table id="dashboardTable">
            <thead>
                <tr>
                    <th>Fecha</th>
                    <th>Hora</th>
                    <th>Liga</th>
                    <th>Partido</th>
                    <th>Mercado</th>
                    <th>Pick</th>
                    <th>Sharpie</th>
                    <th>Market</th>
                    <th>Trend</th>
                    <th>Acción</th>
                    <th>Stake</th>
                    <th>Prioridad</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>

    <script>
    const activeFilters = {{ date: "", time: "", league: "", trend: "", action: "" }};

    function populateFilters() {{
        const rows = Array.from(document.querySelectorAll("#dashboardTable tbody tr"));
        
        const sets = {{
            date: new Set(),
            time: new Set(),
            league: new Set(),
            trend: new Set(),
            action: new Set()
        }};

        rows.forEach(row => {{
            if (row.style.display !== "none") {{
                sets.date.add(row.cells[0].innerText.trim());
                sets.time.add(row.cells[1].innerText.trim());
                sets.league.add(row.cells[2].innerText.trim());
                sets.trend.add(row.cells[8].innerText.trim());
                sets.action.add(row.cells[9].innerText.trim());
            }}
        }});

        // Siempre dejamos disponibles las fechas globales válidas
        if (!activeFilters.date) {{
            const allDates = new Set();
            rows.forEach(r => {{
                const matchIso = r.getAttribute("data-iso");
                if (new Date(matchIso) >= new Date()) {{
                    allDates.add(r.cells[0].innerText.trim());
                }}
            }});
            updateSelectOptions("dateFilter", allDates, activeFilters.date, "Todas");
        }}

        // Control de activación secuencial para la hora
        const timeSelect = document.getElementById("timeFilter");
        if (activeFilters.date) {{
            timeSelect.disabled = false;
            updateSelectOptions("timeFilter", sets.time, activeFilters.time, "Todas");
        }} else {{
            timeSelect.disabled = true;
            timeSelect.innerHTML = '<option value="">Selecciona Fecha</option>';
            activeFilters.time = "";
        }}

        updateSelectOptions("leagueFilter", sets.league, activeFilters.league, "Todas");
        updateSelectOptions("trendFilter", sets.trend, activeFilters.trend, "Todos");
        updateSelectOptions("actionFilter", sets.action, activeFilters.action, "Todas");
    }}

    function updateSelectOptions(elementId, valueSet, currentValue, defaultText) {{
        const select = document.getElementById(elementId);
        const savedValue = select.value;
        select.innerHTML = `<option value="">${{defaultText}}</option>`;
        
        Array.from(valueSet).sort().forEach(val => {{
            const selected = val === currentValue || val === savedValue ? "selected" : "";
            select.innerHTML += `<option value="${{val}}" ${{selected}}>${{val}}</option>`;
        }});
    }}

    function filterData() {{
        activeFilters.date = document.getElementById("dateFilter").value;
        activeFilters.time = document.getElementById("timeFilter").value;
        activeFilters.league = document.getElementById("leagueFilter").value;
        activeFilters.trend = document.getElementById("trendFilter").value;
        activeFilters.action = document.getElementById("actionFilter").value;

        const rows = document.querySelectorAll("#dashboardTable tbody tr");
        const now = new Date();

        rows.forEach(row => {{
            const matchIso = row.getAttribute("data-iso");
            const matchDateObj = new Date(matchIso);

            if (matchDateObj < now) {{
                row.style.display = "none";
                return;
            }}

            const dText = row.cells[0].innerText;
            const tText = row.cells[1].innerText;
            const lText = row.cells[2].innerText;
            const trText = row.cells[8].innerText;
            const aText = row.cells[9].innerText;

            const mDate = !activeFilters.date || dText === activeFilters.date;
            const mTime = !activeFilters.time || tText === activeFilters.time;
            const mLeague = !activeFilters.league || lText === activeFilters.league;
            const mTrend = !activeFilters.trend || trText.includes(activeFilters.trend);
            const mAction = !activeFilters.action || aText.includes(activeFilters.action);

            if (mDate && mTime && mLeague && mTrend && mAction) {{
                row.style.display = "";
            }} else {{
                row.style.display = "none";
            }}
        }});

        populateFilters();
    }}

    document.addEventListener("DOMContentLoaded", () => {{
        filterData();
    }});
    </script>
</body>
</html>
"""
    return html


def generate_dashboard():
    file = get_latest_file()
    if not file:
        print("❌ Error: No se encontró ningún archivo 'sharpie.json'.")
        return

    with open(file, encoding="utf-8") as f:
        data = json.load(f)

    html = generate_html(data)
    output = os.path.join(OUTPUT_DIR, "index.html")

    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    print()
    print("✓ Dashboard creado con filtros secuenciales Fecha -> Hora:", output)


if __name__ == "__main__":
    generate_dashboard()