"""ÚNICO archivo de código que deben modificar los estudiantes.
Decisiones de consistencia, autorización y degradación del servicio de Contenido.
Ver entrega/ADR-001.md para la justificación de cada decisión.
"""
from pymongo import ReturnDocument
from redis.exceptions import RedisError


def save_board(collection, board_id, expected_version, title):
    """TODO 1 · Control optimista de versiones (compare-and-set atómico).

    El filtro incluye la versión que el cliente leyó. MongoDB evalúa el filtro y
    aplica `$set` + `$inc` sobre el mismo documento en UNA sola operación atómica,
    por lo que dos escrituras concurrentes con la misma `expected_version` no pueden
    ambas coincidir: la primera incrementa la versión y la segunda ya no encuentra
    el documento con esa versión -> devuelve None -> la API responde 409.

    No se hace find + update (lectura y escritura separadas reabrirían la carrera).
    """
    return collection.find_one_and_update(
        {'_id': board_id, 'version': expected_version},
        {'$set': {'title': title}, '$inc': {'version': 1}},
        return_document=ReturnDocument.AFTER,
    )


def permission_for_write(user, board_id, cached_permission, authoritative_permission):
    """TODO 2 · Las escrituras se autorizan contra la fuente autoritativa.

    La caché de Redis (TTL 60 s) solo sirve para la interfaz (mostrar/ocultar
    controles). Una concesión cacheada no prueba que siga vigente después de una
    revocación confirmada, así que para una escritura se consulta siempre a
    Gestión/PostgreSQL. Si la autoridad no responde, `authoritative_permission`
    lanza HTTPException(503) y se deja propagar: nunca se transforma en un permiso
    concedido (fail-closed). Costo: una llamada HTTP extra por escritura y
    dependencia de Gestión para editar; se acepta porque editar es menos frecuente
    que leer y un permiso revocado es un riesgo de seguridad.

    Límite conocido: si la revocación ocurre DESPUÉS de esta validación y ANTES de
    guardar en MongoDB, la escritura se acepta (no hay transacción distribuida).
    Ver ADR-001, sección Consecuencias.
    """
    return authoritative_permission(user, board_id) is True


def touch_presence(client, key, ttl):
    """TODO 3 · Presencia efímera con TTL y degradación controlada.

    `SET key online EX ttl` registra la clave y su expiración en UNA única escritura
    atómica (no SET + EXPIRE, que podría dejar una clave sin TTL si falla el segundo
    comando). Cada heartbeat vuelve a ejecutar SET ... EX y renueva el TTL.

    Si Redis no responde se retorna False: la API contesta 200 con
    `available: false` e incrementa `lab_degraded_total{feature="presence"}`.
    Solo se capturan errores de Redis (RedisError); un error de programación
    debe seguir siendo visible.
    """
    try:
        return bool(client.set(key, 'online', ex=ttl))
    except RedisError:
        return False
