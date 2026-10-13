# Ichimoku Chikou Breakout Alert Bot

Bot de **alertas**, sin ejecución de órdenes, para Binance spot y Yahoo Finance.
Detecta una reversión temprana: cruce Tenkan/Kijun fuera de la nube seguido de
ruptura Chikou. No es una estrategia de seguimiento que exija precio sobre/bajo
la nube en la entrada. Su rentabilidad **no está validada**.

## Estrategia exacta

Se evalúan exclusivamente velas cerradas:

1. LONG: Tenkan pasa de `<= Kijun` a `> Kijun`, con cierre **por debajo del
   borde inferior** del Kumo completo. SHORT: inverso, sobre el borde superior.
2. El cruce debe ser anterior a la entrada y tener como máximo
   `cross_lookback_bars` velas de antigüedad. La igualdad T/K o pérdida de la
   dirección cancela esa preparación; un nuevo cruce puede crear otra.
3. LONG: `close[t-1] <= high[t-1-displacement]` y
   `close[t] > high[t-displacement]`. SHORT: cruza bajo los mínimos históricos.
4. Solo se considera la primera ruptura posterior al cruce. Si un filtro la
   rechaza, no se rescata una ruptura posterior de esa misma preparación.
5. Stop LONG = `min(Kijun actual, mínimo desde el cruce)` menos buffer ATR;
   SHORT = `max(Kijun actual, máximo desde el cruce)` más buffer ATR.
   Es el stop **más amplio**, no el más ajustado. Se descartan stops inválidos.

Estar fuera de la nube en el cruce sirve de contexto de reversión; no constituye
una prueba independiente de tendencia previa. Tampoco se exige que Chikou esté
libre de todas las velas intermedias: se compara la vela en su coordenada histórica.
No se implementan confirmación multitemporal ni objetivos S/R automáticos.

Ichimoku usa 9/26/52 con desplazamiento 26. Kumo actual usa Senkou desplazadas;
`projected_senkou_a/b` son valores calculados hoy y dibujados hacia delante.
`chikou` contiene el cierre actual, para dibujarlo 26 posiciones atrás: **no**
contiene cierres futuros. El ATR de 14 periodos usa semilla SMA y suavizado Wilder.
No se acepta Kumo incompleto durante el calentamiento.

## Instalación

```bash
git clone https://github.com/dgarcoe/ichimoku_alert_bot.git
cd ichimoku_alert_bot
cp .env.example .env
cp config/config.example.yml config/config.yml
```

Crea tu bot con BotFather, inicia una conversación con él y configura
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_IDS` en `.env`. Los destinatarios pueden
separarse con comas. No subas credenciales a Git.

```bash
docker compose up -d --build
docker compose logs -f --tail=100
```

Edita `config/config.yml` y reinicia para cambiar la lista de mercados. El estado
se guarda en el volumen `/data`. El healthcheck comprueba únicamente que el
proceso sigue vivo, no la salud de las APIs ni la entrega de alertas.

Para ejecutar sin Docker:

```bash
python -m pip install -r requirements.txt
# Exporta las variables de Telegram en tu shell; Python no carga .env.
python -m app.main --config config/config.yml
```

Diagnóstico **sin Telegram ni escritura de estado** (sí consulta precios):

```bash
LOG_LEVEL=DEBUG python -m app.main --config config/config.example.yml --once --dry-run
```

## Configuración y filtros

| Parámetro | Función |
|---|---|
| `ichimoku.*` | Periodos positivos del indicador |
| `scan.history_bars` | Al menos `max(periodos) + displacement + cross_lookback + 1`; Binance admite hasta 999 |
| `scan.cross_lookback_bars` | Caducidad del cruce, 60 por defecto |
| `scan.poll_interval_seconds` | Frecuencia de consulta; ejemplo: 60 s |
| `scan.max_signal_age_seconds` | Antigüedad máxima desde cierre; ejemplo: 600 s |
| `strategy.min_breakout_atr` | Separación mínima Chikou/precio histórico, en ATR |
| `strategy.stop_buffer_atr` | Margen adicional del stop, en ATR |
| `strategy.max_stop_pct` | Distancia máxima del stop respecto al cierre, en porcentaje |
| `strategy.max_kijun_distance_atr` | Evita entradas excesivamente alejadas de Kijun |
| `strategy.require_price_outside_cloud` | LONG sobre Kumo actual, SHORT bajo Kumo actual en la ruptura |
| `strategy.require_projected_cloud` | Exige nube proyectada a favor |

Los filtros numéricos en cero y booleanos en `false` están desactivados. No se
presentan umbrales optimizados: endurecer filtros reduce oportunidades, pero no
asegura mayor expectativa. Confirmar sobre la nube en la misma ruptura no equivale
a esperar una entrada posterior sobre la nube.

El precio de la alerta es el **cierre de señal**, no una ejecución garantizada.
La distancia al stop es riesgo de precio; no es porcentaje de pérdida de tu cuenta.
El bot no calcula apalancamiento ni tamaño de posición.

## Fuentes de datos

| Fuente | Símbolos | Timeframes |
|---|---|---|
| Binance spot | `BTCUSDT`, `BTC/USDT` | 1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 1w |
| Yahoo | `EURUSD=X`, `EUR/USD`, `AAPL`, `BTC-USD`, `GC=F` | 1m, 5m, 15m, 30m, 1h, 1d, 1w |
| Yahoo sintético | Mismos símbolos | 2h, 4h, 6h, 8h, 12h agregados desde 1h |

Binance filtra usando `close_time`; no elimina incondicionalmente la última vela.
No se usan precios de perpetuos: una señal spot no modela basis, funding o
liquidación de futuros. `BTCUSDT` en Yahoo se convierte a `BTC-USD`, otro mercado.

Yahoo sintético agrega horas completas en bloques UTC y descarta bloques con
horas ausentes. **No está ajustado a sesiones bursátiles**, por lo que descarta
sesiones parciales y puede omitir datos válidos de acciones. Los cierres Yahoo
nativos se estiman como apertura + duración: diarios/semanales de bolsas pueden
retrasarse respecto al cierre real. Para acciones con necesidades de precisión
intradiaria, hace falta integrar un calendario de mercado. Los precios no están
ajustados por splits (`auto_adjust=False`); no uses esos históricos para evaluar
acciones con operaciones corporativas sin normalizarlos antes.

OHLC inválidos, duplicados, desordenados o no finitos se rechazan. No se rellenan
huecos con precios inventados. Las ventanas del indicador cuentan velas recibidas,
no tiempo transcurrido. Retrasos del proveedor o un periodo de caída pueden hacer
que una señal caduque. Se examina la última vela, sin recuperar todas las señales
intermedias perdidas. Ajusta el margen de antigüedad al proveedor.

## Entrega y persistencia

Una señal solo se marca enviada tras respuesta HTTP 200 con `ok: true` de Telegram.
Cada destinatario confirmado se persiste por separado; el siguiente ciclo reintenta
solo los pendientes mientras la señal siga vigente. No se imprimen tokens, URLs
de Telegram ni cuerpos de error en los logs de entrega.

El estado JSON conserva orden de inserción y un máximo de 5000 claves, en memoria
y disco. Se reemplaza de forma atómica; admite rutas sin directorio. Ejecuta una
sola instancia por archivo de estado. Los errores de escritura se registran y un
reinicio podría repetir mensajes. También puede haber duplicados si Telegram
acepta el mensaje pero la respuesta se pierde: no hay entrega exactamente una vez.

## Backtest offline

CSV: `timestamp,open,high,low,close[,volume]`, fechas UTC ascendentes, precios
positivos y solo velas cerradas. Usa un histórico suficientemente largo con
calentamiento anterior al periodo de evaluación.

```bash
python -m app.backtest BTCUSDT-1h.csv \
  --config config/config.example.yml \
  --fee-bps 10 --slippage-bps 5 --reward-r 2 \
  --max-holding-bars 100 --test-start 2025-01-01 \
  --trades-csv trades.csv
```

Modelo reproducible:

- Señal al cierre, entrada en la apertura siguiente con deslizamiento adverso.
- Una posición por símbolo; sin reinversión, apalancamiento ni piramidación.
- Stop inicial fijo, objetivo de múltiplo R; no trailing Kijun automático.
- Stop prioritario si stop y objetivo se tocan en una vela. Los gaps adversos al
  stop ejecutan a apertura con deslizamiento. Objetivos limitados a su precio.
- Comisiones en entrada y salida; slippage en entrada y salidas de mercado/stop.
- Cierre por tiempo o fin de datos; costes de funding, préstamo y spread no modelados.
- Métricas: número de operaciones, acierto neto, R neto, expectativa R, profit
  factor y drawdown **de operaciones cerradas** en R. No equivale a drawdown
  intraposición o de cartera. Profit factor es `null` si no hay pérdidas.
- `--test-start` conserva calentamiento pero no abre operaciones antes del corte.

Protocolo recomendado: separar cronológicamente diseño, validación y prueba;
comparar la base corregida y cada filtro individual; incluir mercados laterales,
alcistas y bajistas, varios activos y costes superiores a los esperados. Congelar
parámetros antes del periodo de prueba. Examinar número de operaciones, exposición,
concentración por activo y estabilidad, no solo acierto. Este cambio **no incluye
resultados de rentabilidad sobre históricos reales**.

## Pruebas

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

Pruebas offline con HTTP simulado: señales simétricas, cruces inválidos, consumo
único, filtros, ausencia de información futura, OHLC inválidos, velas cerradas,
resampling, deduplicación, entrega parcial y costes del backtest. CI verifica
Python 3.11/3.12 y construye la imagen Docker.

## Referencias técnicas

- [Binance market data](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)
- [Telegram Bot API](https://core.telegram.org/bots/api#making-requests)
- [Ichimoku Cloud — TradingView](https://www.tradingview.com/support/solutions/43000589152-ichimoku-cloud/)
