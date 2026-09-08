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

Los criterios iniciales están en `src/tracking.py` (`DEFAULT_POLICY`): EV mínimo
1%, Edge mínimo 1 punto, stake mínimo 1u, confianza mínima 55, categoría VALUE o
PREMIUM y acción bet; señal de flujo admitida, porcentajes válidos y divergencia
consistente. Se requieren dos procesamientos con observaciones distintas que
cumplan los criterios, datos de hasta 15 minutos y entre 10 minutos y 24 horas
hasta el inicio. Son reglas operativas iniciales, no una calibración de resultados
ni garantía del mejor momento de entrada. Cuota, modelo, EV y Edge se evalúan
como condiciones relacionadas; no se suman como evidencias independientes.

### Avisos por Telegram

Configura un bot de [BotFather](https://t.me/BotFather) localmente:

```powershell
python -B src/setup_telegram.py
```

El asistente pide el token con entrada oculta, valida el bot y permite elegir
suscripciones públicas o una lista de IDs de chats privados autorizados.
Guarda el resultado en `.runtime/telegram.json`. **No publiques esa carpeta**:
contiene token, chats, suscripciones y referencias persistentes; está excluida
de Git. Respáldala de forma privada para conservar el seguimiento entre equipos.
El HTML solo recibe el enlace público del bot y el identificador del pick.

En la card, «Avisarme por Telegram» abre el bot. El usuario debe confirmar
**Iniciar** en Telegram; abrir el enlace por sí solo no activa la suscripción.
Se confirma la suscripción en el siguiente procesamiento (aprox. cinco minutos).
`/stop ID_DEL_PICK` cancela un pick; `/stop` cancela todos los del chat.
Sin configuración, se muestra «Telegram pendiente» y no se envían mensajes.

El mismo proceso de `auto_publish.ps1` consulta comandos y avisa al cumplir los
criterios, perderlos o cerrar el prepartido. Una mejora exige al menos +2 puntos
de EV y +1 de Edge desde el último aviso, y 30 minutos de espera. No repite la
misma condición en cada ciclo. Lecturas vencidas, ausencias o errores del feed
no generan avisos positivos. Los fallos de Telegram se reintentan sin impedir
publicar el dashboard; los bloqueos del bot cancelan las suscripciones del chat.
La entrega puede demorarse por el ciclo de ejecución. Un fallo de red después
de que Telegram acepte un mensaje puede causar un duplicado al reintentar.
El equipo y la tarea programada deben seguir activos; GitHub Pages no ejecuta
el bot. Implementación basada en los [enlaces de inicio](https://core.telegram.org/bots/features#deep-linking)
y la [Bot API oficial](https://core.telegram.org/bots/api).

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
