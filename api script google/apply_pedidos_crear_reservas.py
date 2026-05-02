"""
Extiende la rama `pedidos-crear` del workflow Gestion_Economica para soportar
reservas opcionales sobre eventos_corte.

Nuevo flujo:
  Webhook pedidos-crear
    → Read reservas_pedidos (executeOnce)
    → Read eventos_corte (executeOnce)
    → Validar Reservas (Code, throw si stock insuficiente o suma no cuadra)
    → Prepare pedidos row (existente, recibe { body, _has_reservas, _reservas_to_insert })
    → Sheets append pedidos (existente)
    → IF Has Reservas?
        ├─ TRUE → Preparar Filas Reservas (Code) → Sheets append reservas_pedidos → Respond
        └─ FALSE → Respond pedidos-crear
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

# Re-leer workflow vivo
req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos, active={wf['active']}")

# Posiciones de referencia (rama pedidos-crear actual)
node_pos = {n["name"]: n["position"] for n in wf["nodes"]}
print(f"  Webhook pedidos-crear: {node_pos.get('Webhook pedidos-crear')}")
print(f"  Prepare pedidos row:   {node_pos.get('Prepare pedidos row')}")
print(f"  Sheets append pedidos: {node_pos.get('Sheets append pedidos')}")
print(f"  Respond pedidos-crear: {node_pos.get('Respond pedidos-crear')}")


def sheet_read_node(name, sheet_label, pos, execute_once=False):
    return {
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
        **({"executeOnce": True} if execute_once else {}),
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


def reservas_append_node(name, pos):
    cols = ["id_reserva", "id_pedido", "id_evento", "cantidad", "estado",
            "fecha_reserva", "fecha_consumida", "notas"]
    return {
        "parameters": {
            "operation": "append",
            "documentId": {"__rl": True, "mode": "id", "value": SPREADSHEET_ID},
            "sheetName": {"__rl": True, "mode": "name", "value": "reservas_pedidos"},
            "columns": {
                "mappingMode": "defineBelow",
                "value": {c: f"={{{{ $json.{c} }}}}" for c in cols},
                "matchingColumns": [],
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


VALIDAR_CODE = r"""const body = $('Webhook pedidos-crear').first().json.body || $('Webhook pedidos-crear').first().json;
const eventos = $('Read eventos_corte (for crear)').all().map(i => i.json);
const reservas = $('Read reservas_pedidos (for crear)').all().map(i => i.json);

const cantidad = Number(body.cantidad || 0);
if (!body.id_cliente) throw new Error("id_cliente requerido");
if (!body.genetica) throw new Error("genetica requerida");
if (!cantidad || cantidad <= 0) throw new Error("cantidad invalida");
if (!body.precio_unitario || Number(body.precio_unitario) <= 0) throw new Error("precio invalido");

const reservasInput = Array.isArray(body.reservas) ? body.reservas : [];
const has_reservas = reservasInput.length > 0;

if (has_reservas) {
  const suma = reservasInput.reduce((a, r) => a + Number(r.cantidad || 0), 0);
  if (suma !== cantidad) throw new Error("suma de reservas (" + suma + ") no coincide con cantidad pedida (" + cantidad + ")");

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
    if (!idEvento) throw new Error("id_evento vacio en una reserva");
    if (cant <= 0) throw new Error("cantidad invalida en reserva de " + idEvento);
    const e = eventoPorId[idEvento];
    if (!e) throw new Error("lote no existe: " + idEvento);
    if ((String(e.estado || '').trim().toLowerCase() || 'activo') !== 'activo') {
      throw new Error("lote no activo: " + idEvento);
    }
    const total_neto = (Number(e.num_esquejes) || 0) - (Number(e.n_descartados) || 0);
    const reservado = reservasPorEvento[idEvento] || 0;
    const disponible = total_neto - reservado;
    if (cant > disponible) throw new Error("stock insuficiente en " + idEvento + ": pides " + cant + ", disponible " + disponible);
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
    body,
    _has_reservas: has_reservas,
    _reservas_to_insert: reservas_to_insert,
  }
}];
"""

PREPARAR_FILAS_CODE = r"""const idPedido = $('Prepare pedidos row').first().json.id_pedido;
const reservasToInsert = $('Validar Reservas').first().json._reservas_to_insert || [];
const hoy = new Date().toISOString().slice(0, 10);

return reservasToInsert.map(r => ({
  json: {
    id_reserva: r.id_reserva,
    id_pedido: idPedido,
    id_evento: r.id_evento,
    cantidad: r.cantidad,
    estado: 'reservada',
    fecha_reserva: hoy,
    fecha_consumida: '',
    notas: '',
  }
}));
"""

# Posiciones - rama existente: Webhook [_,1500] → Prepare [_,1500] → Append [_,1500] → Respond [_,1500]
# Insertaremos los nuevos nodos manteniendo y=1500 y desplazando los existentes a la derecha
wp_x, wp_y = node_pos["Webhook pedidos-crear"]

# Nuevos nodos pre-Prepare
n_read_reservas = sheet_read_node("Read reservas_pedidos (for crear)", "reservas_pedidos",
                                   [wp_x + 200, wp_y], execute_once=True)
n_read_eventos = sheet_read_node("Read eventos_corte (for crear)", "eventos_corte",
                                  [wp_x + 400, wp_y], execute_once=True)
n_validar = code_node("Validar Reservas", VALIDAR_CODE, [wp_x + 600, wp_y])

# Mover nodos existentes a la derecha para hacer hueco
shift = 600
existing_to_shift = ["Prepare pedidos row", "Sheets append pedidos", "Respond pedidos-crear"]
for n in wf["nodes"]:
    if n["name"] in existing_to_shift:
        n["position"] = [n["position"][0] + shift, n["position"][1]]

# Nuevos nodos post-Append
ap_x, ap_y = node_pos["Sheets append pedidos"]
ap_x_new = ap_x + shift  # nueva posición tras el shift

n_if = if_node(
    "Has Reservas?",
    "={{ $('Validar Reservas').first().json._has_reservas }}",
    [ap_x_new + 200, ap_y],
)
n_prep_filas = code_node("Preparar Filas Reservas", PREPARAR_FILAS_CODE,
                          [ap_x_new + 400, ap_y - 150])
n_append_reservas = reservas_append_node("Sheets append reservas_pedidos",
                                          [ap_x_new + 600, ap_y - 150])

# Mover Respond más a la derecha aún para dejar espacio al IF + ramas
for n in wf["nodes"]:
    if n["name"] == "Respond pedidos-crear":
        n["position"] = [ap_x_new + 800, ap_y]

wf["nodes"].extend([
    n_read_reservas, n_read_eventos, n_validar, n_if, n_prep_filas, n_append_reservas
])

# ---- Reescribir conexiones de la rama pedidos-crear ----
wf["connections"]["Webhook pedidos-crear"] = {
    "main": [[{"node": "Read reservas_pedidos (for crear)", "type": "main", "index": 0}]]
}
wf["connections"]["Read reservas_pedidos (for crear)"] = {
    "main": [[{"node": "Read eventos_corte (for crear)", "type": "main", "index": 0}]]
}
wf["connections"]["Read eventos_corte (for crear)"] = {
    "main": [[{"node": "Validar Reservas", "type": "main", "index": 0}]]
}
wf["connections"]["Validar Reservas"] = {
    "main": [[{"node": "Prepare pedidos row", "type": "main", "index": 0}]]
}
# Prepare pedidos row → Sheets append pedidos (sin cambios)
# Sheets append pedidos → Has Reservas? (cambia)
wf["connections"]["Sheets append pedidos"] = {
    "main": [[{"node": "Has Reservas?", "type": "main", "index": 0}]]
}
# IF tiene 2 outputs: index 0 = TRUE, index 1 = FALSE
wf["connections"]["Has Reservas?"] = {
    "main": [
        [{"node": "Preparar Filas Reservas", "type": "main", "index": 0}],
        [{"node": "Respond pedidos-crear", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Preparar Filas Reservas"] = {
    "main": [[{"node": "Sheets append reservas_pedidos", "type": "main", "index": 0}]]
}
wf["connections"]["Sheets append reservas_pedidos"] = {
    "main": [[{"node": "Respond pedidos-crear", "type": "main", "index": 0}]]
}

# PUT
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_gestion_economica_post_reservas.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"\nNodos finales: {len(body['nodes'])} (antes: 60)")

req = urllib.request.Request(
    f"{BASE}/workflows/{WF_ID}",
    data=json.dumps(body).encode("utf-8"),
    method="PUT",
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        print(f"PUT status: {resp.status}")
        print(f"  active: {result.get('active')}, nodes: {len(result.get('nodes', []))}")
except urllib.error.HTTPError as e:
    print(f"PUT FAILED: {e.code} {e.reason}")
    print(e.read().decode("utf-8"))
    sys.exit(1)
