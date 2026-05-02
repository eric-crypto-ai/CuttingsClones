"""
Paso 6: nuevo webhook POST /pedidos-cancelar en workflow Gestion_Economica.

Body: { id_pedido }
- Valida que el pedido existe y está en estado=pendiente (no permite cancelar
  entregado o ya cancelado → devuelve { success:false, error }).
- Update pedido a estado=cancelado.
- Update reservas activas del pedido (estado=reservada) a estado=liberada con
  fecha_consumida=hoy y notas=cancelado.

Flujo:
  Webhook pedidos-cancelar
    → Prepare pedidos-cancelar (Code: extrae id_pedido del body)
    → Read pedidos (for cancelar) [executeOnce]
    → Check pedido cancelable (Code: valida; si no → fail flag)
    → IF Pedido cancelable?
        ├─ TRUE  → Update pedido cancelado
        │           → Read reservas_pedidos (for cancelar) [executeOnce]
        │           → Find Reservas Cancelar (Code → has_reservas + lista)
        │           → IF Has Reservas Cancelar?
        │               ├─ TRUE  → Marcar Filas Liberadas (Code) → Update reservas liberadas → Respond OK
        │               └─ FALSE → Respond OK
        └─ FALSE → Respond Error pedidos-cancelar
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

def pedido_update_node(name, pos):
    """Update pedido: matchingColumns=id_pedido, set estado=cancelado."""
    cols = ["id_pedido", "estado"]
    return {
        "parameters": {
            "operation": "update",
            "documentId": {"__rl": True, "mode": "id", "value": SPREADSHEET_ID},
            "sheetName": {"__rl": True, "mode": "name", "value": "pedidos"},
            "columns": {
                "mappingMode": "defineBelow",
                "value": {
                    "id_pedido": "={{ $('Prepare pedidos-cancelar').first().json.id_pedido }}",
                    "estado": "cancelado",
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

def reservas_update_liberadas_node(name, pos):
    cols = ["id_reserva", "estado", "fecha_consumida", "notas"]
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
                    "notas": "={{ $json.notas }}",
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


PREPARE_CODE = r"""const body = $input.first().json.body || $input.first().json;
const id_pedido = String(body.id_pedido || '').trim();
if (!id_pedido) {
  return [{ json: { id_pedido: '', error_msg: 'id_pedido requerido', cancelable: false } }];
}
return [{ json: { id_pedido, error_msg: '', cancelable: null } }];
"""

CHECK_CODE = r"""const prep = $('Prepare pedidos-cancelar').first().json;
if (prep.error_msg) return [{ json: prep }];

const idPedido = prep.id_pedido;
const filas = $input.all().map(i => i.json).filter(p => p.id_pedido);
const pedido = filas.find(p => String(p.id_pedido).trim() === idPedido);

if (!pedido) {
  return [{ json: { id_pedido: idPedido, error_msg: 'pedido no encontrado: ' + idPedido, cancelable: false } }];
}
const estado = String(pedido.estado || '').trim().toLowerCase();
if (estado !== 'pendiente') {
  return [{ json: { id_pedido: idPedido, error_msg: 'pedido no cancelable (estado actual: ' + estado + ')', cancelable: false } }];
}
return [{ json: { id_pedido: idPedido, error_msg: '', cancelable: true } }];
"""

FIND_RESERVAS_CODE = r"""const idPedido = $('Prepare pedidos-cancelar').first().json.id_pedido;
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

MARCAR_LIBERADAS_CODE = r"""const reservas = $('Find Reservas Cancelar').first().json.reservas || [];
const hoy = new Date().toISOString().slice(0, 10);

return reservas.map(r => ({
  json: {
    id_reserva: r.id_reserva,
    estado: 'liberada',
    fecha_consumida: hoy,
    notas: 'pedido cancelado',
  }
}));
"""

# Posición base — usar zona vacía bajo bote-repartir (~y=6500)
base_x, base_y = 200, 6500

n_webhook = webhook_node("Webhook pedidos-cancelar", "pedidos-cancelar", [base_x, base_y])
n_prepare = code_node("Prepare pedidos-cancelar", PREPARE_CODE, [base_x + 200, base_y])
n_read_pedidos = sheet_read_node("Sheets read pedidos (for cancelar)", "pedidos",
                                  [base_x + 400, base_y], execute_once=True)
n_check = code_node("Check pedido cancelable", CHECK_CODE, [base_x + 600, base_y])
n_if_cancel = if_node("Pedido cancelable?", "={{ $json.cancelable }}", [base_x + 800, base_y])
n_update_pedido = pedido_update_node("Update pedido cancelado", [base_x + 1000, base_y - 100])
n_read_reservas = sheet_read_node("Read reservas_pedidos (for cancelar)", "reservas_pedidos",
                                   [base_x + 1200, base_y - 100], execute_once=True)
n_find_reservas = code_node("Find Reservas Cancelar", FIND_RESERVAS_CODE,
                              [base_x + 1400, base_y - 100])
n_if_reservas = if_node("Has Reservas Cancelar?", "={{ $json.has_reservas }}",
                         [base_x + 1600, base_y - 100])
n_marcar = code_node("Marcar Filas Liberadas", MARCAR_LIBERADAS_CODE,
                      [base_x + 1800, base_y - 200])
n_update_reservas = reservas_update_liberadas_node("Update reservas liberadas",
                                                     [base_x + 2000, base_y - 200])
n_respond_ok = respond_node(
    "Respond pedidos-cancelar OK",
    "={{ { \"success\": true, \"data\": { \"id_pedido\": $('Prepare pedidos-cancelar').first().json.id_pedido } } }}",
    [base_x + 2200, base_y - 100],
)
n_respond_err = respond_node(
    "Respond pedidos-cancelar Error",
    "={{ { \"success\": false, \"error\": $('Check pedido cancelable').first().json.error_msg || $('Prepare pedidos-cancelar').first().json.error_msg } }}",
    [base_x + 1000, base_y + 200],
)

wf["nodes"].extend([
    n_webhook, n_prepare, n_read_pedidos, n_check, n_if_cancel,
    n_update_pedido, n_read_reservas, n_find_reservas, n_if_reservas,
    n_marcar, n_update_reservas, n_respond_ok, n_respond_err,
])

# Conexiones
wf["connections"]["Webhook pedidos-cancelar"] = {
    "main": [[{"node": "Prepare pedidos-cancelar", "type": "main", "index": 0}]]
}
wf["connections"]["Prepare pedidos-cancelar"] = {
    "main": [[{"node": "Sheets read pedidos (for cancelar)", "type": "main", "index": 0}]]
}
wf["connections"]["Sheets read pedidos (for cancelar)"] = {
    "main": [[{"node": "Check pedido cancelable", "type": "main", "index": 0}]]
}
wf["connections"]["Check pedido cancelable"] = {
    "main": [[{"node": "Pedido cancelable?", "type": "main", "index": 0}]]
}
wf["connections"]["Pedido cancelable?"] = {
    "main": [
        [{"node": "Update pedido cancelado", "type": "main", "index": 0}],
        [{"node": "Respond pedidos-cancelar Error", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Update pedido cancelado"] = {
    "main": [[{"node": "Read reservas_pedidos (for cancelar)", "type": "main", "index": 0}]]
}
wf["connections"]["Read reservas_pedidos (for cancelar)"] = {
    "main": [[{"node": "Find Reservas Cancelar", "type": "main", "index": 0}]]
}
wf["connections"]["Find Reservas Cancelar"] = {
    "main": [[{"node": "Has Reservas Cancelar?", "type": "main", "index": 0}]]
}
wf["connections"]["Has Reservas Cancelar?"] = {
    "main": [
        [{"node": "Marcar Filas Liberadas", "type": "main", "index": 0}],
        [{"node": "Respond pedidos-cancelar OK", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Marcar Filas Liberadas"] = {
    "main": [[{"node": "Update reservas liberadas", "type": "main", "index": 0}]]
}
wf["connections"]["Update reservas liberadas"] = {
    "main": [[{"node": "Respond pedidos-cancelar OK", "type": "main", "index": 0}]]
}

# PUT
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_gestion_economica_post_cancelar.json"
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
