"""
v2: cambia el manejo de errores de validación de `throw` a IF + Respond error,
así el cliente recibe { success: false, error: <msg> } con HTTP 200 en lugar
de un 500 genérico que pierde el mensaje.

Inserta entre `Validar Reservas` y `Prepare pedidos row`:
  Validar Reservas (devuelve { ok, error_msg, body, _has_reservas, _reservas_to_insert })
    → IF Validacion OK?
        ├─ TRUE → Prepare pedidos row (flujo normal)
        └─ FALSE → Respond Error pedidos-crear (devuelve { success:false, error })
"""
import json
import os
import sys
import uuid
import urllib.request

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "OGYN277IKvO9OVpH"

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")

# 1. Reescribir Validar Reservas para no usar throw
NEW_VALIDAR_CODE = r"""const body = $('Webhook pedidos-crear').first().json.body || $('Webhook pedidos-crear').first().json;
const eventos = $('Read eventos_corte (for crear)').all().map(i => i.json);
const reservas = $('Read reservas_pedidos (for crear)').all().map(i => i.json);

function fail(msg) {
  return [{ json: { ok: false, error_msg: msg, body, _has_reservas: false, _reservas_to_insert: [] } }];
}

const cantidad = Number(body.cantidad || 0);
if (!body.id_cliente) return fail("id_cliente requerido");
if (!body.genetica) return fail("genetica requerida");
if (!cantidad || cantidad <= 0) return fail("cantidad invalida");
if (!body.precio_unitario || Number(body.precio_unitario) <= 0) return fail("precio invalido");

const reservasInput = Array.isArray(body.reservas) ? body.reservas : [];
const has_reservas = reservasInput.length > 0;

if (has_reservas) {
  const suma = reservasInput.reduce((a, r) => a + Number(r.cantidad || 0), 0);
  if (suma !== cantidad) return fail("suma de reservas (" + suma + ") no coincide con cantidad pedida (" + cantidad + ")");

  const reservasPorEvento = {};
  for (const r of reservas) {
    const e = String(r.id_evento || '').trim();
    if (!e) continue;
    const est = String(r.estado || '').trim().toLowerCase();
    if (est === 'reservada' || est === 'consumida') {
      reservasPorEvento[e] = (reservasPorEvento[e] || 0) + (Number(r.cantidad) || 0);
    }
  }

  const eventoPorId = {};
  for (const e of eventos) {
    const id = String(e.id_evento || '').trim();
    if (id) eventoPorId[id] = e;
  }

  for (const r of reservasInput) {
    const idEvento = String(r.id_evento || '').trim();
    const cant = Number(r.cantidad || 0);
    if (!idEvento) return fail("id_evento vacio en una reserva");
    if (cant <= 0) return fail("cantidad invalida en reserva de " + idEvento);
    const e = eventoPorId[idEvento];
    if (!e) return fail("lote no existe: " + idEvento);
    if ((String(e.estado || '').trim().toLowerCase() || 'activo') !== 'activo') {
      return fail("lote no activo: " + idEvento);
    }
    const total_neto = (Number(e.num_esquejes) || 0) - (Number(e.n_descartados) || 0);
    const reservado = reservasPorEvento[idEvento] || 0;
    const disponible = total_neto - reservado;
    if (cant > disponible) return fail("stock insuficiente en " + idEvento + ": pides " + cant + ", disponible " + disponible);
  }
}

const baseTs = Date.now();
const reservas_to_insert = reservasInput.map((r, i) => ({
  id_reserva: "RP" + baseTs + (i > 0 ? "-" + i : ""),
  id_evento: String(r.id_evento).trim(),
  cantidad: Number(r.cantidad),
}));

return [{
  json: {
    ok: true,
    error_msg: "",
    body,
    _has_reservas: has_reservas,
    _reservas_to_insert: reservas_to_insert,
  }
}];
"""

for n in wf["nodes"]:
    if n["name"] == "Validar Reservas":
        n["parameters"]["jsCode"] = NEW_VALIDAR_CODE
        validar_pos = n["position"]
        break

# 2. Crear nodo IF "Validacion OK?" y "Respond Error pedidos-crear"
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

def respond_error_node(name, pos):
    return {
        "parameters": {
            "respondWith": "json",
            "responseBody": "={{ { \"success\": false, \"error\": $json.error_msg } }}",
            "options": {},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.5,
        "position": pos,
    }

# Insertar IF justo después de Validar Reservas
n_if_validacion = if_node(
    "Validacion OK?",
    "={{ $json.ok }}",
    [validar_pos[0] + 200, validar_pos[1]],
)
n_respond_error = respond_error_node(
    "Respond Error pedidos-crear",
    [validar_pos[0] + 400, validar_pos[1] + 200],
)

# Mover Prepare pedidos row y todo lo siguiente 200 más a la derecha
shift = 200
shift_targets = ["Prepare pedidos row", "Sheets append pedidos", "Has Reservas?",
                 "Preparar Filas Reservas", "Sheets append reservas_pedidos",
                 "Respond pedidos-crear"]
for n in wf["nodes"]:
    if n["name"] in shift_targets:
        n["position"] = [n["position"][0] + shift, n["position"][1]]

wf["nodes"].extend([n_if_validacion, n_respond_error])

# 3. Reconectar:
# Validar Reservas → Validacion OK?
wf["connections"]["Validar Reservas"] = {
    "main": [[{"node": "Validacion OK?", "type": "main", "index": 0}]]
}
# Validacion OK? TRUE → Prepare pedidos row, FALSE → Respond Error
wf["connections"]["Validacion OK?"] = {
    "main": [
        [{"node": "Prepare pedidos row", "type": "main", "index": 0}],
        [{"node": "Respond Error pedidos-crear", "type": "main", "index": 0}],
    ]
}

# Body PUT
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_gestion_economica_post_reservas_v2.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"Nodos finales: {len(body['nodes'])} (antes: 66)")

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
