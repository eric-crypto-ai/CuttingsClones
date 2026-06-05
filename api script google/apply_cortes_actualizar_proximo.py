"""
Cortes — endpoint POST /cortes-actualizar-proximo

Añade al workflow Cortes (WF_ID=H3rtLs6wi4Yty91S) un endpoint que actualiza
ATÓMICAMENTE la fecha del próximo corte de un lote, manteniendo sincronizados:

  1. eventos_corte.fecha_proximo_corte_estimada (columna del lote)
  2. tareas.fecha de la tarea #4 asociada (zona=madres, tipo_origen=corte,
     id_evento_origen=X, estado=pendiente)

Si la tarea #4 está hecha o no existe, solo actualiza el evento (lo reporta
en la respuesta como tarea_actualizada=false).

Body request:
  { "id_evento": "AMN-2026-04-25-1",
    "nueva_fecha_proximo_corte_estimada": "2026-05-09" }

Validaciones:
  - id_evento existe en eventos_corte
  - estado del lote === 'activo' (no permite editar lotes cerrados)
  - fecha formato ISO YYYY-MM-DD válido

Respuesta OK:
  { "ok": true, "id_evento": "...", "nueva_fecha": "...",
    "tarea_actualizada": true|false, "id_tarea": "..." (si aplica) }

Respuesta Error:
  { "ok": false, "error": "..." }

Idempotencia: aborta si ya existe un nodo "Webhook Actualizar Proximo".

Requiere: N8N_KEY (env o ~/.n8n_key).
"""
import json
import os
import sys
import uuid
import urllib.request
import urllib.error

BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "H3rtLs6wi4Yty91S"

SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEETS_CRED_ID = "U9MmYhXUgVdOQej5"
SHEETS_CRED_NAME = "Google Sheets account"

EVENTOS_GID = 1143539242
TAREAS_GID = 1404161276


def _load_key():
    v = os.environ.get("N8N_KEY")
    if v:
        return v
    p = os.path.expanduser("~/.n8n_key")
    if os.path.isfile(p):
        with open(p) as f:
            return f.read().strip()
    raise SystemExit("N8N_KEY no encontrado")


API_KEY = _load_key()
HEADERS = {"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}


def n8n_request(method, path, payload=None):
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        return e.code, body


# ─── Snippets de código JS ────────────────────────────────────────

JSCODE_VALIDAR = r"""const body = $('Webhook Actualizar Proximo').first().json.body || $('Webhook Actualizar Proximo').first().json;
const id_evento = String(body.id_evento || '').trim();
const nueva_fecha = String(body.nueva_fecha_proximo_corte_estimada || '').trim();

if (!id_evento) {
  return [{ json: { ok: false, error: 'falta id_evento' } }];
}
if (!nueva_fecha || !/^\d{4}-\d{2}-\d{2}$/.test(nueva_fecha)) {
  return [{ json: { ok: false, error: 'formato fecha invalido (YYYY-MM-DD)' } }];
}
const fechaTest = new Date(nueva_fecha + 'T00:00:00Z');
if (isNaN(fechaTest.getTime())) {
  return [{ json: { ok: false, error: 'fecha invalida' } }];
}

const eventos = $('Read eventos_corte (actualizar)').all().map(i => i.json);
const evento = eventos.find(e => String(e.id_evento || '').trim() === id_evento);
if (!evento) {
  return [{ json: { ok: false, error: 'lote no encontrado: ' + id_evento } }];
}
const estado = (String(evento.estado || '').trim().toLowerCase()) || 'activo';
if (estado !== 'activo') {
  return [{ json: { ok: false, error: 'lote no activo (estado=' + estado + '). No se permite editar fechas de lotes cerrados.' } }];
}

// Tarea #4 asociada (zona=madres, tipo_origen=corte, id_evento_origen=X, estado=pendiente)
const tareas = $('Read tareas (actualizar)').all().map(i => i.json);
const tarea = tareas.find(t =>
  String(t.id_evento_origen || '').trim() === id_evento &&
  String(t.tipo_origen || '').trim().toLowerCase() === 'corte' &&
  String(t.zona || '').trim().toLowerCase() === 'madres' &&
  String(t.estado || '').trim().toLowerCase() === 'pendiente'
);

return [{ json: {
  ok: true,
  id_evento: id_evento,
  fecha_proximo_corte_estimada: nueva_fecha,
  tarea_existe: !!tarea,
  id_tarea: tarea ? String(tarea.id || '').trim() : ''
} }];
"""

JSCODE_FORMAT_OK_CON_TAREA = r"""const v = $('Validar Actualizar Proximo').first().json;
return [{ json: {
  ok: true,
  id_evento: v.id_evento,
  nueva_fecha: v.fecha_proximo_corte_estimada,
  tarea_actualizada: true,
  id_tarea: v.id_tarea
} }];
"""

JSCODE_FORMAT_OK_SIN_TAREA = r"""const v = $('Validar Actualizar Proximo').first().json;
return [{ json: {
  ok: true,
  id_evento: v.id_evento,
  nueva_fecha: v.fecha_proximo_corte_estimada,
  tarea_actualizada: false,
  motivo_sin_tarea: 'tarea #4 no existe o no esta pendiente'
} }];
"""


# ─── Helpers de nodos ─────────────────────────────────────────────

def _id():
    return str(uuid.uuid4())


def webhook_node(name, path, pos):
    return {
        "parameters": {
            "httpMethod": "POST",
            "path": path,
            "responseMode": "responseNode",
            "options": {"allowedOrigins": "*"},
        },
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2.1,
        "position": pos,
        "webhookId": _id(),
    }


def sheets_read_node(name, gid, sheet_label, pos):
    return {
        "parameters": {
            "documentId": {
                "__rl": True, "value": SPREADSHEET_ID, "mode": "list",
                "cachedResultName": "Control_IPM",
            },
            "sheetName": {
                "__rl": True, "value": gid, "mode": "list",
                "cachedResultName": sheet_label,
            },
            "options": {},
        },
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.5,
        "position": pos,
        "executeOnce": True,
        "credentials": {"googleSheetsOAuth2Api": {"id": SHEETS_CRED_ID, "name": SHEETS_CRED_NAME}},
    }


def sheets_update_node(name, gid, sheet_label, value_map, matching_columns, pos):
    return {
        "parameters": {
            "operation": "update",
            "documentId": {
                "__rl": True, "value": SPREADSHEET_ID, "mode": "list",
                "cachedResultName": "Control_IPM",
            },
            "sheetName": {
                "__rl": True, "value": gid, "mode": "list",
                "cachedResultName": sheet_label,
            },
            "columns": {
                "mappingMode": "defineBelow",
                "value": value_map,
                "matchingColumns": matching_columns,
                "schema": [],
                "attemptToConvertTypes": False,
                "convertFieldsToString": True,
            },
            "options": {},
        },
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.5,
        "position": pos,
        "credentials": {"googleSheetsOAuth2Api": {"id": SHEETS_CRED_ID, "name": SHEETS_CRED_NAME}},
    }


def code_node(name, jscode, pos):
    return {
        "parameters": {"jsCode": jscode},
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": pos,
    }


def if_node(name, expr, pos):
    return {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                "conditions": [{
                    "id": _id(),
                    "leftValue": expr,
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }],
                "combinator": "and",
            },
            "options": {},
        },
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": pos,
    }


def respond_node(name, pos):
    """Respond to Webhook devolviendo $json directo."""
    return {
        "parameters": {
            "respondWith": "json",
            "responseBody": "={{ $json }}",
            "options": {},
        },
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": pos,
    }


# ─── 1. Leer workflow vivo ────────────────────────────────────────
status, wf = n8n_request("GET", f"/workflows/{WF_ID}")
if status != 200:
    raise SystemExit(f"GET workflow falló: HTTP {status} — {wf}")

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos, active={wf.get('active')}")

# Idempotencia
existing_names = {n["name"] for n in wf["nodes"]}
if "Webhook Actualizar Proximo" in existing_names:
    print("ABORT: 'Webhook Actualizar Proximo' ya existe — el endpoint ya está aplicado.")
    sys.exit(0)


# ─── 2. Crear los 12 nodos nuevos ─────────────────────────────────
# Posicion: a la derecha del workflow existente, columna nueva
BASE_X = 240
BASE_Y = 4200  # bajo de todo

# Calcular max y de existentes para posicionar debajo
max_y = max((n.get("position", [0, 0])[1] for n in wf["nodes"]), default=0)
BASE_Y = max_y + 320

COL_W = 240

new_nodes = [
    webhook_node("Webhook Actualizar Proximo", "cortes-actualizar-proximo",
                 [BASE_X, BASE_Y]),
    sheets_read_node("Read eventos_corte (actualizar)", EVENTOS_GID, "eventos_corte",
                     [BASE_X + COL_W, BASE_Y]),
    sheets_read_node("Read tareas (actualizar)", TAREAS_GID, "tareas",
                     [BASE_X + COL_W*2, BASE_Y]),
    code_node("Validar Actualizar Proximo", JSCODE_VALIDAR,
              [BASE_X + COL_W*3, BASE_Y]),
    if_node("¿Validar OK?", "={{ $json.ok }}",
            [BASE_X + COL_W*4, BASE_Y]),
    # TRUE branch del IF Validar
    sheets_update_node(
        "Update Evento Proximo", EVENTOS_GID, "eventos_corte",
        value_map={
            "id_evento": "={{ $json.id_evento }}",
            "fecha_proximo_corte_estimada": "={{ $json.fecha_proximo_corte_estimada }}",
        },
        matching_columns=["id_evento"],
        pos=[BASE_X + COL_W*5, BASE_Y - 80],
    ),
    # IF y Update Tarea referencian Validar directamente porque Update Evento
    # sobrescribe el item con la fila actualizada de eventos_corte (perdiendo
    # tarea_existe e id_tarea). Sin esto, el IF siempre evalúa false y la
    # tarea #4 nunca se sincroniza. Bug detectado y corregido 2026-05-03.
    if_node("¿Hay Tarea Pendiente?",
            "={{ $('Validar Actualizar Proximo').first().json.tarea_existe }}",
            [BASE_X + COL_W*6, BASE_Y - 80]),
    sheets_update_node(
        "Update Tarea Fecha", TAREAS_GID, "tareas",
        value_map={
            "id": "={{ $('Validar Actualizar Proximo').first().json.id_tarea }}",
            "fecha": "={{ $('Validar Actualizar Proximo').first().json.fecha_proximo_corte_estimada }}",
        },
        matching_columns=["id"],
        pos=[BASE_X + COL_W*7, BASE_Y - 160],
    ),
    code_node("Format Respuesta OK Con Tarea", JSCODE_FORMAT_OK_CON_TAREA,
              [BASE_X + COL_W*8, BASE_Y - 160]),
    # FALSE branch del Hay Tarea: format sin tarea
    code_node("Format Respuesta OK Sin Tarea", JSCODE_FORMAT_OK_SIN_TAREA,
              [BASE_X + COL_W*7, BASE_Y]),
    respond_node("Respond Actualizar OK", [BASE_X + COL_W*9, BASE_Y - 80]),
    # FALSE branch del Validar OK
    respond_node("Respond Actualizar Error", [BASE_X + COL_W*5, BASE_Y + 80]),
]

wf["nodes"].extend(new_nodes)


# ─── 3. Conexiones ────────────────────────────────────────────────
new_conns = {
    "Webhook Actualizar Proximo": {"main": [[
        {"node": "Read eventos_corte (actualizar)", "type": "main", "index": 0}
    ]]},
    "Read eventos_corte (actualizar)": {"main": [[
        {"node": "Read tareas (actualizar)", "type": "main", "index": 0}
    ]]},
    "Read tareas (actualizar)": {"main": [[
        {"node": "Validar Actualizar Proximo", "type": "main", "index": 0}
    ]]},
    "Validar Actualizar Proximo": {"main": [[
        {"node": "¿Validar OK?", "type": "main", "index": 0}
    ]]},
    "¿Validar OK?": {"main": [
        # TRUE
        [{"node": "Update Evento Proximo", "type": "main", "index": 0}],
        # FALSE
        [{"node": "Respond Actualizar Error", "type": "main", "index": 0}],
    ]},
    "Update Evento Proximo": {"main": [[
        {"node": "¿Hay Tarea Pendiente?", "type": "main", "index": 0}
    ]]},
    "¿Hay Tarea Pendiente?": {"main": [
        # TRUE
        [{"node": "Update Tarea Fecha", "type": "main", "index": 0}],
        # FALSE
        [{"node": "Format Respuesta OK Sin Tarea", "type": "main", "index": 0}],
    ]},
    "Update Tarea Fecha": {"main": [[
        {"node": "Format Respuesta OK Con Tarea", "type": "main", "index": 0}
    ]]},
    "Format Respuesta OK Con Tarea": {"main": [[
        {"node": "Respond Actualizar OK", "type": "main", "index": 0}
    ]]},
    "Format Respuesta OK Sin Tarea": {"main": [[
        {"node": "Respond Actualizar OK", "type": "main", "index": 0}
    ]]},
}

for name, conn in new_conns.items():
    wf["connections"][name] = conn


# ─── 4. PUT ───────────────────────────────────────────────────────
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

print(f"\nAplicando PUT con {len(wf['nodes'])} nodos totales (12 nuevos)...")
status, result = n8n_request("PUT", f"/workflows/{WF_ID}", body)
if status == 200:
    print(f"✓ PUT OK: HTTP {status}, active={result.get('active')}, nodes={len(result.get('nodes', []))}")
else:
    print(f"✗ PUT FALLÓ: HTTP {status} — {result}")
    sys.exit(1)

# Verificación post-PUT
status, wf2 = n8n_request("GET", f"/workflows/{WF_ID}")
if status == 200:
    after_names = {n["name"] for n in wf2["nodes"]}
    if "Webhook Actualizar Proximo" in after_names:
        print("✓ Verificación post-PUT: 'Webhook Actualizar Proximo' presente en live.")
    else:
        print("⚠ Verificación post-PUT: webhook NO presente. Revisa manualmente.")
        sys.exit(1)

# Snapshot local
NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_cortes_post_actualizar_proximo.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"✓ Snapshot escrito: {NEW_FILE}")
