"""
Aplica la extensión del workflow Cortes:
1. Añade rama paralela `Leer Reservas para Lista` desde `Webhook Lista Cortes`.
2. Reemplaza Code `Formatear Lista` para devolver total_neto/reservado/disponible/reservas_activas.
3. Crea nueva rama completa para webhook GET /cortes-disponibilidad.

Diseño documentado en <VAULT>/03 Stack/n8n_workflows/CORTES.md.
"""
import json
import os
import sys
import uuid
import urllib.request

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "H3rtLs6wi4Yty91S"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
GID_EVENTOS = 1143539242
GID_RESERVAS = 793345778
SHEETS_CRED = {"id": "U9MmYhXUgVdOQej5", "name": "Google Sheets account"}

BACKUP = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_cortes_backup_pre_disponibilidad.json"

with open(BACKUP) as f:
    wf = json.load(f)


def sheet_read_node(name, gid, sheet_label, pos):
    return {
        "parameters": {
            "documentId": {
                "__rl": True,
                "value": SPREADSHEET_ID,
                "mode": "list",
                "cachedResultName": "Control_IPM",
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=drivesdk",
            },
            "sheetName": {
                "__rl": True,
                "value": gid,
                "mode": "list",
                "cachedResultName": sheet_label,
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={gid}",
            },
            "options": {},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "position": pos,
        "credentials": {"googleSheetsOAuth2Api": SHEETS_CRED},
        "alwaysOutputData": True,
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


def webhook_node(name, path, pos):
    return {
        "parameters": {
            "httpMethod": "GET",
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


def respond_node(name, pos):
    return {
        "parameters": {
            "respondWith": "json",
            "responseBody": "={{ $json }}",
            "options": {},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.5,
        "position": pos,
    }


# ---- 1. Reemplazar Code "Formatear Lista" con la versión que incluye disponibilidad ----
NEW_FORMATEAR_LISTA_CODE = r"""const eventos = $('Leer Eventos para Lista').all().map(i => i.json);
const reservas = $('Leer Reservas para Lista').all().map(i => i.json);

// Reservas que cuentan como ocupadas (reservada + consumida)
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
      estado: String(f.estado || '').trim(),
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
        n["parameters"]["jsCode"] = NEW_FORMATEAR_LISTA_CODE
        break

# ---- 2. Añadir nodo Leer Reservas para Lista (rama paralela del Webhook Lista Cortes) ----
leer_reservas_lista = sheet_read_node(
    "Leer Reservas para Lista", GID_RESERVAS, "reservas_pedidos", [420, 760]
)
wf["nodes"].append(leer_reservas_lista)

# ---- 3. Crear rama completa para cortes-disponibilidad ----
NEW_DISPONIBILIDAD_CODE = r"""const eventos = $('Leer Eventos Disponibilidad').all().map(i => i.json);
const reservas = $('Leer Reservas Disponibilidad').all().map(i => i.json);

// Query param genetica (n8n v2.1: $json.query.<key>)
const trigger = $('Webhook Disponibilidad').first().json;
const geneticaFilter = String((trigger.query && trigger.query.genetica) || '').trim().toLowerCase();

const reservasPorEvento = {};
for (const r of reservas) {
  const idEvento = String(r.id_evento || '').trim();
  if (!idEvento) continue;
  const estado = String(r.estado || '').trim().toLowerCase();
  if (estado === 'reservada' || estado === 'consumida') {
    reservasPorEvento[idEvento] = (reservasPorEvento[idEvento] || 0) + (Number(r.cantidad) || 0);
  }
}

const items = eventos
  .map(f => {
    const id_evento = String(f.id_evento || '').trim();
    const estado = String(f.estado || '').trim().toLowerCase() || 'activo';
    const num_esquejes = Number(f.num_esquejes) || 0;
    const n_descartados = Number(f.n_descartados) || 0;
    const total_neto = num_esquejes - n_descartados;
    const reservado = reservasPorEvento[id_evento] || 0;
    return {
      id_evento,
      genetica: String(f.genetica || '').trim(),
      fecha_corte: String(f.fecha_corte || '').trim(),
      total_neto,
      reservado,
      disponible: total_neto - reservado,
      estado,
    };
  })
  .filter(e => e.id_evento)
  .filter(e => e.estado === 'activo')
  .filter(e => !geneticaFilter || e.genetica.toLowerCase() === geneticaFilter)
  .filter(e => e.disponible > 0)
  .sort((a, b) => (a.fecha_corte || '').localeCompare(b.fecha_corte || ''));

return [{ json: { items } }];
"""

webhook_disp = webhook_node("Webhook Disponibilidad", "cortes-disponibilidad", [200, 920])
leer_eventos_disp = sheet_read_node(
    "Leer Eventos Disponibilidad", GID_EVENTOS, "eventos_corte", [420, 920]
)
leer_reservas_disp = sheet_read_node(
    "Leer Reservas Disponibilidad", GID_RESERVAS, "reservas_pedidos", [420, 1080]
)
calc_disp = code_node("Calcular Disponibilidad", NEW_DISPONIBILIDAD_CODE, [640, 920])
respuesta_disp = respond_node("Respuesta Disponibilidad", [860, 920])

wf["nodes"].extend([webhook_disp, leer_eventos_disp, leer_reservas_disp, calc_disp, respuesta_disp])

# ---- 4. Conexiones ----
# Webhook Lista Cortes → ahora también dispara Leer Reservas para Lista (rama paralela)
wf["connections"]["Webhook Lista Cortes"]["main"][0].append(
    {"node": "Leer Reservas para Lista", "type": "main", "index": 0}
)

# Conexiones de la rama nueva cortes-disponibilidad
wf["connections"]["Webhook Disponibilidad"] = {
    "main": [[
        {"node": "Leer Eventos Disponibilidad", "type": "main", "index": 0},
        {"node": "Leer Reservas Disponibilidad", "type": "main", "index": 0},
    ]]
}
wf["connections"]["Leer Eventos Disponibilidad"] = {
    "main": [[{"node": "Calcular Disponibilidad", "type": "main", "index": 0}]]
}
wf["connections"]["Calcular Disponibilidad"] = {
    "main": [[{"node": "Respuesta Disponibilidad", "type": "main", "index": 0}]]
}
# (Leer Reservas Disponibilidad no tiene salida — el Code lo lee por nombre)

# ---- 5. Construir body del PUT (whitelist: name, nodes, connections, settings) ----
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

# Guardar el JSON propuesto antes de enviar (para auditoría)
NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_cortes_post_disponibilidad.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"Workflow propuesto: {NEW_FILE}")
print(f"Nodos: {len(body['nodes'])} (antes: 11)")

# ---- 6. PUT ----
req = urllib.request.Request(
    f"{BASE}/workflows/{WF_ID}",
    data=json.dumps(body).encode("utf-8"),
    method="PUT",
    headers={
        "X-N8N-API-KEY": API_KEY,
        "Content-Type": "application/json",
    },
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"PUT status: {resp.status}")
        result = json.loads(resp.read().decode("utf-8"))
        print(f"  active: {result.get('active')}")
        print(f"  nodes: {len(result.get('nodes', []))}")
except urllib.error.HTTPError as e:
    print(f"PUT FAILED: {e.code} {e.reason}")
    print(e.read().decode("utf-8"))
    sys.exit(1)
