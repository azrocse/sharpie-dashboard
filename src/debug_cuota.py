import os
from bs4 import BeautifulSoup

# Ajusta esta ruta si tus archivos en bruto están en otra carpeta de descarga
RAW_HTML_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))

def debug_raw_html():
    print("--- RASTREO PROFUNDO DE ORIGEN (HTML CRUDO) ---")
    found_target = False
    
    for root, dirs, files in os.walk(RAW_HTML_DIR):
        for file in files:
            if file.endswith(".html"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    html = f.read()
                
                soup = BeautifulSoup(html, "html.parser")
                events = soup.select(".tb-se")
                
                for event in events:
                    title = event.select_one(".tb-se-title h5")
                    if not title:
                        continue
                    game_title = title.get_text(" ", strip=True)
                    
                    # Buscamos alguno de los partidos críticos que dieron guión
                    if "Tigers" in game_title or "White Sox" in game_title or "Nationals" in game_title:
                        found_target = True
                        print(f"\n[PARTIDO ENCONTRADO EN HTML]: {game_title} (Archivo: {file})")
                        
                        market_blocks = event.select(".tb-market-wrap > div")
                        for block in market_blocks:
                            head = block.select_one(".tb-se-head div")
                            m_name = head.get_text(" ", strip=True) if head else "Desconocido"
                            
                            rows = block.select(".tb-sm")
                            for row in rows:
                                pick_el = row.select_one(".tb-slipline")
                                if not pick_el:
                                    continue
                                
                                pick_text = pick_el.get_text(" ", strip=True)
                                full_row_text = row.get_text(" ", strip=True)
                                
                                # Buscamos específicamente los totales u opciones que suelen salir con guión
                                if "Over" in pick_text or "Under" in pick_text or "-1.5" in pick_text:
                                    print(f"  -> Mercado: {m_name} | Pick: {pick_text}")
                                    print(f"     Texto crudo de la fila en HTML: [{full_row_text}]")
                                    
                                    # Revisamos clases específicas de odds en el HTML por si el regex las ignora
                                    odds_nodes = row.select(".tb-se-odds, .tb-odds, .odds, span, div")
                                    potential_odds = [n.get_text(strip=True) for n in odds_nodes if "+" in n.get_text() or "-" in n.get_text()]
                                    print(f"     Elementos con signos +/- encontrados en esta fila: {potential_odds}")

    if not found_target:
        print("\nNo se encontraron archivos HTML crudos con esos equipos en las rutas comunes. Verifica dónde guarda el scraper los archivos fuente.")

if __name__ == "__main__":
    debug_raw_html()