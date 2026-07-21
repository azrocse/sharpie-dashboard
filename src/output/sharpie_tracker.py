import json
import os
from datetime import datetime

def guardar_datos_reales(nuevos_picks, nombre_archivo_maestro="history_master.json"):
    # Sube desde src/ hasta la raíz del proyecto y entra a data/history/
    dir_actual = os.path.dirname(os.path.abspath(__file__))
    raiz_proyecto = os.path.join(dir_actual, "..", "..")
    data_history_dir = os.path.join(raiz_proyecto, "data", "history")
    
    os.makedirs(data_history_dir, exist_ok=True)
    archivo_historial = os.path.join(data_history_dir, nombre_archivo_maestro)

    # Cargar historial existente o inicializar estructura base
    if os.path.exists(archivo_historial):
        try:
            with open(archivo_historial, "r", encoding="utf-8") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = {"metadata": {"fields": ["time", "betsPct", "handlePct", "odds", "status", "result", "roi"]}, "events": {}}
    else:
        history = {
            "metadata": {
                "fields": ["time", "betsPct", "handlePct", "odds", "status", "result", "roi"]
            },
            "events": {}
        }

    hora_actual = datetime.now().strftime("%H:%M")
    
    for p in nuevos_picks:
        game_id = p.get("game", "").lower().replace(" ", "_")
        fecha_evento = p.get("date", datetime.now().strftime("%Y-%m-%d"))
        event_key = f"{game_id}_{fecha_evento}"
        
        if event_key not in history["events"]:
            history["events"][event_key] = {
                "game": p.get("game"),
                "league": p.get("league"),
                "pick": p.get("pick"),
                "market": p.get("market"),
                "score": p.get("score", 0),
                "modelProb": p.get("modelProb", 0),
                "edge": p.get("edge", 0),
                "trendKey": p.get("trendKey", "other"),
                "whale": p.get("whale", False),
                "ev": p.get("ev", 0),
                "stake": p.get("stake", 0),
                "risk": p.get("risk", "NORMAL"),
                "actionKey": p.get("actionKey", "bet"),
                "freePick": p.get("freePick", False),
                "reason": p.get("reason", ""),
                "timeline": []
            }
        
        snapshot = [
            hora_actual,
            p.get("betsPct", 0),
            p.get("handlePct", 0),
            p.get("odds", "1.90"),
            p.get("status", "UPCOMING"),
            p.get("result", None),
            p.get("roi", None)
        ]
        
        timeline = history["events"][event_key]["timeline"]
        
        if not timeline or timeline[-1][0] != hora_actual:
            timeline.append(snapshot)
        else:
            timeline[-1] = snapshot

    # Guardado minificado en data/history/history_master.json
    with open(archivo_historial, "w", encoding="utf-8") as f:
        json.dump(history, f, separators=(',', ':'), ensure_ascii=False)
        
    print(f"✅ Historial real actualizado correctamente en data/history/{nombre_archivo_maestro}")