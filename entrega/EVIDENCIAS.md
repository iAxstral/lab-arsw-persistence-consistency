# Evidencias · ARSW-EQP-XX

Todas las horas están en UTC, el 31 de octubre de 2026. Para cada paso dejamos tres cosas: la captura, la salida completa del comando en `evidencias/logs/` y, cuando la herramienta lo genera, el JSON en `evidencias/json/`. A los JSON les pusimos el prefijo `antes-` si se tomaron con el código original y `despues-` si se tomaron con nuestros cambios.

## Entorno

- Linux x86_64 (VM), Intel Xeon @ 2.10 GHz, 4 vCPU y 16 GB de RAM. Docker Engine corre nativo, sin un límite de memoria aparte; con todo el Compose arriba se usaba más o menos 1 GB.
- Docker Engine 29.9.2 y Docker Compose v5.6.1, que soporta `--wait`.
- Imágenes: postgres 16.6-alpine, mongo 7.0.16, redis 7.4.2-alpine, nginx 1.27.3-alpine, prometheus v3.1.0, grafana 11.5.1, k6 0.57.0 y la API sobre python 3.12-slim.

![Entorno](evidencias/capturas/terminal-00-entorno.png)

## Resumen

| Experimento | Hora (UTC) | Evidencia | Resultado | Lectura |
|---|---|---|---|---|
| Smoke | 12:23:52 | `terminal-01-smoke.png`, `json/smoke-*.json` | `arranque: passed:true`, tablero en v1 | El entorno responde de punta a punta |
| Restricciones SQL y rollback | 12:23:52 | `terminal-02-sql-restricciones-rollback.png` | El rollback deshace la revocación; la PK y la FK rechazan los dos INSERT | PostgreSQL protege la integridad de los permisos |
| Baseline (antes) | 12:24:04 – 12:24:27 | `terminal-04-baseline.png`, `json/antes-baseline-*.json` | `[200, 200]` en concurrencia, 200 con permiso revocado, la presencia no expira | Los tres defectos se reproducen |
| Redis detenido (antes) | 12:24:35 – 12:24:43 | `terminal-05-base-redis-down.png` | La presencia responde 503 | La presencia, que es opcional, rompía la respuesta |
| Gestión detenida (antes) | 12:24:48 – 12:24:57 | `terminal-06-base-authority-down.png` | La escritura se acepta (200) usando la caché | Se escribía sin poder validar el permiso |
| Dos pestañas (antes) | 12:25:12 – 12:25:13 | `antes-exp1-*.png` | 200 y 200, queda la versión 3 | El cambio de Ana se pierde |
| k6 (antes) | 12:25:20 – 12:27:00 | `terminal-07-k6-carga-base.png`, `grafana-02-k6-base.png` | P95 7,35 ms, 0 % fallos | Línea base de rendimiento |
| Acceptance (después) | 12:27:32 – 12:28:26 | `terminal-08-acceptance.png`, `json/despues-acceptance-*.json` | 4/4 `passed:true`, exit 0 | Los tres contratos se cumplen |
| Dos pestañas (después) | 12:28:45 – 12:28:46 | `despues-exp1-*.png` | 200 y 409 | El conflicto se detecta y no se pierde nada |
| Revocación vs caché | 12:28:48 – 12:29:27 | `despues-revocacion-*.png`, `terminal-09-revocacion-vs-cache.png` | La caché sigue en 1, pero la escritura da 403 | La escritura se autoriza contra PostgreSQL |
| Presencia con TTL | 12:28:52 – 12:29:50 | `despues-presencia-*.png`, `terminal-10-presencia-ttl.png` | TTL 20 que se renueva; a los 22 s ya no aparece | TTL en una sola escritura |
| Redis detenido y recuperación | 12:29:51 – 12:31:09 | `despues-exp2-*.png`, `terminal-11-exp2-redis-down.png`, `grafana-03-*.png` | Edición 200, presencia 200 con `available:false` | Degradación controlada |
| Gestión detenida y recuperación | 12:31:21 – 12:32:24 | `despues-exp3-*.png`, `terminal-12-exp3-authority-down.png`, `grafana-04-*.png` | Escritura 503 aunque haya caché | Se cierra por seguridad (fail-closed) |
| k6 (después) | 12:32:53 – 12:34:33 | `terminal-13-k6-carga-solucion.png`, `grafana-05-k6-solucion.png` | P95 7,92 ms, 0 % fallos | Sin cambio relevante en lecturas |

---

## 1. Arranque y recorrido

Levantamos el entorno con `docker compose up -d --wait` (lo del build está en «Problemas pendientes») y revisamos en Prometheus (`/targets`) que `content` y `management` estuvieran en `up`. Luego corrimos el smoke, que devolvió el tablero en la versión 1.

![Smoke](evidencias/capturas/terminal-01-smoke.png)

## 2. Bloque A: restricciones de PostgreSQL

Corrimos `evidence.sql` dentro del contenedor, con `-a` para que cada sentencia saliera impresa junto a su resultado:

```sh
docker compose exec -T postgres psql -U lab -d boards -a -f /lab/evidence.sql
```

![SQL](evidencias/capturas/terminal-02-sql-restricciones-rollback.png)

Esto es lo que vimos:

- **Rollback.** Luis aparece con `can_edit = t`. Dentro de la transacción pasa a `f` y después del `ROLLBACK` vuelve a `t`. La revocación se aplica completa o no se aplica.
- **Clave primaria `(board_id, user_id)`.** Insertar otra vez `(board-1, ana)` falla con `duplicate key value violates unique constraint "memberships_pkey"`. No pueden existir dos filas de permiso contradictorias para el mismo usuario y tablero.
- **Clave foránea hacia `users`.** Insertar `usuario-inexistente` falla con `violates foreign key constraint "memberships_user_id_fkey"`. No quedan permisos huérfanos.

Los dos errores son los esperados y no quitamos ninguna restricción. También revisamos el documento en Mongo y las claves de Redis: el tablero tiene las preferencias embebidas y Redis estaba vacío después del reset.

![Inspección](evidencias/capturas/terminal-03-inspeccion-mongo-redis.png)

## 3. Bloque B: baseline antes de tocar el código

Antes de cambiar nada corrimos `docker compose run --rm tools baseline`. Tardó unos 22 s por la prueba de expiración.

![Baseline](evidencias/capturas/terminal-04-baseline.png)

Salieron los tres defectos:

1. **Ediciones concurrentes:** `statuses: [200, 200]` y la versión pasó de 1 a 3, con el título «Cambio de luis». El cambio de Ana se perdió sin que nadie lo notara.
2. **Permiso revocado:** la caché tenía `can_edit: true`, el PUT de Luis devolvió 200 y el tablero quedó como «Cambio prohibido».
3. **Presencia:** 22 s después Ana seguía apareciendo, porque la clave no tenía expiración.

Para tener el "antes" de los experimentos de falla también los corrimos con el código original. Con Redis detenido, la presencia devolvió **503**:

![Redis caído, base](evidencias/capturas/terminal-05-base-redis-down.png)

Con Gestión detenida y el permiso de Ana en caché, la escritura se aceptó (**200**). Es justo lo que no debería pasar:

![Gestión caída, base](evidencias/capturas/terminal-06-base-authority-down.png)

### Dos pestañas con el código original

Abrimos el frontend en dos pestañas y cargamos la versión 1 en ambas. En la segunda cambiamos a Luis. Guardamos primero en la pestaña 1 y después en la 2. Las dos respondieron 200 y el tablero quedó con el cambio de Luis en la versión 3.

| Pestaña 1 (Ana) | Pestaña 2 (Luis) |
|---|---|
| ![](evidencias/capturas/antes-exp1-pestana1-ana.png) | ![](evidencias/capturas/antes-exp1-pestana2-luis.png) |

### Carga k6 con el código original

Medimos la carga en este punto para poder comparar después. Guardamos el resumen como `antes-k6-carga-summary.json` antes de que la siguiente corrida lo sobrescribiera.

![k6 base](evidencias/capturas/terminal-07-k6-carga-base.png)

## 4. Los tres TODO

Los cambios están todos en `services/content/decisions.py`, en el commit `719d3b6`:

- **TODO 1 `save_board`:** pusimos `version: expected_version` en el filtro de `find_one_and_update`. Así la comparación y el `$inc` ocurren en la misma operación atómica sobre el documento. Si otra persona ya cambió la versión, la función devuelve `None` y la API responde 409.
- **TODO 2 `permission_for_write`:** las escrituras usan `authoritative_permission`, es decir Gestión/PostgreSQL, y no la caché. Si Gestión no responde, la excepción 503 se propaga y no se guarda nada.
- **TODO 3 `touch_presence`:** `client.set(key, 'online', ex=ttl)` deja valor y expiración en una sola escritura. Si hay un `RedisError` devuelve `False` y la API responde 200 con `available:false`.

Reiniciamos `content` con `docker compose restart content` y corrimos acceptance:

![Acceptance](evidencias/capturas/terminal-08-acceptance.png)

Los cuatro tests salieron en `passed: true` con código de salida 0. En concurrencia el resultado fue `[200, 409]` con la versión de 1 a 2, y la revocación dio 403 con el documento intacto. En total acceptance se corrió cuatro veces (12:27:55, 12:28:26, 12:31:09 y 12:32:24), siempre 4/4.

## 5. Bloque C: experimentos

### Experimento 1: dos pestañas

Repetimos el mismo procedimiento con el código corregido. Ana guarda y obtiene 200 con la versión 2. Luis, que todavía tenía la versión 1, recibe **409** «Versión obsoleta o tablero inexistente: recargue antes de editar».

| Pestaña 1 (Ana): 200 | Pestaña 2 (Luis): 409 |
|---|---|
| ![](evidencias/capturas/despues-exp1-pestana1-ana.png) | ![](evidencias/capturas/despues-exp1-pestana2-luis.png) |

Un 409 no es una caída del servidor. El servidor está bien: rechaza a propósito una edición basada en datos viejos para no borrar lo que guardó Ana. Por eso no aparece en el panel de errores 5xx, sino en el de conflictos.

### Revocación frente a caché

Desde la interfaz consultamos el permiso de Luis, que quedó en caché. Luego lo revocamos desde «Administración del escenario» e intentamos guardar como Luis:

| 1. Permiso en caché | 2. Revocación confirmada | 3. Escritura rechazada |
|---|---|---|
| ![](evidencias/capturas/despues-revocacion-1-cache.png) | ![](evidencias/capturas/despues-revocacion-2-revocado.png) | ![](evidencias/capturas/despues-revocacion-3-403.png) |

Para confirmar que la caché seguía desactualizada lo repetimos por terminal. Redis todavía tenía `permission:board-1:luis = 1` con TTL 60 y `GET /permissions` seguía diciendo `can_edit: true`. Aun así el PUT devolvió **403**, el tablero siguió en la versión 1 y PostgreSQL mostraba `luis | f`.

![Revocación vs caché](evidencias/capturas/terminal-09-revocacion-vs-cache.png)

### Presencia con TTL

Registramos la presencia de Ana, la consultamos de inmediato y volvimos a consultarla 22 s después sin heartbeat. Ya no aparecía.

| Registro | Inmediatamente | 22 s después |
|---|---|---|
| ![](evidencias/capturas/despues-presencia-1-registro.png) | ![](evidencias/capturas/despues-presencia-2-activa.png) | ![](evidencias/capturas/despues-presencia-3-expirada.png) |

En Redis el TTL bajó de 20 a 15 y, después de un nuevo heartbeat, volvió a 20:

![TTL](evidencias/capturas/terminal-10-presencia-ttl.png)

### Experimento 2: Redis detenido

Seguimos los pasos del README: `tools reset`, `docker compose stop redis`, `tools redis-down` y `docker compose start redis`. Mientras Redis estuvo abajo mandamos unos heartbeats más para que el panel de degradación tuviera datos.

![Redis caído](evidencias/capturas/terminal-11-exp2-redis-down.png)

`degradacion_redis` salió en `passed: true`: la edición respondió 200 y la presencia 200 con `{"available":false}`. En las métricas de content quedó `lab_dependency_up{redis}=0` y `lab_degraded_total{presence}=13`, mientras `up` de content y management seguía en 1. Al restaurar, `redis-cli ping` respondió `PONG` y acceptance volvió a dar 4/4 con exit 0. Lo mismo desde la interfaz:

| Edición con Redis caído: 200 | Presencia con Redis caído: 200 degradada |
|---|---|
| ![](evidencias/capturas/despues-exp2-redis-down-edicion.png) | ![](evidencias/capturas/despues-exp2-redis-down-presencia.png) |

### Experimento 3: autoridad de permisos no disponible

Con Redis y Gestión arriba consultamos el permiso de Ana con «Consultar permiso en caché», y luego detuvimos Gestión:

| Permiso de Ana en caché | Escritura con Gestión detenida: 503 |
|---|---|
| ![](evidencias/capturas/despues-exp3-cache-primada.png) | ![](evidencias/capturas/despues-exp3-authority-down-503.png) |

![Gestión caída](evidencias/capturas/terminal-12-exp3-authority-down.png)

Aunque Redis tenía `permission:board-1:ana = 1`, `authority-down` dio **503** y el documento no cambió. Restauramos con `docker compose start management`: el health respondió 200, una edición válida volvió a dar 200 y acceptance dio 4/4.

**Lo que degradó de forma controlada** fue la presencia, con Redis caído. **Lo que dejó de estar disponible a propósito** fue la edición, con Gestión caída. **La garantía detrás** es que nunca se acepta una escritura que no se pudo autorizar contra la fuente real. **Si la que falla es MongoDB**, no hay dónde leer ni escribir el contenido, así que lectura y edición responden 503. La presencia y los permisos siguen funcionando, pero sin el tablero no sirven de mucho.

## 6. Bloque D: Prometheus, Grafana y k6

### Dashboard

Duplicamos «ARSW · Punto de partida» como **ARSW-EQP-XX · Persistencia** en la carpeta ARSW. Mantuvimos los dos paneles iniciales y agregamos los seis de `OBSERVABILIDAD.md` más dos opcionales: respuestas por código y disponibilidad técnica. El export completo está en [`dashboard.json`](dashboard.json) y conserva el UID `prometheus` de la fuente.

| # | Panel | PromQL |
|---|---|---|
| 1 | Servicios observables (inicial) | `up{job=~"content\|management"}` |
| 2 | Solicitudes por segundo (inicial) | `sum by (service) (rate(lab_http_requests_total[1m]))` |
| 3 | P95 por servicio | `histogram_quantile(0.95, sum by (le, service) (rate(lab_http_duration_seconds_bucket[1m])))` |
| 4 | Errores técnicos 5xx | `sum by (service) (rate(lab_http_requests_total{status=~"5.."}[1m]))` |
| 5 | Dependencias | `lab_dependency_up` |
| 6 | Aciertos de caché | `sum(rate(lab_cache_total{result="hit"}[1m])) / clamp_min(sum(rate(lab_cache_total{result=~"hit\|miss"}[1m])), 0.000001)` |
| 7 | Conflictos de edición | `sum(rate(lab_conflicts_total[1m]))` |
| 8 | Presencia degradada | `sum(rate(lab_degraded_total{feature="presence"}[1m]))` |
| 9 | Respuestas por código (opcional) | `sum by (service,status) (rate(lab_http_requests_total[1m]))` |
| 10 | Disponibilidad técnica (opcional) | `1 - (sum(rate(…{status=~"5.."}[1m])) or vector(0)) / clamp_min(sum(rate(…[1m])), 0.000001)` |

Vista de toda la sesión (12:23–12:36). Se ven las dos corridas de k6 como picos de unos 24 req/s, las dos veces que detuvimos Gestión en el panel `up`, y los conflictos y la presencia degradada solo después de los cambios:

![Grafana sesión](evidencias/capturas/grafana-01-sesion-completa.png)

Redis detenido (12:29:30–12:31:30). La franja `content → redis` se pone en rojo mientras `up` sigue en 1, los 5xx no tienen datos (no hubo ninguno), sube la presencia degradada y el hit ratio de caché cae a 0:

![Grafana Redis](evidencias/capturas/grafana-03-exp2-redis-down.png)

Gestión detenida (12:31:00–12:32:45). `content → management` en rojo, `management → postgres` sin datos porque Gestión no se podía scrapear, los 503 en el panel de 5xx y la disponibilidad técnica bajando a cerca de 70 %:

![Grafana Gestión](evidencias/capturas/grafana-04-exp3-authority-down.png)

### k6 antes y después

Corrimos `docker compose run --rm k6` dos veces: una con el código original y otra con la solución. Renombramos el resumen después de cada corrida para no perderlo.

![k6 solución](evidencias/capturas/terminal-13-k6-carga-solucion.png)

| Antes | Después |
|---|---|
| ![](evidencias/capturas/grafana-02-k6-base.png) | ![](evidencias/capturas/grafana-05-k6-solucion.png) |

![Comparación k6](evidencias/capturas/terminal-15-k6-comparacion.png)

| Métrica (k6 `carga`, 5 VU, 100 s) | Antes | Después |
|---|---:|---:|
| Solicitudes | 2000 | 1995 |
| Tasa | 19,98 req/s | 19,92 req/s |
| P95 | 7,35 ms | 7,92 ms |
| P90 / mediana | 6,25 / 3,73 ms | 6,85 / 4,52 ms |
| Máximo | 51,8 ms | 69,4 ms |
| `http_req_failed` | 0 % | 0 % |
| `checks` | 100 % (4000/4000) | 100 % (3990/3990) |
| `semantic_errors` | 0 | 0 |
| P95 backend `content` (Prometheus) | ≈ 4,9 ms | ≈ 5,0 ms |

Se cumplieron todos los umbrales del script (P95 < 500 ms, errores < 1 %, checks > 99 %, `semantic_errors == 0`). La diferencia de unos 0,6 ms entre corridas está dentro del ruido: la carga es solo de lecturas y nuestros cambios tocan la escritura y la presencia. Con 5 VU la máquina casi no trabajó. No corrimos estrés, pico ni resistencia porque eran opcionales.

El P95 del backend lo sacamos de Prometheus sobre la ventana exacta de cada corrida:

![P95 Prometheus](evidencias/capturas/terminal-14-prometheus-p95-ventanas-k6.png)

### Las cuatro preguntas

**1. ¿Por qué puede subir el contador de conflictos mientras baja la pérdida de cambios?**
Porque son el mismo evento visto desde dos lados. Con el código original, cuando dos personas editaban la misma versión las dos recibían 200 y una pisaba a la otra. La pérdida existía pero no se veía: en la captura de la sesión el panel de conflictos está en 0 durante el baseline de las 12:24, aunque ese baseline perdió un cambio. Con el control de versiones, cada choque que antes era una pérdida silenciosa ahora es un 409 que se cuenta en `lab_conflicts_total`. Por eso aparecen los picos desde las 12:27. Más conflictos contados significa menos cambios perdidos.

**2. ¿Por qué el panel de caché no demuestra que una escritura fue autorizada correctamente?**
El panel solo mide qué fracción de las lecturas de `cached_permission` encontró el dato en Redis, y esas lecturas ahora solo alimentan la UI. Las escrituras ya no pasan por ahí. Además, un acierto de caché puede ser un permiso viejo: lo vimos con Luis, que tenía `1` en Redis mientras PostgreSQL decía `f`. Que el permiso se aplicó bien se demuestra con el 403 de la revocación y el 503 con Gestión caída, no con el hit ratio.

**3. ¿Qué ve Grafana cuando Redis cae, pero la API sigue contestando 200?**
`up` de content sigue en 1, porque Prometheus puede leer `/metrics`, y no hay 5xx. Lo que delata el problema es `lab_dependency_up{dependency="redis"}` en 0 y el panel de presencia degradada subiendo hasta unas 0,2 ops/s. Mirando solo `up` o solo los códigos HTTP parecería que todo está bien, cuando en realidad la presencia no funciona.

**4. ¿Por qué el P95 de k6 y el P95 del backend no tienen necesariamente el mismo valor?**
k6 mide el viaje completo del cliente: la red de Docker, Nginx como proxy y el propio cliente. El backend mide solo el tiempo dentro de FastAPI. k6 calcula el percentil exacto sobre cada muestra, mientras que Prometheus lo estima interpolando dentro de buckets fijos (5, 10, 25 ms…). Aquí casi todo cayó en el primer bucket, así que el estimado de unos 4,9 ms depende mucho de cómo están definidos los buckets. Además, el histograma del backend mezcla todo el tráfico de la ventana, incluidas las ediciones que llaman a Gestión y tardan 40–80 ms, mientras que k6 solo mide sus GET. Por eso fuera de las corridas de carga el P95 de content sube a 40–80 ms. En nuestras corridas k6 dio 7,35 y 7,92 ms y el backend unos 4,9 y 5,0 ms; la diferencia es básicamente Nginx, la red y el cliente.

## Problemas pendientes

- Ninguna de las pruebas pedidas quedó fallando: acceptance, redis-down y authority-down pasan con exit 0, y Redis y Gestión quedaron restaurados.
- La ventana entre validar el permiso y escribir (una revocación que llega justo en medio) sigue abierta por diseño. Está explicada en el ADR y ninguna prueba la cubre.
- La UI puede seguir mostrando «puede editar» hasta 60 s después de una revocación, aunque la escritura se rechace. Una mejora sería invalidar la caché cuando Gestión revoca.
- En el primer arranque Docker Hub respondió `429 Too Many Requests` al bajar varias imágenes a la vez, y el `pip install` del build falló por el certificado de un proxy HTTPS de la red. Lo resolvimos bajando las imágenes una por una y construyendo la imagen de la API con ese certificado solo en local, sin tocar el `Dockerfile` ni el `compose.yaml` del repositorio.
- Cada captura del frontend tiene la hora UTC en la esquina superior derecha. En las de Grafana la ventana de tiempo aparece en el selector de arriba.
