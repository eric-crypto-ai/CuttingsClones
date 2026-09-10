"""
Notificaciones_Telegram — workflow nuevo con 7 crons que mandan al grupo
Telegram "CuttingsClones · Avisos" (chat_id en TELEGRAM_CHAT_ID_GRUPO).

Cada cron tiene la estructura:
   Schedule → Read Sheet(s) → Code (filtrar + formatear) → IF (hay algo?) → Telegram

Si el Code determina que no hay nada que avisar, marca {_stop: true} y el IF
corta. Sin spam.

Ramas:
  1. Tareas atrasadas        09:00  diario
  2. Tareas mañana           19:00  diario
  3. Cortes próximos         18:00  diario  (offsets 4 y 2 días)
  4a. Pedidos víspera        18:00  diario  (entrega en +2 días)
  4b. Pedidos hoy            09:00  diario  (entrega hoy)
  5. Cambio semana floración 08:00  diario  (si toca semana nueva)
  6. Resumen cobros mensual  09:00  día 1 de cada mes

Idempotencia: si ya existe un workflow con name='Notificaciones_Telegram',
aborta sin tocar nada.

Requiere:
  - N8N_KEY (env o ~/.n8n_key)
  - TELEGRAM_CHAT_ID_GRUPO (env o ~/.zshrc)
"""
import json
import os
import re
import sys
import uuid
import urllib.request
import urllib.error

BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_NAME = "Notificaciones_Telegram"

SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEETS_CRED_ID = "U9MmYhXUgVdOQej5"
SHEETS_CRED_NAME = "Google Sheets account"

TELEGRAM_CRED_ID = "gIKUgl2QLI4kwXIY"
TELEGRAM_CRED_NAME = "Telegram CuttingClones"


def _load_key(name, fallback_file=None):
    v = os.environ.get(name)
    if v:
        return v
    if fallback_file and os.path.isfile(os.path.expanduser(fallback_file)):
        with open(os.path.expanduser(fallback_file)) as f:
            return f.read().strip()
    return None


def _load_from_zshrc(name):
    path = os.path.expanduser("~/.zshrc")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        for line in f:
            m = re.match(r'^export\s+(\w+)\s*=\s*"?([^"\n]*)"?\s*$', line.strip())
            if m and m.group(1) == name:
                return m.group(2)
    return None


API_KEY = _load_key("N8N_KEY", "~/.n8n_key") or sys.exit("N8N_KEY no encontrado")
CHAT_ID_GRUPO = (
    os.environ.get("TELEGRAM_CHAT_ID_GRUPO")
    or _load_from_zshrc("TELEGRAM_CHAT_ID_GRUPO")
    or sys.exit("TELEGRAM_CHAT_ID_GRUPO no encontrado en env ni ~/.zshrc")
)
HEADERS = {"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}


def n8n_request(method, path, payload=None):
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        return e.code, body


# ─── Helpers para construir nodos ─────────────────────────────────

def _id():
    return str(uuid.uuid4())


def schedule_node(name, hour, minute, pos, day_of_month=None):
    """Schedule Trigger diario a HH:MM o mensual día N a HH:MM."""
    if day_of_month is not None:
        rule = {"interval": [{"field": "months", "monthsInterval": 1,
                              "triggerAtDayOfMonth": day_of_month,
                              "triggerAtHour": hour, "triggerAtMinute": minute}]}
    else:
        rule = {"interval": [{"field": "hours", "hoursInterval": 24,
                              "triggerAtHour": hour, "triggerAtMinute": minute}]}
    return {
        "parameters": {"rule": rule},
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": pos,
    }


def sheets_read_node(name, sheet_name, pos):
    """Read Google Sheet (executeOnce, mode=name)."""
    return {
        "parameters": {
            "documentId": {"__rl": True, "value": SPREADSHEET_ID, "mode": "id"},
            "sheetName": {"__rl": True, "value": sheet_name, "mode": "name"},
            "options": {},
        },
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.5,
        "position": pos,
        "executeOnce": True,
        "credentials": {"googleSheetsOAuth2Api": {"id": SHEETS_CRED_ID, "name": SHEETS_CRED_NAME}},
    }


def code_node(name, jscode, pos):
    return {
        "parameters": {"jsCode": jscode},
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": pos,
    }


def if_continue_node(name, pos, expr="={{ !$json._stop }}"):
    return {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                "conditions": [{
                    "id": _id(),
                    "leftValue": expr,
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }],
                "combinator": "and",
            },
            "options": {},
        },
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": pos,
    }


def telegram_node(name, pos):
    return {
        "parameters": {
            "chatId": "={{ $json.chat_id }}",
            "text": "={{ $json.text }}",
            "additionalFields": {},
        },
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.telegram",
        "typeVersion": 1.2,
        "position": pos,
        "credentials": {"telegramApi": {"id": TELEGRAM_CRED_ID, "name": TELEGRAM_CRED_NAME}},
    }


# ─── Plantillas de jsCode ─────────────────────────────────────────
# CHAT_ID se inyecta literal en cada uno (sin guion al final, ej: -5023756424)

CHAT_ID = int(CHAT_ID_GRUPO)


def code_tareas_filtro(filtro_label, filter_js, header_emoji):
    """Genera jsCode para tareas atrasadas o tareas mañana."""
    return f"""const filas = $input.all().map(i => i.json);
const hoy = new Date(); hoy.setHours(0,0,0,0);
const hoyStr = hoy.toISOString().slice(0,10);
const manana = new Date(hoy); manana.setDate(manana.getDate()+1);
const mananaStr = manana.toISOString().slice(0,10);

const matched = filas.filter(f => {{
  const fecha = String(f.fecha || '').trim();
  const estado = String(f.estado || '').trim().toLowerCase();
  if (estado !== 'pendiente') return false;
  if (!fecha) return false;
  {filter_js}
}});

if (matched.length === 0) return [{{ json: {{ _stop: true }} }}];

const porZona = {{}};
for (const t of matched) {{
  const z = String(t.zona || 'sin zona').toLowerCase();
  if (!porZona[z]) porZona[z] = [];
  porZona[z].push(t);
}}

let texto = '{header_emoji} {filtro_label} (' + matched.length + ')\\n\\n';
const zonas = Object.keys(porZona).sort();
for (const z of zonas) {{
  texto += '• ' + z.toUpperCase() + '\\n';
  porZona[z].sort((a,b) => String(a.fecha).localeCompare(String(b.fecha)));
  for (const t of porZona[z]) {{
    const prio = String(t.prioridad || '').toLowerCase();
    const flag = prio === 'alta' ? '🔴 ' : '';
    texto += '  ' + flag + t.fecha + ' · ' + t.tarea + '\\n';
  }}
  texto += '\\n';
}}

return [{{ json: {{ chat_id: {CHAT_ID}, text: texto.trim() }} }}];
"""


JSCODE_TAREAS_ATRASADAS = code_tareas_filtro(
    "Tareas atrasadas", "return fecha < hoyStr;", "🚨"
)

JSCODE_TAREAS_MANANA = code_tareas_filtro(
    "Tareas para mañana", "return fecha === mananaStr;", "📋"
)

JSCODE_CORTES_PROXIMOS = f"""const filas = $input.all().map(i => i.json);
const hoy = new Date(); hoy.setHours(0,0,0,0);
const OFFSETS = [4, 2];

const candidatos = [];
for (const e of filas) {{
  const estado = String(e.estado || 'activo').toLowerCase();
  if (estado !== 'activo') continue;
  const fp = String(e.fecha_proximo_corte_estimada || '').trim();
  if (!fp) continue;
  const fpDate = new Date(fp + 'T00:00:00Z');
  if (isNaN(fpDate.getTime())) continue;
  const dias = Math.round((fpDate - hoy) / 86400000);
  if (OFFSETS.includes(dias)) {{
    candidatos.push({{ id_evento: e.id_evento, genetica: e.genetica, fp, dias }});
  }}
}}

if (candidatos.length === 0) return [{{ json: {{ _stop: true }} }}];

candidatos.sort((a,b) => a.dias - b.dias);
let texto = '✂️ Próximos cortes\\n\\n';
for (const c of candidatos) {{
  const sufijo = c.dias === 0 ? 'hoy' : (c.dias === 1 ? 'mañana' : 'en ' + c.dias + ' días');
  texto += '• ' + sufijo + ' (' + c.fp + ') — ' + c.genetica + ' · lote ' + c.id_evento + '\\n';
}}

return [{{ json: {{ chat_id: {CHAT_ID}, text: texto.trim() }} }}];
"""


def code_pedidos(offset_dias, label_dia):
    return f"""const filas = $input.all().map(i => i.json);
const hoy = new Date(); hoy.setHours(0,0,0,0);
const OFFSET = {offset_dias};

const candidatos = [];
for (const p of filas) {{
  const estado = String(p.estado || '').trim().toLowerCase();
  if (estado === 'entregado' || estado === 'cancelado') continue;
  const fep = String(p.fecha_entrega_prometida || '').trim();
  if (!fep) continue;
  const fepDate = new Date(fep + 'T00:00:00Z');
  if (isNaN(fepDate.getTime())) continue;
  const dias = Math.round((fepDate - hoy) / 86400000);
  if (dias === OFFSET) {{
    candidatos.push({{ id_pedido: p.id_pedido, id_cliente: p.id_cliente, genetica: p.genetica, cantidad: p.cantidad, total: p.total, fep }});
  }}
}}

if (candidatos.length === 0) return [{{ json: {{ _stop: true }} }}];

let texto = '📦 Pedidos a entregar {label_dia} (' + candidatos.length + ')\\n\\n';
for (const c of candidatos) {{
  texto += '• ' + c.id_pedido + ' — ' + c.cantidad + ' ' + c.genetica + ' · ' + c.total + '€\\n';
  texto += '  cliente ' + c.id_cliente + ' · entrega ' + c.fep + '\\n';
}}

return [{{ json: {{ chat_id: {CHAT_ID}, text: texto.trim() }} }}];
"""


JSCODE_PEDIDOS_VISPERA = code_pedidos(2, "en 2 días")
JSCODE_PEDIDOS_HOY = code_pedidos(0, "HOY")


JSCODE_FLORACION_SEMANA = f"""const filas = $input.all().map(i => i.json);

const data = {{}};
for (const f of filas) {{
  const k = String(f.clave || '').trim();
  const v = String(f.valor || '').trim();
  if (k) data[k] = v;
}}

const fase = (data.fase_actual || '').toLowerCase();
const inicio = data.inicio_floracion || '';

if (fase !== 'floracion' || !inicio) return [{{ json: {{ _stop: true }} }}];

const hoy = new Date(); hoy.setHours(0,0,0,0);
const inicioDate = new Date(inicio + 'T00:00:00Z');
if (isNaN(inicioDate.getTime())) return [{{ json: {{ _stop: true }} }}];

const dias = Math.round((hoy - inicioDate) / 86400000);
if (dias <= 0 || dias % 7 !== 0) return [{{ json: {{ _stop: true }} }}];

const semana = dias / 7 + 1;  // dia 0-6 = semana 1, dia 7 = inicio semana 2, etc.
const ciclo_total_semanas = 9; // ciclo de floracion estandar (modificar si cambia)

let texto = '🌸 Nueva semana de floración\\n\\n';
texto += 'Hoy empieza la SEMANA ' + semana + ' / ' + ciclo_total_semanas + '\\n';
texto += 'Día ' + dias + ' desde el inicio (' + inicio + ')\\n';

return [{{ json: {{ chat_id: {CHAT_ID}, text: texto.trim() }} }}];
"""


JSCODE_COBROS_MENSUAL = f"""const filas = $input.all().map(i => i.json);

// Mes anterior
const hoy = new Date();
const anioActual = hoy.getFullYear();
const mesActual = hoy.getMonth(); // 0-11
const mesAnterior = mesActual === 0 ? 11 : mesActual - 1;
const anioMesAnterior = mesActual === 0 ? anioActual - 1 : anioActual;

const yyyy = anioMesAnterior;
const mm = String(mesAnterior + 1).padStart(2, '0');
const prefijoMes = yyyy + '-' + mm; // "2026-04"

const meses = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
const labelMes = meses[mesAnterior] + ' ' + yyyy;

const cobrosMes = filas.filter(c => String(c.fecha || '').trim().startsWith(prefijoMes));

if (cobrosMes.length === 0) {{
  // No hubo cobros — igual mandamos un breve "sin cobros" para tener pulso del mes
  return [{{ json: {{ chat_id: {CHAT_ID}, text: '💰 Resumen ' + labelMes + '\\n\\nSin cobros registrados este mes.' }} }}];
}}

// Total y desglose por socio
const totalImporte = cobrosMes.reduce((acc, c) => acc + (Number(c.importe) || 0), 0);
const porSocio = {{}};
for (const c of cobrosMes) {{
  const quien = String(c.quien_cobro || 'sin asignar').trim() || 'sin asignar';
  if (!porSocio[quien]) porSocio[quien] = {{ count: 0, importe_directo: 0, suma_reparto: 0 }};
  porSocio[quien].count += 1;
  porSocio[quien].importe_directo += Number(c.importe) || 0;
  porSocio[quien].suma_reparto += Number(c.por_socio_calculado) || 0;
}}

let texto = '💰 Resumen ' + labelMes + '\\n\\n';
texto += '*Total cobrado:* ' + totalImporte + '€ (' + cobrosMes.length + ' cobros)\\n\\n';
texto += '*Reparto por socio:*\\n';
const socios = Object.keys(porSocio).sort();
for (const s of socios) {{
  const p = porSocio[s];
  texto += '• ' + s + ': ' + p.suma_reparto + '€ (de ' + p.count + ' cobros · cobró directo ' + p.importe_directo + '€)\\n';
}}

return [{{ json: {{ chat_id: {CHAT_ID}, text: texto.trim() }} }}];
"""


# ─── Construir las 7 ramas ────────────────────────────────────────

def build_branch(label, schedule_args, sheet_name, jscode, y_offset):
    """Construye una rama: Schedule -> Read -> Code -> IF -> Telegram. y_offset es la fila."""
    BASE_X, COL_W = 240, 220
    nodes = [
        schedule_node(f"Cron {label}", schedule_args["hour"], schedule_args["minute"],
                      [BASE_X, y_offset], schedule_args.get("day_of_month")),
        sheets_read_node(f"Read {sheet_name} ({label})", sheet_name, [BASE_X + COL_W, y_offset]),
        code_node(f"Code {label}", jscode, [BASE_X + COL_W*2, y_offset]),
    ]
    if schedule_args.get("force_send"):
        # No IF — el Code siempre devuelve algo (cobros mensual)
        nodes.append(telegram_node(f"Telegram {label}", [BASE_X + COL_W*3, y_offset]))
    else:
        nodes.append(if_continue_node(f"¿Hay {label}?", [BASE_X + COL_W*3, y_offset]))
        nodes.append(telegram_node(f"Telegram {label}", [BASE_X + COL_W*4, y_offset]))
    return nodes


def build_connections(branches):
    """Conecta los nodos de cada rama linealmente."""
    conns = {}
    for branch in branches:
        # Cada nodo conecta al siguiente. Si hay IF, su rama TRUE va al siguiente.
        for i in range(len(branch) - 1):
            cur = branch[i]
            nxt = branch[i + 1]
            if cur["type"] == "n8n-nodes-base.if":
                # IF tiene 2 outputs (true, false). Solo conectamos el TRUE al telegram.
                conns[cur["name"]] = {"main": [
                    [{"node": nxt["name"], "type": "main", "index": 0}],
                    []  # rama false: vacia (no hace nada)
                ]}
            else:
                conns[cur["name"]] = {"main": [[{"node": nxt["name"], "type": "main", "index": 0}]]}
    return conns


# ─── Definir las ramas ────────────────────────────────────────────

branches_def = [
    {"label": "Tareas Atrasadas", "schedule": {"hour": 9, "minute": 0},
     "sheet": "tareas", "jscode": JSCODE_TAREAS_ATRASADAS, "y": 0},
    {"label": "Tareas Mañana", "schedule": {"hour": 19, "minute": 0},
     "sheet": "tareas", "jscode": JSCODE_TAREAS_MANANA, "y": 200},
    {"label": "Cortes Próximos", "schedule": {"hour": 18, "minute": 0},
     "sheet": "eventos_corte", "jscode": JSCODE_CORTES_PROXIMOS, "y": 400},
    {"label": "Pedidos Víspera", "schedule": {"hour": 18, "minute": 0},
     "sheet": "pedidos", "jscode": JSCODE_PEDIDOS_VISPERA, "y": 600},
    {"label": "Pedidos Hoy", "schedule": {"hour": 9, "minute": 0},
     "sheet": "pedidos", "jscode": JSCODE_PEDIDOS_HOY, "y": 800},
    {"label": "Floración Semana", "schedule": {"hour": 8, "minute": 0},
     "sheet": "info_util", "jscode": JSCODE_FLORACION_SEMANA, "y": 1000},
    {"label": "Cobros Mensual", "schedule": {"hour": 9, "minute": 0, "day_of_month": 1, "force_send": True},
     "sheet": "cobros", "jscode": JSCODE_COBROS_MENSUAL, "y": 1200},
]

all_nodes = []
all_branches = []
for b in branches_def:
    nodes = build_branch(b["label"], b["schedule"], b["sheet"], b["jscode"], b["y"])
    all_nodes.extend(nodes)
    all_branches.append(nodes)

connections = build_connections(all_branches)

workflow_body = {
    "name": WF_NAME,
    "nodes": all_nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}


# ─── Idempotencia: comprobar que no exista ya ─────────────────────
status, existing = n8n_request("GET", "/workflows?limit=250")
if status == 200 and existing:
    items = existing.get("data", []) if isinstance(existing, dict) else existing
    for w in items:
        if w.get("name") == WF_NAME:
            print(f"ABORT: ya existe workflow '{WF_NAME}' (id={w.get('id')}).")
            print("Si quieres redeployar, bórralo o renómbralo en n8n y vuelve a ejecutar.")
            sys.exit(0)


# ─── POST + activar ───────────────────────────────────────────────
print(f"Creando workflow '{WF_NAME}' con {len(all_nodes)} nodos...")
status, result = n8n_request("POST", "/workflows", workflow_body)
if status not in (200, 201):
    raise SystemExit(f"POST /workflows falló: HTTP {status} — {result}")

wf_id = result["id"]
print(f"✓ Creado: id={wf_id}")

# Activar
status, act = n8n_request("POST", f"/workflows/{wf_id}/activate", {})
if status == 200:
    print(f"✓ Activado: active={act.get('active')}, nodos={len(act.get('nodes', []))}")
else:
    print(f"⚠ Activación falló: HTTP {status} — {act}. Actívalo manualmente desde la UI.")

# Snapshot local
NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_notificaciones_telegram.json"
with open(NEW_FILE, "w") as f:
    json.dump(workflow_body, f, indent=2, ensure_ascii=False)
print(f"✓ Snapshot escrito: {NEW_FILE}")

print(f"\nResumen:")
print(f"  - 7 crons activos en workflow '{WF_NAME}' (id={wf_id})")
print(f"  - chat_id destino: {CHAT_ID} (grupo)")
print(f"  - Para verificar manualmente: ejecuta cada cron desde la UI de n8n con 'Execute Workflow'")
