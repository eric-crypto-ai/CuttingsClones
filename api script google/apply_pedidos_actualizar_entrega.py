"""
Nuevo webhook POST /pedidos-actualizar-entrega en workflow Gestion_Economica.

Body: { id_pedido, fecha_entrega_prometida }
- Valida que el pedido existe y está en estado=pendiente.
- Valida que la fecha tiene formato YYYY-MM-DD.
- Update pedido: set fecha_entrega_prometida.

Flujo:
  Webhook pedidos-actualizar-entrega
    → Prepare pedidos-actualizar-entrega (Code: extrae body, valida fecha)
    → Read pedidos (for actualizar-entrega) [executeOnce]
    → Check pedido editable (Code: existe + estado=pendiente)
    → IF Pedido editable?
        ├─ TRUE  → Update pedido fecha entrega → Respond OK
        └─ FALSE → Respond Error
"""
import json
import os
import sys
import uuid
import urllib.request
import urllib.error

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "OGYN277IKvO9OVpH"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEETS_CRED = {"id": "U9MmYhXUgVdOQej5", "name": "Google Sheets account"}

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))
print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")


def webhook_node(name, path, pos, http_method="POST"):
    return {
        "parameters": {
            "httpMethod": http_method,
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

def pedido_update_fecha_node(name, pos):
    """Update pedido: matchingColumns=id_pedido, set fecha_entrega_prometida."""
    cols = ["id_pedido", "fecha_entrega_prometida"]
    return {
        "parameters": {
            "operation": "update",
            "documentId": {"__rl": True, "mode": "id", "value": SPREADSHEET_ID},
            "sheetName": {"__rl": True, "mode": "name", "value": "pedidos"},
            "columns": {
                "mappingMode": "defineBelow",
                "value": {
                    "id_pedido": "={{ $('Prepare pedidos-actualizar-entrega').first().json.id_pedido }}",
                    "fecha_entrega_prometida": "={{ $('Prepare pedidos-actualizar-entrega').first().json.fecha_entrega_prometida }}",
                },
                "matchingColumns": ["id_pedido"],
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


PREPARE_CODE = r"""const body = $input.first().json.body || $input.first().json;
const id_pedido = String(body.id_pedido || '').trim();
const fecha = String(body.fecha_entrega_prometida || '').trim();

if (!id_pedido) {
  return [{ json: { id_pedido: '', fecha_entrega_prometida: '', error_msg: 'id_pedido requerido', editable: false } }];
}
if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha)) {
  return [{ json: { id_pedido, fecha_entrega_prometida: fecha, error_msg: 'fecha_entrega_prometida inválida (formato YYYY-MM-DD requerido)', editable: false } }];
}
const d = new Date(fecha + 'T00:00:00');
if (isNaN(d.getTime())) {
  return [{ json: { id_pedido, fecha_entrega_prometida: fecha, error_msg: 'fecha_entrega_prometida inválida', editable: false } }];
}
return [{ json: { id_pedido, fecha_entrega_prometida: fecha, error_msg: '', editable: null } }];
"""

CHECK_CODE = r"""const prep = $('Prepare pedidos-actualizar-entrega').first().json;
if (prep.error_msg) return [{ json: prep }];

const idPedido = prep.id_pedido;
const filas = $input.all().map(i => i.json).filter(p => p.id_pedido);
const pedido = filas.find(p => String(p.id_pedido).trim() === idPedido);

if (!pedido) {
  return [{ json: { id_pedido: idPedido, fecha_entrega_prometida: prep.fecha_entrega_prometida, error_msg: 'pedido no encontrado: ' + idPedido, editable: false } }];
}
const estado = String(pedido.estado || '').trim().toLowerCase();
if (estado !== 'pendiente') {
  return [{ json: { id_pedido: idPedido, fecha_entrega_prometida: prep.fecha_entrega_prometida, error_msg: 'pedido no editable (estado actual: ' + estado + ')', editable: false } }];
}
return [{ json: { id_pedido: idPedido, fecha_entrega_prometida: prep.fecha_entrega_prometida, error_msg: '', editable: true } }];
"""

# Posición base — zona vacía bajo pedidos-cancelar
base_x, base_y = 200, 7200

n_webhook = webhook_node("Webhook pedidos-actualizar-entrega", "pedidos-actualizar-entrega", [base_x, base_y])
n_prepare = code_node("Prepare pedidos-actualizar-entrega", PREPARE_CODE, [base_x + 200, base_y])
n_read_pedidos = sheet_read_node("Read pedidos (for actualizar-entrega)", "pedidos",
                                  [base_x + 400, base_y], execute_once=True)
n_check = code_node("Check pedido editable", CHECK_CODE, [base_x + 600, base_y])
n_if_editable = if_node("Pedido editable?", "={{ $json.editable }}", [base_x + 800, base_y])
n_update_pedido = pedido_update_fecha_node("Update pedido fecha entrega", [base_x + 1000, base_y - 100])
n_respond_ok = respond_node(
    "Respond pedidos-actualizar-entrega OK",
    "={{ { \"success\": true, \"data\": { \"id_pedido\": $('Prepare pedidos-actualizar-entrega').first().json.id_pedido, \"fecha_entrega_prometida\": $('Prepare pedidos-actualizar-entrega').first().json.fecha_entrega_prometida } } }}",
    [base_x + 1200, base_y - 100],
)
n_respond_err = respond_node(
    "Respond pedidos-actualizar-entrega Error",
    "={{ { \"success\": false, \"error\": $('Check pedido editable').first().json.error_msg || $('Prepare pedidos-actualizar-entrega').first().json.error_msg } }}",
    [base_x + 1000, base_y + 200],
)

wf["nodes"].extend([
    n_webhook, n_prepare, n_read_pedidos, n_check, n_if_editable,
    n_update_pedido, n_respond_ok, n_respond_err,
])

# Conexiones
wf["connections"]["Webhook pedidos-actualizar-entrega"] = {
    "main": [[{"node": "Prepare pedidos-actualizar-entrega", "type": "main", "index": 0}]]
}
wf["connections"]["Prepare pedidos-actualizar-entrega"] = {
    "main": [[{"node": "Read pedidos (for actualizar-entrega)", "type": "main", "index": 0}]]
}
wf["connections"]["Read pedidos (for actualizar-entrega)"] = {
    "main": [[{"node": "Check pedido editable", "type": "main", "index": 0}]]
}
wf["connections"]["Check pedido editable"] = {
    "main": [[{"node": "Pedido editable?", "type": "main", "index": 0}]]
}
wf["connections"]["Pedido editable?"] = {
    "main": [
        [{"node": "Update pedido fecha entrega", "type": "main", "index": 0}],
        [{"node": "Respond pedidos-actualizar-entrega Error", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Update pedido fecha entrega"] = {
    "main": [[{"node": "Respond pedidos-actualizar-entrega OK", "type": "main", "index": 0}]]
}

# PUT
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_gestion_economica_post_actualizar_entrega.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
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
