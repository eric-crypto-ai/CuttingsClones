"""
Endpoint POST /pedidos-reservar — añade reservas a un pedido existente sin reservas.

Caso de uso (F2.6 §"Pedidos sin reserva permitidos"):
  Un pedido se creó antes de existir stock; ahora hay lote(s) y queremos
  vincular reservas a ese pedido sin tener que cancelar y recrearlo.

Body: { id_pedido: string, reservas: [{ id_evento, cantidad }, ...] }

Validaciones (Code "Validar Reserva Pedido"):
  - id_pedido existe
  - pedido.estado === 'pendiente' (no entregado/cancelado)
  - El pedido NO tiene reservas previas activas (estado in ['reservada','consumida'])
  - reservas no vacío
  - suma(reservas.cantidad) === pedido.cantidad (consistente con /pedidos-crear)
  - cada id_evento existe, estado='activo', genetica == pedido.genetica
  - cada id_evento tiene disponible suficiente (considera reservas existentes de OTROS pedidos)

Flujo:
  Webhook pedidos-reservar (POST)
    → Prepare pedidos-reservar (Code: extrae body)
    → Read pedidos (for reservar) [executeOnce]
    → Read eventos_corte (for reservar) [executeOnce]
    → Read reservas_pedidos (for reservar) [executeOnce]
    → Validar Reserva Pedido (Code: { ok, error_msg, _reservas_to_insert })
    → IF Reserva Pedido OK?
        ├─ TRUE  → Preparar Filas Reservas (reservar) → Sheets append reservas_pedidos (reservar) → Respond OK
        └─ FALSE → Respond Error pedidos-reservar

Idempotente: aborta si "Webhook pedidos-reservar" ya existe.

Requisitos: N8N_KEY (env o ~/.n8n_key)
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

existing = {n["name"] for n in wf["nodes"]}
if "Webhook pedidos-reservar" in existing:
    print("ABORT: 'Webhook pedidos-reservar' ya existe — endpoint ya aplicado.")
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


def sheet_read_node(name, sheet_label, pos, execute_once=True):
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


def reservas_append_node(name, pos):
    cols = ["id_reserva", "id_pedido", "id_evento", "cantidad",
            "estado", "fecha_reserva", "fecha_consumida", "notas"]
    return {
        "parameters": {
            "operation": "append",
            "documentId": {"__rl": True, "mode": "id", "value": SPREADSHEET_ID},
            "sheetName": {"__rl": True, "mode": "name", "value": "reservas_pedidos"},
            "columns": {
                "mappingMode": "defineBelow",
                "value": {
                    "id_reserva": "={{ $json.id_reserva }}",
                    "id_pedido": "={{ $json.id_pedido }}",
                    "id_evento": "={{ $json.id_evento }}",
                    "cantidad": "={{ $json.cantidad }}",
                    "estado": "={{ $json.estado }}",
                    "fecha_reserva": "={{ $json.fecha_reserva }}",
                    "fecha_consumida": "={{ $json.fecha_consumida }}",
                    "notas": "={{ $json.notas }}",
                },
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


# ─── Código JS ───────────────────────────────────────────────
PREPARE_CODE = r"""const body = $input.first().json.body || $input.first().json;
const id_pedido = String(body.id_pedido || '').trim();
const reservas = Array.isArray(body.reservas) ? body.reservas : [];
return [{ json: { id_pedido, reservas, body } }];
"""

VALIDAR_CODE = r"""const prep = $('Prepare pedidos-reservar').first().json;
const idPedido = prep.id_pedido;
const reservasInput = prep.reservas || [];

const pedidos = $('Read pedidos (for reservar)').all().map(i => i.json);
const eventos = $('Read eventos_corte (for reservar)').all().map(i => i.json);
const reservasExistentes = $('Read reservas_pedidos (for reservar)').all().map(i => i.json);

function fail(msg) {
  return [{ json: { ok: false, error_msg: msg, _reservas_to_insert: [] } }];
}

if (!idPedido) return fail("id_pedido requerido");
if (!Array.isArray(reservasInput) || reservasInput.length === 0) return fail("reservas vacío");

const pedido = pedidos.find(p => String(p.id_pedido || '').trim() === idPedido);
if (!pedido) return fail("pedido no encontrado: " + idPedido);

const estadoPedido = String(pedido.estado || '').trim().toLowerCase();
if (estadoPedido !== 'pendiente') return fail("pedido no es pendiente (estado: " + estadoPedido + ")");

// Bloquear si ya tiene reservas activas (reservada o consumida)
const tieneReservasActivas = reservasExistentes.some(r => {
  if (String(r.id_pedido || '').trim() !== idPedido) return false;
  const est = String(r.estado || '').trim().toLowerCase();
  return est === 'reservada' || est === 'consumida';
});
if (tieneReservasActivas) return fail("el pedido ya tiene reservas activas — usa /pedidos-cancelar y vuelve a crear si quieres reasignar");

const cantidadPedido = Number(pedido.cantidad) || 0;
const sumaReservas = reservasInput.reduce((a, r) => a + (Number(r.cantidad) || 0), 0);
if (sumaReservas !== cantidadPedido) {
  return fail("suma de reservas (" + sumaReservas + ") no coincide con cantidad pedida (" + cantidadPedido + ")");
}

const geneticaPedido = String(pedido.genetica || '').trim().toLowerCase();

// Mapa de reservado actual por evento (otras reservas activas)
const reservadoPorEvento = {};
for (const r of reservasExistentes) {
  const idEv = String(r.id_evento || '').trim();
  if (!idEv) continue;
  const est = String(r.estado || '').trim().toLowerCase();
  if (est === 'reservada' || est === 'consumida') {
    reservadoPorEvento[idEv] = (reservadoPorEvento[idEv] || 0) + (Number(r.cantidad) || 0);
  }
}

const eventoPorId = {};
for (const e of eventos) {
  const id = String(e.id_evento || '').trim();
  if (id) eventoPorId[id] = e;
}

// Sumar cantidades del propio body por evento (para validar contra disponible
// si el cliente reparte el mismo lote en varias entradas)
const pedidoPorEvento = {};
for (const r of reservasInput) {
  const idEv = String(r.id_evento || '').trim();
  pedidoPorEvento[idEv] = (pedidoPorEvento[idEv] || 0) + (Number(r.cantidad) || 0);
}

for (const idEv of Object.keys(pedidoPorEvento)) {
  if (!idEv) return fail("id_evento vacío en alguna reserva");
  const evento = eventoPorId[idEv];
  if (!evento) return fail("lote no existe: " + idEv);
  const estLote = (String(evento.estado || '').trim().toLowerCase()) || 'activo';
  if (estLote !== 'activo') return fail("lote no activo: " + idEv);
  const genLote = String(evento.genetica || '').trim().toLowerCase();
  if (genLote !== geneticaPedido) {
    return fail("genética del lote " + idEv + " (" + evento.genetica + ") no coincide con la del pedido (" + pedido.genetica + ")");
  }
  const total_neto = (Number(evento.num_esquejes) || 0) - (Number(evento.n_descartados) || 0);
  const reservadoOtros = reservadoPorEvento[idEv] || 0;
  const disponible = total_neto - reservadoOtros;
  const pidoEsteLote = pedidoPorEvento[idEv];
  if (pidoEsteLote > disponible) {
    return fail("stock insuficiente en " + idEv + ": pides " + pidoEsteLote + ", disponible " + disponible);
  }
}

// OK — preparar filas
const baseTs = Date.now();
const reservasToInsert = reservasInput.map((r, i) => ({
  id_reserva: "RP" + baseTs + (i > 0 ? "-" + i : ""),
  id_pedido: idPedido,
  id_evento: String(r.id_evento).trim(),
  cantidad: Number(r.cantidad),
}));

return [{
  json: {
    ok: true,
    error_msg: "",
    id_pedido: idPedido,
    _reservas_to_insert: reservasToInsert,
  }
}];
"""

PREPARAR_FILAS_CODE = r"""const reservas = $('Validar Reserva Pedido').first().json._reservas_to_insert || [];
const hoy = new Date().toISOString().slice(0, 10);
return reservas.map(r => ({
  json: {
    id_reserva: r.id_reserva,
    id_pedido: r.id_pedido,
    id_evento: r.id_evento,
    cantidad: r.cantidad,
    estado: 'reservada',
    fecha_reserva: hoy,
    fecha_consumida: '',
    notas: '',
  }
}));
"""

# ─── Crear nodos ─────────────────────────────────────────────
base_x, base_y = 200, 7100  # Zona libre bajo cancelar (que vive ~6500)

n_webhook = webhook_node("Webhook pedidos-reservar", "pedidos-reservar", [base_x, base_y])
n_prep = code_node("Prepare pedidos-reservar", PREPARE_CODE, [base_x + 200, base_y])
n_read_pedidos = sheet_read_node("Read pedidos (for reservar)", "pedidos",
                                 [base_x + 400, base_y])
n_read_eventos = sheet_read_node("Read eventos_corte (for reservar)", "eventos_corte",
                                 [base_x + 600, base_y])
n_read_reservas = sheet_read_node("Read reservas_pedidos (for reservar)", "reservas_pedidos",
                                  [base_x + 800, base_y])
n_validar = code_node("Validar Reserva Pedido", VALIDAR_CODE, [base_x + 1000, base_y])
n_if = if_node("Reserva Pedido OK?", "={{ $json.ok }}", [base_x + 1200, base_y])
n_preparar_filas = code_node("Preparar Filas Reservas (reservar)", PREPARAR_FILAS_CODE,
                              [base_x + 1400, base_y - 100])
n_append = reservas_append_node("Sheets append reservas_pedidos (reservar)",
                                 [base_x + 1600, base_y - 100])
n_resp_ok = respond_node(
    "Respond pedidos-reservar OK",
    "={{ { \"success\": true, \"data\": { \"id_pedido\": $('Validar Reserva Pedido').first().json.id_pedido, \"reservas\": $('Validar Reserva Pedido').first().json._reservas_to_insert } } }}",
    [base_x + 1800, base_y - 100],
)
n_resp_err = respond_node(
    "Respond Error pedidos-reservar",
    "={{ { \"success\": false, \"error\": $('Validar Reserva Pedido').first().json.error_msg } }}",
    [base_x + 1400, base_y + 200],
)

wf["nodes"].extend([
    n_webhook, n_prep, n_read_pedidos, n_read_eventos, n_read_reservas,
    n_validar, n_if, n_preparar_filas, n_append, n_resp_ok, n_resp_err,
])

# ─── Conexiones ──────────────────────────────────────────────
wf["connections"]["Webhook pedidos-reservar"] = {
    "main": [[{"node": "Prepare pedidos-reservar", "type": "main", "index": 0}]]
}
wf["connections"]["Prepare pedidos-reservar"] = {
    "main": [[{"node": "Read pedidos (for reservar)", "type": "main", "index": 0}]]
}
wf["connections"]["Read pedidos (for reservar)"] = {
    "main": [[{"node": "Read eventos_corte (for reservar)", "type": "main", "index": 0}]]
}
wf["connections"]["Read eventos_corte (for reservar)"] = {
    "main": [[{"node": "Read reservas_pedidos (for reservar)", "type": "main", "index": 0}]]
}
wf["connections"]["Read reservas_pedidos (for reservar)"] = {
    "main": [[{"node": "Validar Reserva Pedido", "type": "main", "index": 0}]]
}
wf["connections"]["Validar Reserva Pedido"] = {
    "main": [[{"node": "Reserva Pedido OK?", "type": "main", "index": 0}]]
}
wf["connections"]["Reserva Pedido OK?"] = {
    "main": [
        [{"node": "Preparar Filas Reservas (reservar)", "type": "main", "index": 0}],
        [{"node": "Respond Error pedidos-reservar", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Preparar Filas Reservas (reservar)"] = {
    "main": [[{"node": "Sheets append reservas_pedidos (reservar)", "type": "main", "index": 0}]]
}
wf["connections"]["Sheets append reservas_pedidos (reservar)"] = {
    "main": [[{"node": "Respond pedidos-reservar OK", "type": "main", "index": 0}]]
}

# ─── PUT ─────────────────────────────────────────────────────
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_gestion_economica_post_pedidos_reservar.json"
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
