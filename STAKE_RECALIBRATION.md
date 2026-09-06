# Recalibración de riesgo y stake

## Política operativa

- La confianza se calcula por separado del EV. El EV aporta como máximo 10 puntos.
- No existe un mínimo absoluto de 55%: los underdogs se evalúan mediante el Edge contra la probabilidad implícita.
- SMART MONEY/WHALE es una señal de mercado, no una categoría de confianza.
- Cuotas de +151 a +250 se clasifican como `LONGSHOT`.
- Cuotas de +251 o superiores se clasifican como `EXTREME_LONGSHOT`.
- Todo longshot tiene un stake máximo de 0.5u, independientemente de Kelly o EV.
- El stake operativo normal queda limitado a 3u mientras se valida la nueva calibración.
- Los longshots permanecen visibles como especulativos, pero no cuentan como oportunidades, no pueden ser Top Pick y no se publican automáticamente como Free Pick.

## Umbrales de selección

- `VALUE`: Edge >= 2%, EV >= 3%, confianza >= 40 y cuota <= +150.
- `PREMIUM`: Edge >= 4%, EV >= 6%, confianza >= 60 y cuota <= +150.
- `LONGSHOT` +151 a +250: Edge >= 2% y EV >= 5%.
- `EXTREME_LONGSHOT` desde +251: Edge >= 3% y EV >= 8%.

## Campos añadidos al JSON

- `confidenceScore`
- `confidence`
- `confidenceStakeCap`
- `oddsStakeCap`
- `riskClass`
- `riskLevel`

## Validación

Ejecutar desde la raíz del proyecto:

```powershell
python -m unittest discover -s tests -v
```
