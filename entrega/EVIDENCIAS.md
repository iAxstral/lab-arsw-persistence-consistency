# Evidencias · ARSW-EQP-XX

Todas las horas están en **UTC** (2026-10-31). Los JSON originales de `results/` se copiaron a [`evidencias/json/`](evidencias/json/) con prefijo `antes-` (código base) o `despues-` (con los TODO corregidos). La salida completa de cada comando está en [`evidencias/logs/`](evidencias/logs/) y las capturas en [`evidencias/capturas/`](evidencias/capturas/).

## Entorno

- **SO / CPU:** Linux x86_64 (VM), Intel Xeon @ 2.10 GHz, 4 vCPU
- **RAM:** 16 GB; Docker Engine nativo sin límite explícito de memoria (≈ 1 GB en uso con todo el Compose arriba)
- **Docker:** Engine 29.9.2 · **Compose:** v5.6.1 (soporta `--wait`)
- **Imágenes:** postgres 16.6-alpine, mongo 7.0.16, redis 7.4.2-alpine, nginx 1.27.3-alpine, prometheus v3.1.0, grafana 11.5.1, k6 0.57.0, API python 3.12-slim
- Detalle en [`logs/00-entorno.txt`](evidencias/logs/00-entorno.txt). Targets `content` y `management` en estado `up` en Prometheus antes de empezar.

## Registro

| Experimento | Inicio / fin (UTC) | Archivo / captura | Resultado observado | Interpretación |
|---|---|---|---|---|
| Smoke | 12:23:52 | `json/smoke-20261031T122352Z.json`, `logs/01-smoke.txt` | `arranque: passed:true`, tablero v1 | Entorno operativo; frontend → APIs → Mongo OK |
| **Restricciones SQL y rollback** | 12:23:52 | `logs/02-sql-restricciones-rollback.txt` | `ANTES t` → `DENTRO DE TRANSACCION f` → `DESPUES DE ROLLBACK t`; `ERROR duplicate key … "memberships_pkey"` `(board-1, ana)`; `ERROR … foreign key "memberships_user_id_fkey"` `usuario-inexistente` | **ROLLBACK** deshace la revocación completa (atomicidad). La **PK compuesta** impide dos membresías para el mismo par (no hay permisos ambiguos). La **FK** impide membresías de usuarios inexistentes (no hay permisos huérfanos). Errores esperados: no se eliminaron restricciones |
| Inspección Mongo/Redis | 12:23:53 | `logs/03-inspeccion-mongo-redis.txt` | Documento `{_id, preferences:{background}, title, version:1}`; Redis sin claves | Preferencias embebidas; Redis vacío tras reset (dato efímero) |
| **Baseline (antes)** | 12:24:04 – 12:24:27 | `json/antes-baseline-20261031T122427Z.json`, `logs/04-baseline.txt` | Concurrentes `[200, 200]`, v1→**v3**, título «Cambio de luis»; revocado: caché `can_edit:true`, PUT **200**, título «Cambio prohibido»; presencia a los 22 s **sigue** `["ana"]`. Exit 0 | Tres defectos reproducidos: edición perdida, autorización con caché obsoleta, presencia sin TTL |
| Redis detenido (antes) | 12:24:35 – 12:24:43 | `json/antes-redis-down-20261031T122443Z.json`, `logs/05-base-redis-down.txt` | Edición 200, presencia **503** «implementar degradación» | Una capacidad opcional (presencia) se convertía en error técnico |
| Autoridad detenida (antes) | 12:24:48 – 12:24:57 | `json/antes-authority-down-20261031T122456Z.json`, `logs/06-base-authority-down.txt` | Gestión detenida, permiso de Ana en caché → PUT **200** | La caché ocultaba la caída de la autoridad: escritura aceptada sin poder validarla |
| Dos pestañas (antes) | 12:25:13 | `capturas/antes-exp1-pestana1-ana.png`, `capturas/antes-exp1-pestana2-luis.png` | Ambas pestañas **HTTP 200**; queda «Cambio de Luis», **versión 3** | El cambio de Ana se perdió silenciosamente |
| **Carga k6 (antes)** | 12:25:20 – 12:27:00 | `json/antes-k6-carga-summary.json`, `logs/07-k6-carga-base.txt`, `capturas/grafana-02-k6-base.png` | 2000 req, 19,98 req/s, P95 **7,35 ms**, fallos 0 %, checks 100 %, `semantic_errors=0` | Umbrales cumplidos con holgura (solo lecturas) |
| — Se aplican los TODO 1-3 y `docker compose restart content` | ≈ 12:27:20 | commit `719d3b6` | | |
| **Acceptance corregido** | 12:27:32 – 12:28:26 | `json/despues-acceptance-20261031T122755Z.json`, `json/despues-acceptance-20261031T122826Z.json`, `logs/08-acceptance.txt` | 4/4 `passed:true`; concurrentes **[200, 409]**, v1→v2; revocado **403**, documento v1 intacto; presencia expira a los 22 s; **exit 0** | Los tres contratos se cumplen |
| Dos pestañas (después) | 12:28:45 – 12:28:46 | `capturas/despues-exp1-pestana1-ana.png`, `capturas/despues-exp1-pestana2-luis.png` | Pestaña 1 (Ana) **200** v2; pestaña 2 (Luis, versión 1 leída) **409** «Versión obsoleta… recargue» | El 409 es un **rechazo de negocio correcto**: el servidor está sano y protege el cambio de Ana. No es 5xx y no cuenta en errores técnicos |
| Revocación vs caché (después) | UI 12:28:48 – 12:28:50 · CLI 12:29:26 – 12:29:27 | `capturas/despues-revocacion-{1,2,3}-*.png`, `logs/09-revocacion-vs-cache.txt` | Tras revocar: Redis `GET permission:board-1:luis = 1`, `TTL 60`, la UI aún muestra `can_edit:true`, pero el PUT de Luis → **403** y el tablero queda en v1; PostgreSQL `luis f` | La escritura usa la autoridad; la caché solo afecta la UI |
| Presencia con TTL (después) | UI 12:28:52 – 12:29:15 · CLI 12:29:40 – 12:29:50 | `capturas/despues-presencia-{1,2,3}-*.png`, `logs/10-presencia-ttl.txt` | `available:true, ttl_seconds:20`; `TTL` 20 → 15 → heartbeat → **20**; 22 s después `users: []` | `SET … EX 20` en una sola escritura; el heartbeat renueva |
| **Redis detenido y recuperación** | 12:29:51 – 12:31:09 | `json/despues-redis-down-20261031T123004Z.json`, `logs/11-exp2-redis-down.txt`, `capturas/despues-exp2-redis-down-{edicion,presencia}.png`, `capturas/grafana-03-exp2-redis-down.png` | `degradacion_redis passed:true`: edición **200**, presencia **200 `{"available":false}`**; `lab_dependency_up{redis}=0`, `up{content}=1`; `lab_degraded_total{presence}=13`; `GET /permissions` sigue 200 vía Gestión. Restaurado: `PONG` y acceptance 4/4, exit 0 | Degradación controlada: se pierde solo la presencia; la edición sigue. `up=1` no significaba que Redis estuviera disponible |
| **Autoridad detenida y recuperación** | 12:31:21 – 12:32:24 | `json/despues-authority-down-20261031T123132Z.json`, `logs/12-exp3-authority-down.txt`, `capturas/despues-exp3-cache-primada.png`, `capturas/despues-exp3-authority-down-503.png`, `capturas/grafana-04-exp3-authority-down.png` | Caché de Ana `1` (TTL 59) y Gestión detenida → PUT **503** «No se puede validar el permiso; escritura no autorizada»; documento sin cambios. Restaurado: health 200, PUT 200 y acceptance 4/4, exit 0 | Indisponibilidad **deliberada** de la escritura (fail-closed). El 503 aparece en el panel de 5xx porque es una falla técnica real de una dependencia, no un rechazo de negocio |
| **Carga k6 (después)** | 12:32:53 – 12:34:33 | `json/despues-k6-carga-summary.json`, `logs/13-k6-carga-solucion.txt`, `capturas/grafana-05-k6-solucion.png` | 1995 req, 19,92 req/s, P95 **7,92 ms**, fallos 0 %, checks 100 %, `semantic_errors=0` | Sin cambio material: la carga es de lecturas y las correcciones tocan escritura/presencia (+0,6 ms está dentro del ruido de una sola corrida) |
| P95 del backend en las ventanas k6 | — | `logs/14-prometheus-p95-ventanas-k6.txt` | content ≈ **4,9 ms** (antes) y **5,0 ms** (después); management ≈ 24 ms | Ver respuesta 4 de observabilidad |

### Comparación k6 (antes / después)

| Métrica (k6, `TYPE=carga`, 5 VU, 100 s) | Base | Solución |
|---|---:|---:|
| Solicitudes | 2000 | 1995 |
| Tasa | 19,98 req/s | 19,92 req/s |
| P95 `http_req_duration` | 7,35 ms | 7,92 ms |
| P90 / mediana | 6,25 / 3,73 ms | 6,85 / 4,52 ms |
| Máximo | 51,8 ms | 69,4 ms |
| `http_req_failed` | 0 % | 0 % |
| `checks` | 100 % (4000/4000) | 100 % (3990/3990) |
| `semantic_errors` | 0 | 0 |
| P95 backend `content` (Prometheus) | ≈ 4,9 ms | ≈ 5,0 ms |

Umbrales didácticos (`P95 < 500 ms`, errores < 1 %, checks > 99 %, `semantic_errors == 0`): **cumplidos en ambas corridas**. Recursos: la máquina estuvo prácticamente ociosa (5 VU con 0,2 s de pausa no la saturan); no se ejecutaron estrés/pico/resistencia por ser opcionales.

## Observabilidad

Dashboard **ARSW-EQP-XX · Persistencia** (carpeta ARSW), exportado en [`dashboard.json`](dashboard.json) con el UID de la fuente `prometheus`. Conserva los 2 paneles iniciales y añade los 6 obligatorios + 2 opcionales:

| # | Panel | PromQL | Unidad |
|---|---|---|---|
| 1 | Servicios observables (inicial) | `up{job=~"content\|management"}` | 0/1 |
| 2 | Solicitudes por segundo (inicial) | `sum by (service) (rate(lab_http_requests_total[1m]))` | req/s |
| 3 | P95 por servicio | `histogram_quantile(0.95, sum by (le, service) (rate(lab_http_duration_seconds_bucket[1m])))` | s |
| 4 | Errores técnicos 5xx | `sum by (service) (rate(lab_http_requests_total{status=~"5.."}[1m]))` | req/s |
| 5 | Dependencias (state timeline) | `lab_dependency_up` | 1/0 |
| 6 | Aciertos de caché | `sum(rate(lab_cache_total{result="hit"}[1m])) / clamp_min(sum(rate(lab_cache_total{result=~"hit\|miss"}[1m])), 0.000001)` | 0–1 |
| 7 | Conflictos de edición | `sum(rate(lab_conflicts_total[1m]))` | conflictos/s |
| 8 | Presencia degradada | `sum(rate(lab_degraded_total{feature="presence"}[1m]))` | ops/s |
| 9 | Respuestas por código (opcional) | `sum by (service,status) (rate(lab_http_requests_total[1m]))` | req/s |
| 10 | Disponibilidad técnica observada (opcional) | `1 - (sum(rate(…{status=~"5.."}[1m])) or vector(0)) / clamp_min(sum(rate(…[1m])), 0.000001)` | 0–1 |

Capturas (ventana absoluta visible en la esquina superior derecha):

- `grafana-01-sesion-completa.png` (12:23–12:36): los dos picos de ~24 req/s son las corridas k6; `up` de management cae dos veces (detenciones deliberadas); conflictos solo aparecen **después** de la corrección; presencia degradada solo durante Redis detenido.
- `grafana-02-k6-base.png`, `grafana-05-k6-solucion.png`: ventanas de carga.
- `grafana-03-exp2-redis-down.png`: `content → redis` en rojo 12:30:00–12:30:45, `up` en 1, presencia degradada ≈ 0,21 ops/s, 0 errores 5xx, hit ratio cae a 0.
- `grafana-04-exp3-authority-down.png`: `content → management` en rojo y `management → postgres` **sin datos** (Gestión no puede ser scrapeada), 5xx de content ≈ 0,1 req/s (los 503 deliberados) y disponibilidad técnica baja a ~70 %.

### Cuatro respuestas obligatorias

**1. ¿Por qué puede subir el contador de conflictos mientras baja la pérdida de cambios?**
Porque son la misma cosa vista desde dos lados. Antes de la corrección, cuando dos clientes editaban la misma versión ambos recibían 200 y uno sobrescribía al otro: la pérdida existía pero era **invisible** (en `grafana-01` el panel de conflictos está en 0 durante el baseline de las 12:24, aunque el baseline perdió un cambio). Con el compare-and-set cada colisión que antes era una pérdida silenciosa se convierte en un **409 contado** en `lab_conflicts_total` (picos de ~0,036/s a partir de las 12:27). Más conflictos = más carreras detectadas y rechazadas = menos ediciones perdidas. Un 409 no es falla del servidor: no aparece en el panel de 5xx.

**2. ¿Por qué el panel de caché no demuestra que una escritura fue autorizada correctamente?**
El panel mide la fracción `hit/(hit+miss)` de `cached_permission`, que solo se usa para `GET /permissions` (UI). Después del TODO 2 las escrituras no pasan por la caché, sino por Gestión; un 100 % de aciertos podría estar sirviendo un permiso **revocado** (lo vimos: `permission:board-1:luis = 1` con TTL 60 mientras PostgreSQL decía `f`). El panel no sabe si el valor es vigente ni qué decisión se tomó con él. La corrección de la autorización se demuestra con el escenario `permiso_revocado` (403, documento intacto) y con el 503 de `authority-down`, no con métricas de caché.

**3. ¿Qué ve Grafana cuando Redis cae, pero la API sigue contestando 200?**
En `grafana-03`: `up{job="content"}` sigue en **1** (Prometheus puede leer `/metrics`), `lab_dependency_up{dependency="redis"}` pasa a **0** (franja roja), los 5xx siguen en **0** porque edición y presencia responden 200, y el panel **Presencia degradada** sube (≈ 0,2 ops/s; `lab_degraded_total` llegó a 13). La única forma de ver que la funcionalidad está reducida es con las métricas de dependencia y degradación: `up` y el código HTTP no lo muestran. Por eso `up` ≠ disponibilidad funcional.

**4. ¿Por qué el P95 de k6 y el P95 del backend no tienen necesariamente el mismo valor?**
- **Qué miden:** k6 mide el recorrido completo del cliente (red Docker, **Nginx** como proxy, serialización, cola en el cliente); el backend mide solo el tiempo dentro del middleware de FastAPI.
- **Cómo se calcula:** k6 calcula el percentil exacto sobre cada muestra; Prometheus lo **estima** con `histogram_quantile` interpolando dentro de buckets fijos (`5 ms, 10 ms, 25 ms…`). Aquí casi todo cae en el primer bucket (≤ 5 ms), así que el estimado (≈ 4,9 ms) está acotado por la forma del bucket.
- **Qué incluye:** el backend agrega todas las rutas y fuentes de tráfico de la ventana (sondeos de permisos hacia Gestión, acceptance, ediciones con llamada a la autoridad, que cuestan 40–80 ms), mientras k6 solo mide sus `GET`. Fuera de las ventanas de carga el P95 de content sube a 40–80 ms porque domina ese tráfico de edición, no porque el sistema esté más lento.
- **Ventana:** `rate(...[1m])` suaviza; k6 resume toda la corrida.

Resultado: k6 **7,35 / 7,92 ms** vs backend **≈ 4,9 / 5,0 ms**; la diferencia (~2,5–3 ms) es el costo de Nginx + red + cliente.

## Problemas pendientes

- **No hay fallas sin resolver en los contratos evaluados**: acceptance, redis-down y authority-down pasan (exit 0) y se restauraron Redis y Gestión.
- **Ventana validar→escribir** de la revocación: limitación de diseño documentada en el ADR; no se probó porque ninguna prueba la ejercita.
- **UI con permiso desactualizado** hasta 60 s después de revocar (la escritura igual se rechaza). Mejora propuesta: invalidación por evento.
- **Entorno de construcción:** en nuestra máquina `pip install` dentro del `docker build` falló por un proxy HTTPS con certificado propio (`CERTIFICATE_VERIFY_FAILED`), y Docker Hub devolvió `429 Too Many Requests` en el primer `pull`. Se resolvió descargando las imágenes una a una y construyendo `arsw-persistencia-api:local` con el certificado del proxy **solo localmente**, sin modificar el `Dockerfile` ni el `compose.yaml` del repositorio; luego `docker compose up -d --no-build --wait`.
- Las capturas de la UI se tomaron con Chromium sin interfaz (Playwright); cada una lleva un sello con la hora UTC en la esquina superior derecha.
