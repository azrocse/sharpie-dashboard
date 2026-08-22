import asyncio
import re
import json
from playwright.async_api import async_playwright

TARGET_URL = "https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/?tb_eg=MLB"

def parse_dk_splits(lines):
    events = []
    current_event = None
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Detección de encabezado de partido: "MIA Marlins @ PHI Phillies"
        if " @ " in line and len(line.split(" @ ")) == 2:
            teams = line.split(" @ ")
            current_event = {
                "matchup": line,
                "away_team": teams[0].strip(),
                "home_team": teams[1].strip(),
                "date_time": lines[i+1].strip() if (i+1 < len(lines)) else "",
                "markets": {}
            }
            events.append(current_event)
            i += 2
            continue

        # Detección de tipos de mercado
        if line in ["Moneyline", "Run Line", "Spread", "Total"]:
            market_name = line
            
            # Saltamos encabezados fijos: 'Odds', '% Handle', '% Bets'
            # Leemos los bloques de 4 elementos: [Equipo/Línea, Odds, Handle%, Bets%]
            try:
                # Buscar posición de inicio de datos omitiendo headers
                offset = i + 1
                while offset < len(lines) and lines[offset] in ["Odds", "% Handle", "% Bets"]:
                    offset += 1

                # Lectura de Lado A
                side1_name = lines[offset]
                side1_odds = lines[offset + 1]
                side1_handle = lines[offset + 2]
                side1_bets = lines[offset + 3]

                # Lectura de Lado B
                side2_name = lines[offset + 4]
                side2_odds = lines[offset + 5]
                side2_handle = lines[offset + 6]
                side2_bets = lines[offset + 7]

                if current_event is not None:
                    current_event["markets"][market_name] = {
                        "side1": {
                            "team": side1_name,
                            "odds": side1_odds,
                            "handle": side1_handle,
                            "bets": side1_bets
                        },
                        "side2": {
                            "team": side2_name,
                            "odds": side2_odds,
                            "handle": side2_handle,
                            "bets": side2_bets
                        }
                    }
                i = offset + 8
                continue
            except IndexError:
                i += 1
                continue

        i += 1

    return events


async def test_full_parser():
    async with async_playwright() as p:
        print("[+] Extrayendo y parseando datos completos de DK Network...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 1000}
        )
        page = await context.new_page()

        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        container = await page.query_selector("#tbsedid, .tbtw")
        if not container:
            print("[!] Contenedor no encontrado.")
            await browser.close()
            return

        text = await container.inner_text()
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        parsed_data = parse_dk_splits(lines)

        print(f"\n[ÉXITO] Partidos parseados estructurados: {len(parsed_data)}\n")
        
        if parsed_data:
            print("=== MUESTRA JSON DEL PRIMER PARTIDO ===")
            print(json.dumps(parsed_data[0], indent=2, ensure_ascii=False))

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_full_parser())