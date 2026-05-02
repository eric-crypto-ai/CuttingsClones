"""
Paso 5: extiende /pedidos-entregar para marcar las reservas activas del pedido como `consumida`.

Inserta entre `Sheets update pedido entregado` y `Respond pedidos-entregar`:
  Update pedido entregado
    → Read reservas_pedidos (for entregar) [executeOnce]
    → Find Reservas Pedido (Code, devuelve { has_reservas, reservas: [...] })
    → IF Has Reservas Pedido?
        ├─ TRUE  → Marcar Filas Consumidas (Code, N items) → Update reservas consumidas → Respond
        └─ FALSE → Respond
"""
import json
import os
import sys
import uuid
import urllib.request

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "OGYN277IKvO9OVpH"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEETS_CRED = {"id": "U9MmYhXUgVdOQej5", "name": "Google Sheets account"}

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")

# Posición de referencia
update_pos = next(n["position"] for n in wf["nodes"] if n["name"] == "Sheets update pedido entregado")
respond_pos = next(n["position"] for n in wf["nodes"] if n["name"] == "Respond pedidos-entregar")
print(f"  Update pedido entregado: {update_pos}")
print(f"  Respond pedidos-entregar: {respond_pos}")

# Mover Respond más a la derecha para hacer hueco
shift = 1000
for n in wf["nodes"]:
    if n["name"] == "Respond pedidos-entregar":
        n["position"] = [respond_pos[0] + shift, respond_pos[1]]


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
                "conditions": [
                    {
                        "id": str(uuid.uuid4()),
                        "leftValue": expression,
                        "rightValue": "",
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                    }
                ],
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


def reservas_update_node(name, pos):
    cols = ["id_reserva", "estado", "fecha_consumida"]
    return {
        "parameters": {
            "operation": "update",
            "documentId": {"__rl": True, "mode": "id", "value": SPREADSHEET_ID},
            "sheetName": {"__rl": True, "mode": "name", "value": "reservas_pedidos"},
            "columns": {
                "mappingMode": "defineBelow",
                "value": {
                    "id_reserva": "={{ $json.id_reserva }}",
                    "estado": "={{ $json.estado }}",
                    "fecha_consumida": "={{ $json.fecha_consumida }}",
                },
                "matchingColumns": ["id_reserva"],
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


FIND_RESERVAS_CODE = r"""const idPedido = $('Prepare pedidos-entregar').first().json.id_pedido;
const filas = $input.all().map(i => i.json);

const reservas = filas
  .filter(r => String(r.id_pedido || '').trim() === idPedido)
  .filter(r => String(r.estado || '').trim().toLowerCase() === 'reservada')
  .map(r => ({
    id_reserva: String(r.id_reserva || '').trim(),
    id_evento: String(r.id_evento || '').trim(),
    cantidad: Number(r.cantidad) || 0,
  }));

return [{
  json: {
    id_pedido: idPedido,
    has_reservas: reservas.length > 0,
    reservas,
  }
}];
"""

MARCAR_FILAS_CODE = r"""const reservas = $('Find Reservas Pedido').first().json.reservas || [];
const hoy = new Date().toISOString().slice(0, 10);

return reservas.map(r => ({
  json: {
    id_reserva: r.id_reserva,
    estado: 'consumida',
    fecha_consumida: hoy,
  }
}));
"""

# Crear nuevos nodos
y = update_pos[1]
n_read = sheet_read_node("Read reservas_pedidos (for entregar)", "reservas_pedidos",
                          [update_pos[0] + 200, y], execute_once=True)
n_find = code_node("Find Reservas Pedido", FIND_RESERVAS_CODE, [update_pos[0] + 400, y])
n_if = if_node("Has Reservas Pedido?",
               "={{ $json.has_reservas }}",
               [update_pos[0] + 600, y])
n_marcar = code_node("Marcar Filas Consumidas", MARCAR_FILAS_CODE,
                      [update_pos[0] + 800, y - 120])
n_update_reservas = reservas_update_node("Update reservas consumidas",
                                          [update_pos[0] + 1000, y - 120])

wf["nodes"].extend([n_read, n_find, n_if, n_marcar, n_update_reservas])

# Reconectar:
# Update pedido entregado → Read reservas_pedidos (no longer to Respond)
wf["connections"]["Sheets update pedido entregado"] = {
    "main": [[{"node": "Read reservas_pedidos (for entregar)", "type": "main", "index": 0}]]
}
wf["connections"]["Read reservas_pedidos (for entregar)"] = {
    "main": [[{"node": "Find Reservas Pedido", "type": "main", "index": 0}]]
}
wf["connections"]["Find Reservas Pedido"] = {
    "main": [[{"node": "Has Reservas Pedido?", "type": "main", "index": 0}]]
}
wf["connections"]["Has Reservas Pedido?"] = {
    "main": [
        [{"node": "Marcar Filas Consumidas", "type": "main", "index": 0}],
        [{"node": "Respond pedidos-entregar", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Marcar Filas Consumidas"] = {
    "main": [[{"node": "Update reservas consumidas", "type": "main", "index": 0}]]
}
wf["connections"]["Update reservas consumidas"] = {
    "main": [[{"node": "Respond pedidos-entregar", "type": "main", "index": 0}]]
}

# PUT
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_gestion_economica_post_consumir.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"\nNodos finales: {len(body['nodes'])}")

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
