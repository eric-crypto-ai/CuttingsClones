"""
F2.5 — Refactor del cron de tareas recurrentes (in-place dentro de Control_IPM).

Cambios:
  1. Sustituye el `jsCode` del nodo `Filtrar y Generar1` por la versión que
     soporta `tipo_recurrencia` ∈ {semanal, mensual, cada_x_dias} con fallback
     legacy a `dia_recurrencia`.
  2. Añade el nodo `Update Ultima Generada` (Google Sheets `update`) que
     escribe `ultima_disparada=hoy` en cada plantilla que disparó. Imprescindible
     para que `cada_x_dias` funcione (sin esto, dispararía todos los días).
  3. Convierte la conexión `If → Crear Tareas1` en un fork:
     `If → [Crear Tareas1, Update Ultima Generada]` para que Update reciba los
     mismos N items con `_id_plantilla` que Crear Tareas1.

Idempotente: si el script se vuelve a ejecutar no duplica nodos ni conexiones.
"""
import json
import os
import sys
import urllib.error
import urllib.request

WORKFLOW_ID = "CPUlOabXvRrGIVjy"  # Control_IPM
N8N_URL = "https://primary-production-2cf7.up.railway.app/api/v1/workflows"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEET_RECURRENTES_GID = 1626272047
CREDENTIAL_ID = "U9MmYhXUgVdOQej5"  # Google Sheets account


NEW_JS_CODE = r"""// Cron Tareas Recurrentes — F2.5 (semanal | mensual | cada_x_dias)
// Capa de exclusividad agronómica por (categoria_exclusiva, zona).
// Fallback legacy: si tipo_recurrencia vacío, usa dia_recurrencia como semanal.
const ahora = DateTime.now().setZone('Europe/Madrid');
const fechaHoy = ahora.toFormat('yyyy-MM-dd');
const mapaDias = {1:'lunes',2:'martes',3:'miercoles',4:'jueves',5:'viernes',6:'sabado',7:'domingo'};
const diaSemana = mapaDias[ahora.weekday];
const diaMes = ahora.day;
const ultimoDiaMes = ahora.endOf('month').day;

const norm = s => String(s || '').trim().toLowerCase();
const splitCSV = s => String(s || '').split(',').map(x => x.trim().toLowerCase()).filter(Boolean);

const plantillas = $('Leer Plantillas1').all().map(i => i.json);
const tareasExistentes = $('Leer Tareas Existentes1').all().map(i => i.json);

function debeDisparar(p) {
  const tipo = norm(p.tipo_recurrencia);

  // Legacy: sin tipo_recurrencia → dia_recurrencia tratado como semanal
  if (!tipo) {
    return splitCSV(p.dia_recurrencia).includes(diaSemana);
  }

  if (tipo === 'semanal') {
    return splitCSV(p.config_recurrencia).includes(diaSemana);
  }

  if (tipo === 'mensual') {
    const dias = splitCSV(p.config_recurrencia)
      .map(d => parseInt(d, 10))
      .filter(n => !isNaN(n) && n >= 1 && n <= 31);
    if (dias.length === 0) return false;
    // Si día configurado > último del mes (p. ej. 31 en febrero) → último día
    const efectivos = dias.map(d => Math.min(d, ultimoDiaMes));
    return efectivos.includes(diaMes);
  }

  if (tipo === 'cada_x_dias') {
    const n = parseInt(String(p.config_recurrencia || '').trim(), 10);
    if (isNaN(n) || n < 1) return false;
    const ultima = String(p.ultima_disparada || '').trim();
    if (!ultima) return true; // primera vez
    const ultimaDt = DateTime.fromISO(ultima, { zone: 'Europe/Madrid' });
    if (!ultimaDt.isValid) return true;
    const diasTranscurridos = Math.floor(ahora.diff(ultimaDt, 'days').days);
    return diasTranscurridos >= n;
  }

  return false; // tipo desconocido → silencio
}

// 1. Filtrar por activa + día (semanal/mensual/cada_x_dias)
const plantillasHoy = plantillas.filter(p => norm(p.activa) === 'si' && debeDisparar(p));

if (plantillasHoy.length === 0) {
  return [{ json: { _skip: true, mensaje: `Sin plantillas para ${fechaHoy} (${diaSemana}, día ${diaMes})` } }];
}

// 2. Anti-duplicado: misma tarea+zona+fecha hoy y estado != hecha
const sinDuplicar = plantillasHoy.filter(p => {
  return !tareasExistentes.some(t =>
    norm(t.tarea) === norm(p.tarea) &&
    norm(t.zona) === norm(p.zona) &&
    String(t.fecha || '').trim() === fechaHoy &&
    norm(t.estado) !== 'hecha'
  );
});

if (sinDuplicar.length === 0) {
  return [{ json: { _skip: true, mensaje: `Todas las tareas para ${fechaHoy} ya existen` } }];
}

// 3. Exclusividad agronómica — por (categoria_exclusiva, zona)
// Plantillas con categoria_exclusiva vacía pasan sin filtro.
// En cada grupo, mantener solo prioridad máxima (alta>media>baja); empates pasan todos.
const ordenPrio = { alta: 3, media: 2, baja: 1 };
const conCategoria = sinDuplicar.filter(p => norm(p.categoria_exclusiva));
const sinCategoria = sinDuplicar.filter(p => !norm(p.categoria_exclusiva));

const grupos = new Map();
for (const p of conCategoria) {
  const key = `${norm(p.categoria_exclusiva)}|${norm(p.zona)}`;
  if (!grupos.has(key)) grupos.set(key, []);
  grupos.get(key).push(p);
}

const ganadores = [];
for (const arr of grupos.values()) {
  let maxPrio = 0;
  for (const p of arr) {
    const x = ordenPrio[norm(p.prioridad)] || 0;
    if (x > maxPrio) maxPrio = x;
  }
  for (const p of arr) {
    if ((ordenPrio[norm(p.prioridad)] || 0) === maxPrio) ganadores.push(p);
  }
}

const plantillasFinal = [...sinCategoria, ...ganadores];

if (plantillasFinal.length === 0) {
  return [{ json: { _skip: true, mensaje: `Sin plantillas tras exclusividad para ${fechaHoy}` } }];
}

// 4. Generar IDs incrementales y emitir items
let maxId = 0;
for (const t of tareasExistentes) {
  const id = parseInt(String(t.id || '').trim(), 10);
  if (!isNaN(id) && id > maxId) maxId = id;
}

return plantillasFinal.map((p, i) => ({
  json: {
    id: String(maxId + 1 + i),
    zona: p.zona || '',
    tarea: p.tarea || '',
    prioridad: p.prioridad || 'media',
    estado: 'pendiente',
    fecha: fechaHoy,
    recurrente: 'si',
    dia_recurrencia: p.dia_recurrencia || '',
    observaciones: p.observaciones || '',
    _id_plantilla: p.id_plantilla || ''
  }
}));
"""


def build_update_node(existing_position):
    """Nodo Google Sheets update: ultima_disparada=hoy donde id_plantilla coincide."""
    return {
        "parameters": {
            "operation": "update",
            "documentId": {
                "__rl": True,
                "value": SPREADSHEET_ID,
                "mode": "list",
                "cachedResultName": "Control_IPM",
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=drivesdk",
            },
            "sheetName": {
                "__rl": True,
                "value": SHEET_RECURRENTES_GID,
                "mode": "list",
                "cachedResultName": "tareas_recurrentes",
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={SHEET_RECURRENTES_GID}",
            },
            "columns": {
                "mappingMode": "defineBelow",
                "value": {
                    "id_plantilla": "={{ $json._id_plantilla }}",
                    "ultima_disparada": "={{ $now.setZone('Europe/Madrid').toFormat('yyyy-MM-dd') }}",
                },
                "matchingColumns": ["id_plantilla"],
                "schema": [
                    {"id": "id_plantilla", "displayName": "id_plantilla", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "zona", "displayName": "zona", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "tarea", "displayName": "tarea", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "prioridad", "displayName": "prioridad", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "activa", "displayName": "activa", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "dia_recurrencia", "displayName": "dia_recurrencia", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "observaciones", "displayName": "observaciones", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "tipo_recurrencia", "displayName": "tipo_recurrencia", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "config_recurrencia", "displayName": "config_recurrencia", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "ultima_disparada", "displayName": "ultima_disparada", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                    {"id": "categoria_exclusiva", "displayName": "categoria_exclusiva", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
                ],
                "attemptToConvertTypes": False,
                "convertFieldsToString": False,
            },
            "options": {},
        },
        "id": "f2-5-recurrentes-update-ultima-generada",
        "name": "Update Ultima Generada",
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        # Posición: a la izquierda y abajo de Crear Tareas1 (ramificación visual)
        "position": [existing_position[0], existing_position[1] + 220],
        "credentials": {
            "googleSheetsOAuth2Api": {"id": CREDENTIAL_ID, "name": "Google Sheets account"}
        },
    }


def http_get(url, key):
    req = urllib.request.Request(url, headers={"X-N8N-API-KEY": key})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def http_put(url, key, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={"X-N8N-API-KEY": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"HTTP {e.code} body:\n{err_body}\n")
        # Volcar el body que enviamos para inspección
        with open("/tmp/n8n_put_body.json", "w") as f:
            f.write(json.dumps(body, indent=2))
        sys.stderr.write("Body enviado guardado en /tmp/n8n_put_body.json\n")
        raise


def main():
    key_path = os.path.expanduser("~/.n8n_key")
    if not os.path.exists(key_path):
        sys.exit("Falta ~/.n8n_key")
    api_key = open(key_path).read().strip()

    print("→ GET workflow Control_IPM")
    wf = http_get(f"{N8N_URL}/{WORKFLOW_ID}", api_key)
    nodes = wf["nodes"]
    conns = wf.setdefault("connections", {})

    # 1. Patch del Code
    code_node = next((n for n in nodes if n["name"] == "Filtrar y Generar1"), None)
    if not code_node:
        sys.exit("ERROR: nodo 'Filtrar y Generar1' no encontrado")
    code_node["parameters"]["jsCode"] = NEW_JS_CODE
    print("✓ jsCode reemplazado en 'Filtrar y Generar1'")

    # 2. Añadir nodo Update Ultima Generada (idempotente)
    crear_tareas = next((n for n in nodes if n["name"] == "Crear Tareas1"), None)
    if not crear_tareas:
        sys.exit("ERROR: nodo 'Crear Tareas1' no encontrado")
    update_existing = next((n for n in nodes if n["name"] == "Update Ultima Generada"), None)
    if update_existing:
        # Re-actualiza parámetros por si cambió el diseño
        for k, v in build_update_node(crear_tareas["position"]).items():
            if k != "id":  # respetar id si ya existía
                update_existing[k] = v
        print("✓ 'Update Ultima Generada' ya existía → parámetros actualizados (idempotente)")
    else:
        nodes.append(build_update_node(crear_tareas["position"]))
        print("✓ 'Update Ultima Generada' añadido")

    # 3. Fork de la conexión IF → [Crear Tareas1, Update Ultima Generada]
    if_conn = conns.setdefault("If", {}).setdefault("main", [[]])
    branch = if_conn[0]
    target_names = {b["node"] for b in branch}
    if "Crear Tareas1" not in target_names:
        branch.append({"node": "Crear Tareas1", "type": "main", "index": 0})
        print("⚠  Inesperado: 'Crear Tareas1' no estaba conectado al IF — añadido")
    if "Update Ultima Generada" not in target_names:
        branch.append({"node": "Update Ultima Generada", "type": "main", "index": 0})
        print("✓ Conexión 'If → Update Ultima Generada' añadida")
    else:
        print("✓ Conexión 'If → Update Ultima Generada' ya existía (idempotente)")

    # 4. PUT — solo whitelist permitida (N8N-001).
    # `settings` debe limitarse a los campos aceptados por la API; los traídos
    # del GET (binaryMode, timeSavedMode, availableInMCP) provocan 400.
    live_settings = wf.get("settings", {}) or {}
    safe_settings = {
        "executionOrder": live_settings.get("executionOrder", "v1"),
        "callerPolicy": live_settings.get("callerPolicy", "workflowsFromSameOwner"),
    }
    if live_settings.get("timezone"):
        safe_settings["timezone"] = live_settings["timezone"]
    body = {
        "name": wf["name"],
        "nodes": wf["nodes"],
        "connections": wf["connections"],
        "settings": safe_settings,
        "staticData": wf.get("staticData"),
    }
    print(f"→ PUT workflow ({len(body['nodes'])} nodos)")
    resp = http_put(f"{N8N_URL}/{WORKFLOW_ID}", api_key, body)
    print(f"✓ PUT OK — versionId={resp.get('versionId')}, active={resp.get('active')}")


if __name__ == "__main__":
    main()
