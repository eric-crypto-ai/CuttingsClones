"""
Regla 1 — auto-cierre de lote por consumo total.

Modifica el workflow Gestion_Economica añadiendo, después de
`Update reservas consumidas` (rama TRUE de `Has Reservas Pedido?` en
/pedidos-entregar), la lógica que detecta lotes totalmente consumidos
y los marca como inactivos en eventos_corte.

Flujo nuevo (sustituye la conexión directa Update reservas consumidas → Respond):

  Update reservas consumidas
    → Read eventos_corte (for autocierre)        [executeOnce]
    → Read reservas_pedidos (for autocierre)     [executeOnce, post-update]
    → Calcular Eventos a Cerrar                  (Code, devuelve { has, eventos })
    → IF Hay Eventos a Cerrar?
        ├─ TRUE  → Marcar Eventos Cerrados (Code N items)
        │           → Update eventos cerrados
        │           → Respond pedidos-entregar
        └─ FALSE → Respond pedidos-entregar

Reglas de cierre (todas deben cumplirse):
  - estado actual del evento = 'activo'
  - num_esquejes - n_descartados (= total_neto) === suma reservas con estado='consumida'
  - no quedan reservas con estado='reservada' para ese evento

Idempotente: si ningún lote queda totalmente consumido, no escribe nada.

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
WF_ID = "OGYN277IKvO9OVpH"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEETS_CRED = {"id": "U9MmYhXUgVdOQej5", "name": "Google Sheets account"}

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")

# Sanity: no aplicar dos veces
existing = {n["name"] for n in wf["nodes"]}
if "Calcular Eventos a Cerrar" in existing:
    print("ABORT: 'Calcular Eventos a Cerrar' ya existe — el workflow ya tiene la regla 1 aplicada.")
    sys.exit(0)

# Posición de referencia
update_reservas_pos = next(n["position"] for n in wf["nodes"]
                           if n["name"] == "Update reservas consumidas")
respond_pos = next(n["position"] for n in wf["nodes"]
                   if n["name"] == "Respond pedidos-entregar")

# Mover Respond pedidos-entregar más a la derecha para hacer hueco
shift = 1400
for n in wf["nodes"]:
    if n["name"] == "Respond pedidos-entregar":
        n["position"] = [respond_pos[0] + shift, respond_pos[1]]


# ─── Helpers ──────────────────────────────────────────────────
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


def sheet_read_node(name, sheet_label, pos, execute_once=False):
    node = {
        "parameters": {
            "operation": "read",
            "documentId": {"__rl": True, "mode": "id", "value": SPREADSHEET_ID},
            "sheetName": {"__rl": True, "mode": "name", "value": sheet_label},
            "options": {},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.5,
        "position": pos,
        "credentials": {"googleSheetsOAuth2Api": SHEETS_CRED},
        "alwaysOutputData": True,
    }
    if execute_once:
        node["executeOnce"] = True
    return node


def eventos_update_node(name, pos):
    """Update eventos_corte: matchingColumns=id_evento, set estado/fecha_cierre/motivo_cierre."""
    cols = ["id_evento", "estado", "fecha_cierre", "motivo_cierre"]
    return {
        "parameters": {
            "operation": "update",
            "documentId": {"__rl": True, "mode": "id", "value": SPREADSHEET_ID},
            "sheetName": {"__rl": True, "mode": "name", "value": "eventos_corte"},
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
        "typeVersion": 4.5,
        "position": pos,
        "credentials": {"googleSheetsOAuth2Api": SHEETS_CRED},
    }


# ─── Código JS ────────────────────────────────────────────────
CALCULAR_CODE = r"""const reservasConsumidas = ($('Find Reservas Pedido').first().json.reservas) || [];
const eventos = $('Read eventos_corte (for autocierre)').all().map(i => i.json);
const reservasTodas = $('Read reservas_pedidos (for autocierre)').all().map(i => i.json);

// IDs únicos de eventos afectados por este consumo
const idsAfectados = [...new Set(reservasConsumidas.map(r => String(r.id_evento || '').trim()).filter(Boolean))];

const hoy = new Date().toISOString().slice(0, 10);
const aCerrar = [];

for (const idEvento of idsAfectados) {
  const evento = eventos.find(e => String(e.id_evento || '').trim() === idEvento);
  if (!evento) continue;
  const estadoActual = (String(evento.estado || '').trim().toLowerCase()) || 'activo';
  if (estadoActual !== 'activo') continue;

  const total_neto = (Number(evento.num_esquejes) || 0) - (Number(evento.n_descartados) || 0);

  let consumidas = 0;
  let reservadas = 0;
  for (const r of reservasTodas) {
    if (String(r.id_evento || '').trim() !== idEvento) continue;
    const est = String(r.estado || '').trim().toLowerCase();
    const cant = Number(r.cantidad) || 0;
    if (est === 'consumida') consumidas += cant;
    else if (est === 'reservada') reservadas += cant;
  }

  // Cerrar solo si todo el lote se consumió y no quedan reservas pendientes
  if (consumidas >= total_neto && reservadas === 0 && total_neto > 0) {
    aCerrar.push({
      id_evento: idEvento,
      estado: 'cerrado',
      fecha_cierre: hoy,
      motivo_cierre: 'consumido',
    });
  }
}

return [{ json: { has_eventos_cerrar: aCerrar.length > 0, eventos: aCerrar } }];
"""

MARCAR_CODE = r"""const eventos = $('Calcular Eventos a Cerrar').first().json.eventos || [];
return eventos.map(e => ({ json: e }));
"""

# ─── Crear nodos ──────────────────────────────────────────────
ux, uy = update_reservas_pos[0], update_reservas_pos[1]

n_read_eventos = sheet_read_node("Read eventos_corte (for autocierre)", "eventos_corte",
                                 [ux + 200, uy], execute_once=True)
n_read_reservas = sheet_read_node("Read reservas_pedidos (for autocierre)", "reservas_pedidos",
                                  [ux + 400, uy], execute_once=True)
n_calcular = code_node("Calcular Eventos a Cerrar", CALCULAR_CODE, [ux + 600, uy])
n_if = if_node("Hay Eventos a Cerrar?", "={{ $json.has_eventos_cerrar }}", [ux + 800, uy])
n_marcar = code_node("Marcar Eventos Cerrados", MARCAR_CODE, [ux + 1000, uy - 120])
n_update = eventos_update_node("Update eventos cerrados", [ux + 1200, uy - 120])

wf["nodes"].extend([n_read_eventos, n_read_reservas, n_calcular, n_if, n_marcar, n_update])

# ─── Reconectar ───────────────────────────────────────────────
# Antes: Update reservas consumidas → Respond pedidos-entregar
# Después: Update reservas consumidas → Read eventos_corte (for autocierre) → ...
wf["connections"]["Update reservas consumidas"] = {
    "main": [[{"node": "Read eventos_corte (for autocierre)", "type": "main", "index": 0}]]
}
wf["connections"]["Read eventos_corte (for autocierre)"] = {
    "main": [[{"node": "Read reservas_pedidos (for autocierre)", "type": "main", "index": 0}]]
}
wf["connections"]["Read reservas_pedidos (for autocierre)"] = {
    "main": [[{"node": "Calcular Eventos a Cerrar", "type": "main", "index": 0}]]
}
wf["connections"]["Calcular Eventos a Cerrar"] = {
    "main": [[{"node": "Hay Eventos a Cerrar?", "type": "main", "index": 0}]]
}
wf["connections"]["Hay Eventos a Cerrar?"] = {
    "main": [
        [{"node": "Marcar Eventos Cerrados", "type": "main", "index": 0}],
        [{"node": "Respond pedidos-entregar", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Marcar Eventos Cerrados"] = {
    "main": [[{"node": "Update eventos cerrados", "type": "main", "index": 0}]]
}
wf["connections"]["Update eventos cerrados"] = {
    "main": [[{"node": "Respond pedidos-entregar", "type": "main", "index": 0}]]
}

# ─── PUT ──────────────────────────────────────────────────────
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_gestion_economica_post_autocierre_consumo.json"
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
