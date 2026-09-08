# Sharpie Dashboard

El proyecto mantiene un único flujo: descarga de Betting Splits de DraftKings,
parseo, análisis de mercados y generación del dashboard actual.

## Ejecutar

Requiere Python 3.10 o superior. Desde la raíz:

```powershell
python -m pip install -r src/requirements.txt
python -B src/main.py
```

`src/config/leagues.json` define las ligas habilitadas. Actualmente solo se
descarga `SPORTS`. Cada mercado conserva la liga de su fuente configurada;
no se deducen ligas a partir de nombres de equipos, selecciones o mercados.

## Archivos del flujo

| Archivo | Función |
|---|---|
| `src/main.py` | Coordina descarga, parseo, análisis y dashboard. |
| `src/scraper/` | Descarga y procesa HTML en memoria. |
| `src/pipeline/` | Actualiza el estado de mercados y aplica el modelo. |
| `src/config/` | Configuración única de ligas y descargas. |
| `src/storage.py` | Escritura atómica compartida. |
| `src/dashboard/` | Generador, plantillas, CSS y JavaScript del dashboard. |
| `data/parsed/sports.json` | Última descarga válida con observaciones recientes. |
| `data/analyzed/sharpie.json` | Análisis actual, reemplazado en cada ejecución válida. |
| `index.html` | Dashboard generado con estilos, scripts y datos integrados. |
| `picks.json` | Datos actuales para la actualización automática del navegador. |
| `data/opportunities.json` | Oportunidades guardadas desde la activación del registro. |
| `opportunities.html` | Sábana de consulta con filtros y detalle de cada oportunidad. |

La sábana muestra eventos de hoy hacia atrás, por fecha del encuentro en CDMX.
Los eventos futuros permanecen guardados pero no participan en la consulta,
opciones de filtros, contadores, gráficos ni exportación XLS hasta su fecha.
El registro conserva el objeto completo producido por el dashboard, sin una
lista adicional que recorte sus campos. La depuración se realiza en `build_picks`:
no construye etiquetas duplicadas ni campos sin consumidores. Se conservan los
cálculos intermedios necesarios para validar o explicar las selecciones.

Abre `opportunities.html` en el navegador o usa **Oportunidades guardadas** en el
dashboard. Comparte sus estilos, tema claro/oscuro y gráficos de Modelo vs EV y
señales de mercado. Las métricas y gráficos responden a los filtros de fecha,
liga, categoría, señal y rangos cuantitativos. Funciona como archivo local con los datos incluidos. Cuando se sirve
por HTTP, consulta el JSON cada 90 segundos y permite actualizar manualmente.
La vista se regenera en cada ejecución del dashboard, sin recalcular los valores
guardados. Para reconstruir únicamente el viewer desde la raíz:

```powershell
$env:PYTHONPATH = 'src'
python -B -m dashboard.generate_opportunities_viewer
```

No se generan archivos RAW, snapshots ni resultados.
El registro de oportunidades guarda únicamente `VALUE` y `PREMIUM` con
`actionKey=bet`, usando los valores finales del dashboard. No importa el historial
antiguo. Cada oportunidad conserva un ID estable y fechas de primera captura y
última actualización. Antes del inicio se actualiza su última versión elegible;
al comenzar se congela, incluso si ya desapareció del dashboard. Los picks de
seguimiento y los longshots no se incorporan. El archivo es persistente y no debe
borrarse como si fuera una salida regenerable.
El JSON actual conserva hasta 200 observaciones por mercado presente en el feed
para calcular movimiento de cuota y mostrar su evolución. Los mercados que
desaparecen del feed dejan de conservarse en la siguiente descarga válida.

Se requieren dos observaciones pregame para mostrar un mercado en el dashboard.
Una instalación sin datos previos puede mostrar el estado vacío durante el primer
ciclo. Los eventos iniciados se ocultan. Cuando una descarga válida ya no contiene
picks elegibles, se actualiza el dashboard vacío para retirar los picks anteriores.
Si falla la descarga o el parseo, el proceso termina con error y conserva la salida
publicada anterior.

## Ejecutar etapas por separado

```powershell
$env:PYTHONPATH = 'src'
python -B -m pipeline.analyze
python -B -m dashboard.generate_dashboard
```

El análisis independiente lee exclusivamente las ligas habilitadas en la misma
configuración que utiliza la descarga. No incorpora JSON antiguos por encontrar
archivos adicionales en la carpeta.

## Pruebas

```powershell
python -B -m unittest discover -s tests -t . -v
```

Las pruebas usan HTML simulado y carpetas temporales. Cubren el flujo completo,
errores de descarga y parseo, conservación del estado válido, observaciones
acotadas, exclusión de eventos iniciados y reglas vigentes de riesgo y stake.

## Actualización automática

Todas las cards incluyen seguimiento automático desde la primera observación
disponible. La cuota/Bets/Handle iniciales se conservan; Modelo/Edge/EV parten
de la primera evaluación realmente guardada, sin inventar valores anteriores.
La referencia persiste en `.runtime/tracking.json` aunque se cierre el navegador.
La antigua watchlist de localStorage ya no controla el seguimiento.

El seguimiento utiliza la misma clasificación del dashboard: acción `bet` y
categoría VALUE o PREMIUM. No agrega mínimos de confianza, EV, Edge, stake,
confirmaciones ni ventanas de entrada. Solo evita avisar con datos de más de
15 minutos o de encuentros ya iniciados. El analizador conserva su evaluación
de cuota, modelo, riesgo y flujo.

### Avisos por Telegram

Configura el bot localmente si todavía no está configurado:

```powershell
python -B src/setup_telegram.py
```

La configuración, token, destinatarios y seguimiento permanecen en `.runtime/`,
excluida de Git. Respáldala de forma privada. El HTML solo recibe el enlace público.

«Recibir picks por Telegram» abre el bot. Pulsa **Iniciar** una vez para recibir
la confirmación «Avisos activados» y todos los picks cuando tengan valor.
Puedes usar **Pausar avisos**, `/stop`, **Activar avisos** o `/resume` en Telegram.
Abrir el enlace sin enviar Iniciar no permite identificar tu chat.
Las suscripciones antiguas por pick requieren activar la nueva modalidad general.

Los mensajes muestran encuentro, pick, mercado, cuota, stake y hora CDMX, con
botones para ver el pick y pausar. Cada pick se envía una sola vez por chat;
pausar y reactivar conserva el registro de envíos. No hay avisos de mejoras,
pérdida de valor o cierre. Un error de red después de que Telegram acepte un
mensaje puede causar un duplicado al reintentar.

`telegram_worker.ps1` mantiene un proceso independiente que atiende los comandos
con long polling, sin esperar el scraper. Usa un bloqueo exclusivo para evitar
dos receptores simultáneos. El estado operativo, sin secretos, se consulta en
`.runtime/telegram-worker-status.json`. El scraper sigue actualizando los picks
cada cinco minutos; el worker envía los avisos al leer la nueva evaluación.

Para instalar o reparar la tarea independiente, desde PowerShell como administrador:

```powershell
.\install_telegram_task.ps1
```

El equipo debe permanecer encendido y conectado. GitHub Pages solo muestra el
sitio; no ejecuta el bot. Implementación basada en los
[enlaces de inicio](https://core.telegram.org/bots/features#deep-linking) y la
[Bot API oficial](https://core.telegram.org/bots/api).

`auto_publish.ps1` ejecuta el flujo y publica únicamente sus salidas actuales.
Comprueba el código de salida de Python y de cada operación de Git, e impide
ejecuciones simultáneas del script.

Si hay cambios locales fuera de las salidas generadas, ejecuta el flujo y guarda
las oportunidades localmente, pero omite la publicación hasta revisar el código.
Para actualizar localmente de forma manual:

```powershell
.\auto_publish.ps1 -SkipPublish
```

`refresh_log.txt` contiene el registro local y está excluido de Git.
