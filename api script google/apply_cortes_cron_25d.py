"""
Regla 3 — auto-cierre programado a 25 días del corte.

Modifica el workflow Cortes añadiendo un Schedule Trigger diario que cierra
automáticamente lotes cuya `fecha_corte` cumple 25 días o más, siempre que
NO haya reservas pendientes (estado='reservada') asociadas.

Si un lote a 25d+ tiene reservas pendientes, NO se cierra (respeta la
trazabilidad). El badge "+25d" en la UI gestion.html ya avisa visualmente
de esos casos para que Eric decida manualmente.

Flujo:
  Schedule Trigger (06:30 diario)
    → Read eventos_corte (executeOnce)
    → Read reservas_pedidos (executeOnce)
    → Calcular Eventos Caducados 25d (Code → has + lista)
    → IF Hay Caducados?
        ├─ TRUE  → Marcar Caducados (Code N items)
        │           → Update eventos caducados
        │           → NoOp (terminar)
        └─ FALSE → NoOp (terminar)

Reglas de cierre automático:
  - estado actual = 'activo'
  - (hoy - fecha_corte) >= 25 días
  - ninguna reserva con estado='reservada' apuntando a ese evento

Idempotente: aborta si el cron ya está aplicado.

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
RESERVAS_GID = 793345778
SHEETS_CRED = {"id": "U9MmYhXUgVdOQej5", "name": "Google Sheets account"}

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")

existing = {n["name"] for n in wf["nodes"]}
if "Cron Auto-cierre 25d" in existing:
    print("ABORT: 'Cron Auto-cierre 25d' ya existe — el workflow ya tiene la regla 3 aplicada.")
    sys.exit(0)


# ─── Helpers ─────────────────────────────────────────────────
def schedule_trigger_node(name, hour, minute, pos):
    return {
        "parameters": {
            "rule": {
                "interval": [
                    {"field": "hours", "hoursInterval": 24, "triggerAtHour": hour, "triggerAtMinute": minute}
                ]
            }
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": pos,
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


def noop_node(name, pos):
    return {
        "parameters": {},
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.noOp",
        "typeVersion": 1,
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


def sheets_reservas():
    return {
        "__rl": True,
        "value": RESERVAS_GID,
        "mode": "list",
        "cachedResultName": "reservas_pedidos",
        "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={RESERVAS_GID}",
    }


def read_node(name, sheet_block, pos):
    return {
        "parameters": {"documentId": sheets_doc(), "sheetName": sheet_block, "options": {}},
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "position": pos,
        "credentials": {"googleSheetsOAuth2Api": SHEETS_CRED},
        "alwaysOutputData": True,
        "executeOnce": True,
    }


def update_eventos_caducados_node(name, pos):
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
CALCULAR_CADUCADOS_CODE = r"""const eventos = $('Read eventos_corte (cron)').all().map(i => i.json);
const reservas = $('Read reservas_pedidos (cron)').all().map(i => i.json);

const hoyStr = new Date().toISOString().slice(0, 10);
const hoyMs = new Date(hoyStr + 'T00:00:00Z').getTime();
const DIAS_LIMITE = 25;

// Eventos con reserva pendiente (estado='reservada')
const eventosConReservasPendientes = new Set();
for (const r of reservas) {
  const est = String(r.estado || '').trim().toLowerCase();
  if (est === 'reservada') {
    const id = String(r.id_evento || '').trim();
    if (id) eventosConReservasPendientes.add(id);
  }
}

const aCerrar = [];
for (const e of eventos) {
  const idEvento = String(e.id_evento || '').trim();
  if (!idEvento) continue;
  const estado = (String(e.estado || '').trim().toLowerCase()) || 'activo';
  if (estado !== 'activo') continue;

  const fecha_corte = String(e.fecha_corte || '').trim();
  if (!fecha_corte) continue;
  const corteMs = new Date(fecha_corte + 'T00:00:00Z').getTime();
  if (isNaN(corteMs)) continue;
  const dias = Math.floor((hoyMs - corteMs) / 86400000);
  if (dias < DIAS_LIMITE) continue;

  // Si hay reservas pendientes, NO cerrar (respeta trazabilidad)
  if (eventosConReservasPendientes.has(idEvento)) continue;

  aCerrar.push({
    id_evento: idEvento,
    estado: 'cerrado',
    fecha_cierre: hoyStr,
    motivo_cierre: 'caducado_25d',
  });
}

return [{ json: { has_caducados: aCerrar.length > 0, eventos: aCerrar } }];
"""

MARCAR_CADUCADOS_CODE = r"""const eventos = $('Calcular Eventos Caducados 25d').first().json.eventos || [];
return eventos.map(e => ({ json: e }));
"""

# ─── Crear nodos ─────────────────────────────────────────────
base_x, base_y = 200, 1880

n_cron = schedule_trigger_node("Cron Auto-cierre 25d", 6, 30, [base_x, base_y])
n_read_ev = read_node("Read eventos_corte (cron)", sheets_eventos(),
                      [base_x + 200, base_y])
n_read_res = read_node("Read reservas_pedidos (cron)", sheets_reservas(),
                       [base_x + 400, base_y])
n_calc = code_node("Calcular Eventos Caducados 25d", CALCULAR_CADUCADOS_CODE,
                   [base_x + 600, base_y])
n_if = if_node("Hay Caducados?", "={{ $json.has_caducados }}",
               [base_x + 800, base_y])
n_marcar = code_node("Marcar Caducados", MARCAR_CADUCADOS_CODE,
                     [base_x + 1000, base_y - 120])
n_update = update_eventos_caducados_node("Update eventos caducados",
                                         [base_x + 1200, base_y - 120])
n_noop_end = noop_node("Cron Fin", [base_x + 1400, base_y])

wf["nodes"].extend([n_cron, n_read_ev, n_read_res, n_calc, n_if, n_marcar, n_update, n_noop_end])

# ─── Conexiones ──────────────────────────────────────────────
wf["connections"]["Cron Auto-cierre 25d"] = {
    "main": [[{"node": "Read eventos_corte (cron)", "type": "main", "index": 0}]]
}
wf["connections"]["Read eventos_corte (cron)"] = {
    "main": [[{"node": "Read reservas_pedidos (cron)", "type": "main", "index": 0}]]
}
wf["connections"]["Read reservas_pedidos (cron)"] = {
    "main": [[{"node": "Calcular Eventos Caducados 25d", "type": "main", "index": 0}]]
}
wf["connections"]["Calcular Eventos Caducados 25d"] = {
    "main": [[{"node": "Hay Caducados?", "type": "main", "index": 0}]]
}
wf["connections"]["Hay Caducados?"] = {
    "main": [
        [{"node": "Marcar Caducados", "type": "main", "index": 0}],
        [{"node": "Cron Fin", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Marcar Caducados"] = {
    "main": [[{"node": "Update eventos caducados", "type": "main", "index": 0}]]
}
wf["connections"]["Update eventos caducados"] = {
    "main": [[{"node": "Cron Fin", "type": "main", "index": 0}]]
}

# ─── PUT ─────────────────────────────────────────────────────
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_cortes_post_cron_25d.json"
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
