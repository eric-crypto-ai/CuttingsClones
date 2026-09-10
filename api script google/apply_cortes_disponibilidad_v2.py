"""
v2: corrige el patrón anterior (rama paralela falla porque n8n no ejecuta
ramas sin convergencia). Pasa a patrón en serie con executeOnce=true en
los nodos Sheets para que actúen como barrera (1 ejecución por nodo,
independientemente del nº de items recibidos).

Patrón final cortes-lista:
  Webhook Lista Cortes
    → Leer Reservas para Lista (executeOnce)
    → Leer Eventos para Lista (executeOnce)
    → Formatear Lista (Code, lee ambos por nombre)
    → Respuesta Lista

Patrón final cortes-disponibilidad: idéntico, con sus propios nodos.
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

# Re-leer el workflow actual desde n8n (puede haber cambiado tras el PUT v1)
req = urllib.request.Request(
    f"{BASE}/workflows/{WF_ID}",
    headers={"X-N8N-API-KEY": API_KEY},
)
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))

print(f"Workflow actual: {len(wf['nodes'])} nodos")

# Eliminar TODOS los nodos de las ramas Lista y Disponibilidad para reconstruir limpio.
# Mantengo solo la rama cortes-crear (intacta).
crear_keep = {
    "Webhook Crear Corte",
    "Leer Eventos Existentes",
    "Preparar Evento",
    "Guardar Evento",
    "Preparar Tarea",
    "Guardar Tarea",
    "Respuesta Crear OK",
}

# Quedarse solo con los nodos de la rama crear
wf["nodes"] = [n for n in wf["nodes"] if n["name"] in crear_keep]
# Quedarse solo con las connections de la rama crear
wf["connections"] = {k: v for k, v in wf["connections"].items() if k in crear_keep}
print(f"Tras limpieza (solo crear): {len(wf['nodes'])} nodos")


def sheet_read_node(name, gid, sheet_label, pos, execute_once=False):
    node = {
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


# ===== RAMA cortes-lista =====
FORMATEAR_LISTA_CODE = r"""const eventos = $('Leer Eventos para Lista').all().map(i => i.json);
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

webhook_lista = webhook_node("Webhook Lista Cortes", "cortes-lista", [200, 600])
leer_reservas_lista = sheet_read_node(
    "Leer Reservas para Lista", GID_RESERVAS, "reservas_pedidos", [420, 600], execute_once=True
)
leer_eventos_lista = sheet_read_node(
    "Leer Eventos para Lista", GID_EVENTOS, "eventos_corte", [640, 600], execute_once=True
)
formatear_lista = code_node("Formatear Lista", FORMATEAR_LISTA_CODE, [860, 600])
respuesta_lista = respond_node("Respuesta Lista", [1080, 600])

wf["nodes"].extend([
    webhook_lista, leer_reservas_lista, leer_eventos_lista, formatear_lista, respuesta_lista
])

wf["connections"]["Webhook Lista Cortes"] = {
    "main": [[{"node": "Leer Reservas para Lista", "type": "main", "index": 0}]]
}
wf["connections"]["Leer Reservas para Lista"] = {
    "main": [[{"node": "Leer Eventos para Lista", "type": "main", "index": 0}]]
}
wf["connections"]["Leer Eventos para Lista"] = {
    "main": [[{"node": "Formatear Lista", "type": "main", "index": 0}]]
}
wf["connections"]["Formatear Lista"] = {
    "main": [[{"node": "Respuesta Lista", "type": "main", "index": 0}]]
}

# ===== RAMA cortes-disponibilidad =====
DISPONIBILIDAD_CODE = r"""const eventos = $('Leer Eventos Disponibilidad').all().map(i => i.json);
const reservas = $('Leer Reservas Disponibilidad').all().map(i => i.json);

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
leer_reservas_disp = sheet_read_node(
    "Leer Reservas Disponibilidad", GID_RESERVAS, "reservas_pedidos", [420, 920], execute_once=True
)
leer_eventos_disp = sheet_read_node(
    "Leer Eventos Disponibilidad", GID_EVENTOS, "eventos_corte", [640, 920], execute_once=True
)
calc_disp = code_node("Calcular Disponibilidad", DISPONIBILIDAD_CODE, [860, 920])
respuesta_disp = respond_node("Respuesta Disponibilidad", [1080, 920])

wf["nodes"].extend([
    webhook_disp, leer_reservas_disp, leer_eventos_disp, calc_disp, respuesta_disp
])

wf["connections"]["Webhook Disponibilidad"] = {
    "main": [[{"node": "Leer Reservas Disponibilidad", "type": "main", "index": 0}]]
}
wf["connections"]["Leer Reservas Disponibilidad"] = {
    "main": [[{"node": "Leer Eventos Disponibilidad", "type": "main", "index": 0}]]
}
wf["connections"]["Leer Eventos Disponibilidad"] = {
    "main": [[{"node": "Calcular Disponibilidad", "type": "main", "index": 0}]]
}
wf["connections"]["Calcular Disponibilidad"] = {
    "main": [[{"node": "Respuesta Disponibilidad", "type": "main", "index": 0}]]
}

# ===== PUT =====
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_cortes_post_disponibilidad_v2.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"Nodos finales: {len(body['nodes'])}")
print(f"JSON: {NEW_FILE}")

req = urllib.request.Request(
    f"{BASE}/workflows/{WF_ID}",
    data=json.dumps(body).encode("utf-8"),
    method="PUT",
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
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
