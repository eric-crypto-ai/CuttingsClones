"""
Regla 2 — cierre y reactivación manual de lotes.

Modifica el workflow Cortes añadiendo:
  - POST /cortes-cerrar      { id_evento, motivo? }   → estado='cerrado'
  - POST /cortes-reactivar   { id_evento }            → estado='activo' (limpia fecha/motivo)

Además extiende `Formatear Lista` (/cortes-lista) para devolver
`fecha_cierre` y `motivo_cierre` para que la UI los muestre.

Validaciones:
  /cortes-cerrar    → id_evento existe; debe estar activo (rechaza si ya cerrado)
  /cortes-reactivar → id_evento existe; debe estar inactivo (rechaza si ya activo)

Idempotente: revisa nombres de nodos y aborta si la regla ya está aplicada.

Requisitos:
  - Variable de entorno N8N_KEY
"""
import json
import os
import sys
import uuid
import urllib.request
import urllib.error

def _load_n8n_key():
    key = os.environ.get("N8N_KEY")
    if key:
        return key
    path = os.path.expanduser("~/.n8n_key")
    if os.path.isfile(path):
        with open(path) as f:
            return f.read().strip()
    raise SystemExit("N8N_KEY no está en env ni en ~/.n8n_key")

API_KEY = _load_n8n_key()
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "H3rtLs6wi4Yty91S"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
EVENTOS_GID = 1143539242
SHEETS_CRED = {"id": "U9MmYhXUgVdOQej5", "name": "Google Sheets account"}

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")

existing = {n["name"] for n in wf["nodes"]}
if "Webhook Cerrar Lote" in existing:
    print("ABORT: 'Webhook Cerrar Lote' ya existe — el workflow ya tiene la regla 2 aplicada.")
    sys.exit(0)


# ─── Helpers ─────────────────────────────────────────────────
def webhook_node(name, path, pos):
    return {
        "parameters": {
            "httpMethod": "POST",
            "path": path,
            "responseMode": "responseNode",
            "options": {"allowedOrigins": "*"},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2.1,
        "position": pos,
        "webhookId": path,
    }


def code_node(name, code, pos):
    return {
        "parameters": {"jsCode": code},
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": pos,
    }


def if_node(name, expression, pos):
    return {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                "conditions": [{
                    "id": str(uuid.uuid4()),
                    "leftValue": expression,
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }],
                "combinator": "and",
            },
            "options": {},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": pos,
    }


def respond_node(name, body, pos):
    return {
        "parameters": {"respondWith": "json", "responseBody": body, "options": {}},
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.5,
        "position": pos,
    }


def sheets_doc():
    return {
        "__rl": True,
        "value": SPREADSHEET_ID,
        "mode": "list",
        "cachedResultName": "Control_IPM",
        "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=drivesdk",
    }


def sheets_eventos():
    return {
        "__rl": True,
        "value": EVENTOS_GID,
        "mode": "list",
        "cachedResultName": "eventos_corte",
        "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={EVENTOS_GID}",
    }


def read_eventos(name, pos):
    return {
        "parameters": {"documentId": sheets_doc(), "sheetName": sheets_eventos(), "options": {}},
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "position": pos,
        "credentials": {"googleSheetsOAuth2Api": SHEETS_CRED},
        "alwaysOutputData": True,
        "executeOnce": True,
    }


def update_eventos(name, pos):
    cols = ["id_evento", "estado", "fecha_cierre", "motivo_cierre"]
    return {
        "parameters": {
            "operation": "update",
            "documentId": sheets_doc(),
            "sheetName": sheets_eventos(),
            "columns": {
                "mappingMode": "defineBelow",
                "value": {
                    "id_evento": "={{ $json.id_evento }}",
                    "estado": "={{ $json.estado }}",
                    "fecha_cierre": "={{ $json.fecha_cierre }}",
                    "motivo_cierre": "={{ $json.motivo_cierre }}",
                },
                "matchingColumns": ["id_evento"],
                "schema": [
                    {"id": c, "displayName": c, "required": False, "defaultMatch": False,
                     "display": True, "type": "string"} for c in cols
                ],
                "attemptToConvertTypes": False,
                "convertFieldsToString": False,
            },
            "options": {},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "position": pos,
        "credentials": {"googleSheetsOAuth2Api": SHEETS_CRED},
    }


# ─── Código JS ───────────────────────────────────────────────
PREPARE_CERRAR_CODE = r"""const body = $input.first().json.body || $input.first().json;
const id_evento = String(body.id_evento || '').trim();
const motivo = String(body.motivo || 'manual').trim().toLowerCase() || 'manual';
if (!id_evento) {
  return [{ json: { ok: false, error: 'id_evento requerido', _stop: true } }];
}
return [{ json: { id_evento, motivo, ok: true } }];
"""

VALIDAR_CERRAR_CODE = r"""const prep = $('Prepare Cerrar Lote').first().json;
if (prep._stop) return [{ json: prep }];

const eventos = $input.all().map(i => i.json);
const evento = eventos.find(e => String(e.id_evento || '').trim() === prep.id_evento);
if (!evento) {
  return [{ json: { ok: false, error: 'lote no encontrado: ' + prep.id_evento, _stop: true } }];
}
const estado = (String(evento.estado || '').trim().toLowerCase()) || 'activo';
if (estado !== 'activo') {
  return [{ json: { ok: false, error: 'lote ya cerrado: ' + prep.id_evento, _stop: true } }];
}

const hoy = new Date().toISOString().slice(0, 10);
return [{
  json: {
    id_evento: prep.id_evento,
    estado: 'cerrado',
    fecha_cierre: hoy,
    motivo_cierre: prep.motivo,
    ok: true,
  }
}];
"""

PREPARE_REACTIVAR_CODE = r"""const body = $input.first().json.body || $input.first().json;
const id_evento = String(body.id_evento || '').trim();
if (!id_evento) {
  return [{ json: { ok: false, error: 'id_evento requerido', _stop: true } }];
}
return [{ json: { id_evento, ok: true } }];
"""

VALIDAR_REACTIVAR_CODE = r"""const prep = $('Prepare Reactivar Lote').first().json;
if (prep._stop) return [{ json: prep }];

const eventos = $input.all().map(i => i.json);
const evento = eventos.find(e => String(e.id_evento || '').trim() === prep.id_evento);
if (!evento) {
  return [{ json: { ok: false, error: 'lote no encontrado: ' + prep.id_evento, _stop: true } }];
}
const estado = (String(evento.estado || '').trim().toLowerCase()) || 'activo';
if (estado === 'activo') {
  return [{ json: { ok: false, error: 'lote ya activo: ' + prep.id_evento, _stop: true } }];
}

return [{
  json: {
    id_evento: prep.id_evento,
    estado: 'activo',
    fecha_cierre: '',
    motivo_cierre: '',
    ok: true,
  }
}];
"""

# ─── Crear nodos /cortes-cerrar ──────────────────────────────
base_x_cerrar, base_y_cerrar = 200, 1240

n_wh_cerrar = webhook_node("Webhook Cerrar Lote", "cortes-cerrar", [base_x_cerrar, base_y_cerrar])
n_prep_cerrar = code_node("Prepare Cerrar Lote", PREPARE_CERRAR_CODE,
                          [base_x_cerrar + 200, base_y_cerrar])
n_read_cerrar = read_eventos("Read eventos_corte (cerrar)", [base_x_cerrar + 400, base_y_cerrar])
n_val_cerrar = code_node("Validar Cerrar Lote", VALIDAR_CERRAR_CODE,
                         [base_x_cerrar + 600, base_y_cerrar])
n_if_cerrar = if_node("Cierre OK?", "={{ $json.ok && !$json._stop }}",
                      [base_x_cerrar + 800, base_y_cerrar])
n_upd_cerrar = update_eventos("Update lote cerrado", [base_x_cerrar + 1000, base_y_cerrar - 120])
n_resp_cerrar_ok = respond_node(
    "Respond Cerrar OK",
    "={{ { \"ok\": true, \"id_evento\": $('Validar Cerrar Lote').first().json.id_evento, \"motivo_cierre\": $('Validar Cerrar Lote').first().json.motivo_cierre } }}",
    [base_x_cerrar + 1200, base_y_cerrar - 120],
)
n_resp_cerrar_err = respond_node(
    "Respond Cerrar Error",
    "={{ { \"ok\": false, \"error\": ($('Validar Cerrar Lote').first().json.error || $('Prepare Cerrar Lote').first().json.error || 'error desconocido') } }}",
    [base_x_cerrar + 1000, base_y_cerrar + 120],
)

# ─── Crear nodos /cortes-reactivar ───────────────────────────
base_x_reac, base_y_reac = 200, 1560

n_wh_reac = webhook_node("Webhook Reactivar Lote", "cortes-reactivar", [base_x_reac, base_y_reac])
n_prep_reac = code_node("Prepare Reactivar Lote", PREPARE_REACTIVAR_CODE,
                        [base_x_reac + 200, base_y_reac])
n_read_reac = read_eventos("Read eventos_corte (reactivar)", [base_x_reac + 400, base_y_reac])
n_val_reac = code_node("Validar Reactivar Lote", VALIDAR_REACTIVAR_CODE,
                       [base_x_reac + 600, base_y_reac])
n_if_reac = if_node("Reactivar OK?", "={{ $json.ok && !$json._stop }}",
                    [base_x_reac + 800, base_y_reac])
n_upd_reac = update_eventos("Update lote reactivado", [base_x_reac + 1000, base_y_reac - 120])
n_resp_reac_ok = respond_node(
    "Respond Reactivar OK",
    "={{ { \"ok\": true, \"id_evento\": $('Validar Reactivar Lote').first().json.id_evento } }}",
    [base_x_reac + 1200, base_y_reac - 120],
)
n_resp_reac_err = respond_node(
    "Respond Reactivar Error",
    "={{ { \"ok\": false, \"error\": ($('Validar Reactivar Lote').first().json.error || $('Prepare Reactivar Lote').first().json.error || 'error desconocido') } }}",
    [base_x_reac + 1000, base_y_reac + 120],
)

new_nodes = [
    n_wh_cerrar, n_prep_cerrar, n_read_cerrar, n_val_cerrar, n_if_cerrar,
    n_upd_cerrar, n_resp_cerrar_ok, n_resp_cerrar_err,
    n_wh_reac, n_prep_reac, n_read_reac, n_val_reac, n_if_reac,
    n_upd_reac, n_resp_reac_ok, n_resp_reac_err,
]
wf["nodes"].extend(new_nodes)

# ─── Conexiones ──────────────────────────────────────────────
wf["connections"]["Webhook Cerrar Lote"] = {
    "main": [[{"node": "Prepare Cerrar Lote", "type": "main", "index": 0}]]
}
wf["connections"]["Prepare Cerrar Lote"] = {
    "main": [[{"node": "Read eventos_corte (cerrar)", "type": "main", "index": 0}]]
}
wf["connections"]["Read eventos_corte (cerrar)"] = {
    "main": [[{"node": "Validar Cerrar Lote", "type": "main", "index": 0}]]
}
wf["connections"]["Validar Cerrar Lote"] = {
    "main": [[{"node": "Cierre OK?", "type": "main", "index": 0}]]
}
wf["connections"]["Cierre OK?"] = {
    "main": [
        [{"node": "Update lote cerrado", "type": "main", "index": 0}],
        [{"node": "Respond Cerrar Error", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Update lote cerrado"] = {
    "main": [[{"node": "Respond Cerrar OK", "type": "main", "index": 0}]]
}

wf["connections"]["Webhook Reactivar Lote"] = {
    "main": [[{"node": "Prepare Reactivar Lote", "type": "main", "index": 0}]]
}
wf["connections"]["Prepare Reactivar Lote"] = {
    "main": [[{"node": "Read eventos_corte (reactivar)", "type": "main", "index": 0}]]
}
wf["connections"]["Read eventos_corte (reactivar)"] = {
    "main": [[{"node": "Validar Reactivar Lote", "type": "main", "index": 0}]]
}
wf["connections"]["Validar Reactivar Lote"] = {
    "main": [[{"node": "Reactivar OK?", "type": "main", "index": 0}]]
}
wf["connections"]["Reactivar OK?"] = {
    "main": [
        [{"node": "Update lote reactivado", "type": "main", "index": 0}],
        [{"node": "Respond Reactivar Error", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Update lote reactivado"] = {
    "main": [[{"node": "Respond Reactivar OK", "type": "main", "index": 0}]]
}

# ─── Extender Formatear Lista para incluir fecha_cierre y motivo_cierre ─
NEW_FORMATEAR_CODE = r"""const eventos = $('Leer Eventos para Lista').all().map(i => i.json);
const reservas = $('Leer Reservas para Lista').all().map(i => i.json);

const reservasPorEvento = {};
for (const r of reservas) {
  const idEvento = String(r.id_evento || '').trim();
  if (!idEvento) continue;
  const estado = String(r.estado || '').trim().toLowerCase();
  if (estado === 'reservada' || estado === 'consumida') {
    if (!reservasPorEvento[idEvento]) reservasPorEvento[idEvento] = [];
    reservasPorEvento[idEvento].push(r);
  }
}

const items = eventos
  .map(f => {
    const id_evento = String(f.id_evento || '').trim();
    const num_esquejes = Number(f.num_esquejes) || 0;
    const n_descartados = Number(f.n_descartados) || 0;
    const total_neto = num_esquejes - n_descartados;
    const resList = reservasPorEvento[id_evento] || [];
    const reservado = resList.reduce((acc, r) => acc + (Number(r.cantidad) || 0), 0);
    const disponible = total_neto - reservado;
    return {
      id_evento,
      fecha_corte: String(f.fecha_corte || '').trim(),
      genetica: String(f.genetica || '').trim(),
      num_esquejes,
      intervalo_dias: Number(f.intervalo_dias) || 14,
      fecha_proximo_corte_estimada: String(f.fecha_proximo_corte_estimada || '').trim(),
      operario: String(f.operario || '').trim(),
      observaciones: String(f.observaciones || '').trim(),
      estado: String(f.estado || '').trim() || 'activo',
      fecha_cierre: String(f.fecha_cierre || '').trim(),
      motivo_cierre: String(f.motivo_cierre || '').trim(),
      total_neto,
      reservado,
      disponible,
      reservas_activas: resList.map(r => ({
        id_reserva: String(r.id_reserva || '').trim(),
        id_pedido: String(r.id_pedido || '').trim(),
        cantidad: Number(r.cantidad) || 0,
        estado: String(r.estado || '').trim(),
        fecha_reserva: String(r.fecha_reserva || '').trim(),
      })),
    };
  })
  .filter(f => f.id_evento)
  .sort((a, b) => {
    if (b.fecha_corte !== a.fecha_corte) return b.fecha_corte.localeCompare(a.fecha_corte);
    return b.id_evento.localeCompare(a.id_evento);
  });

return [{ json: { items } }];
"""

for n in wf["nodes"]:
    if n["name"] == "Formatear Lista":
        n["parameters"]["jsCode"] = NEW_FORMATEAR_CODE
        print("  Actualizado: Formatear Lista (incluye fecha_cierre/motivo_cierre)")
        break
else:
    print("  WARN: nodo 'Formatear Lista' no encontrado — /cortes-lista no se actualizó")

# ─── PUT ─────────────────────────────────────────────────────
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_cortes_post_cerrar_manual.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"Snapshot escrito: {NEW_FILE}")
print(f"Nodos finales: {len(body['nodes'])}")

req = urllib.request.Request(
    f"{BASE}/workflows/{WF_ID}",
    data=json.dumps(body).encode("utf-8"),
    method="PUT",
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        print(f"PUT status: {resp.status}, active: {result.get('active')}, nodes: {len(result.get('nodes', []))}")
except urllib.error.HTTPError as e:
    print(f"PUT FAILED: {e.code} {e.reason}")
    print(e.read().decode("utf-8"))
    sys.exit(1)
