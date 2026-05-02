"""
Aviso Telegram en el cron 25d — extensión de la regla 3.

Modifica el workflow Cortes para que, además de auto-cerrar lotes a 25d sin
reservas pendientes, mande un mensaje a Telegram cuando hay lotes a 25d+
**con reservas `estado=reservada` pendientes** (los que el cron NO cierra
automáticamente). Si no hay alertas, no manda nada.

Cambios:
  1. Reemplaza el jsCode de "Calcular Eventos Caducados 25d" para que
     devuelva también `{ has_alertas, alertas: [...] }`.
  2. Añade nodos en una rama paralela desde "Calcular":
       Calcular → IF Hay Alertas Telegram?
                     ├─ TRUE  → Format Mensaje Telegram → Telegram sendMessage → Cron Fin Alertas
                     └─ FALSE → Cron Fin Alertas
  3. Crea credencial `telegramApi` en n8n (cifrada) con accessToken leído
     de TELEGRAM_BOT_TOKEN. El JSON del workflow solo referencia la
     credencial por ID — el token nunca queda en el repo.

Lectura de secretos (en este orden):
  1. Variables de entorno TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.
  2. ~/.zshrc parseado (export TELEGRAM_BOT_TOKEN="..." / export TELEGRAM_CHAT_ID="...").
  3. Falla si no se encuentran.

Idempotente:
  - Aborta si ya existe el nodo "Telegram sendMessage 25d".
  - Reusa credencial Telegram si ya existe una llamada "Telegram CuttingClones".

Requisitos:
  - N8N_KEY (env o ~/.n8n_key)
  - TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (env o ~/.zshrc)
"""
import json
import os
import re
import sys
import uuid
import urllib.request
import urllib.error

BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "H3rtLs6wi4Yty91S"
CRED_NAME = "Telegram CuttingClones"
CRED_TYPE = "telegramApi"

GESTION_URL = "https://eric-crypto-ai.github.io/CuttingsClones/gestion.html?tab=cortes"


def _load_n8n_key():
    key = os.environ.get("N8N_KEY")
    if key:
        return key
    path = os.path.expanduser("~/.n8n_key")
    if os.path.isfile(path):
        with open(path) as f:
            return f.read().strip()
    raise SystemExit("N8N_KEY no está en env ni en ~/.n8n_key")


def _load_from_zshrc(*names):
    out = {n: None for n in names}
    path = os.path.expanduser("~/.zshrc")
    if not os.path.isfile(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^export\s+(\w+)\s*=\s*"([^"]*)"\s*$', line)
            if m and m.group(1) in out:
                out[m.group(1)] = m.group(2)
    return out


def _load_telegram():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        from_rc = _load_from_zshrc("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
        token = token or from_rc["TELEGRAM_BOT_TOKEN"]
        chat = chat or from_rc["TELEGRAM_CHAT_ID"]
    if not (token and chat):
        raise SystemExit("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no encontrados en env ni en ~/.zshrc")
    return token, chat


API_KEY = _load_n8n_key()
TG_TOKEN, TG_CHAT_ID = _load_telegram()
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


# ─── 1. Crear o reusar credencial Telegram ───────────────────
status, body = n8n_request("POST", "/credentials", {
    "name": CRED_NAME,
    "type": CRED_TYPE,
    "data": {"accessToken": TG_TOKEN},
})

if status in (200, 201):
    CRED_ID = body["id"]
    print(f"Credencial creada: {CRED_NAME} (id={CRED_ID})")
elif status == 400 and "already exists" in str(body).lower():
    # n8n no devuelve listado por API pública, así que si falla por duplicado
    # pedimos al usuario el ID manualmente
    raise SystemExit(
        f"Credencial '{CRED_NAME}' ya existe en n8n pero la API pública no permite listarlas.\n"
        f"Edita este script y pega el ID manualmente, o renombra la credencial existente."
    )
else:
    raise SystemExit(f"Error creando credencial: HTTP {status} — {body}")


# ─── 2. Leer workflow vivo ───────────────────────────────────
status, wf = n8n_request("GET", f"/workflows/{WF_ID}")
if status != 200:
    raise SystemExit(f"No se pudo leer el workflow: HTTP {status}")

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")

existing = {n["name"] for n in wf["nodes"]}
if "Telegram sendMessage 25d" in existing:
    print("ABORT: 'Telegram sendMessage 25d' ya existe — el aviso Telegram ya está aplicado.")
    sys.exit(0)

if "Calcular Eventos Caducados 25d" not in existing:
    raise SystemExit("FATAL: 'Calcular Eventos Caducados 25d' no existe — primero lanza apply_cortes_cron_25d.py")


# ─── 3. Reemplazar jsCode de Calcular para incluir alertas ──
NUEVO_CALCULAR = r"""const eventos = $('Read eventos_corte (cron)').all().map(i => i.json);
const reservas = $('Read reservas_pedidos (cron)').all().map(i => i.json);

const hoyStr = new Date().toISOString().slice(0, 10);
const hoyMs = new Date(hoyStr + 'T00:00:00Z').getTime();
const DIAS_LIMITE = 25;

// Mapa de reservas pendientes (estado=reservada) por evento
const reservasPorEvento = {};
for (const r of reservas) {
  const est = String(r.estado || '').trim().toLowerCase();
  if (est !== 'reservada') continue;
  const id = String(r.id_evento || '').trim();
  if (!id) continue;
  if (!reservasPorEvento[id]) reservasPorEvento[id] = { count: 0, cantidad: 0 };
  reservasPorEvento[id].count += 1;
  reservasPorEvento[id].cantidad += Number(r.cantidad) || 0;
}

const aCerrar = [];
const alertas = [];

for (const e of eventos) {
  const idEvento = String(e.id_evento || '').trim();
  if (!idEvento) continue;
  const estado = (String(e.estado || '').trim().toLowerCase()) || 'activo';
  if (estado !== 'activo') continue;

  const fecha_corte = String(e.fecha_corte || '').trim();
  if (!fecha_corte) continue;
  const corteMs = new Date(fecha_corte + 'T00:00:00Z').getTime();
  if (isNaN(corteMs)) continue;
  const dias = Math.floor((hoyMs - corteMs) / 86400000);
  if (dias < DIAS_LIMITE) continue;

  const pendientes = reservasPorEvento[idEvento];
  if (pendientes) {
    alertas.push({
      id_evento: idEvento,
      genetica: String(e.genetica || '').trim(),
      dias,
      reservas_count: pendientes.count,
      reservas_cantidad: pendientes.cantidad,
    });
  } else {
    aCerrar.push({
      id_evento: idEvento,
      estado: 'cerrado',
      fecha_cierre: hoyStr,
      motivo_cierre: 'caducado_25d',
    });
  }
}

return [{
  json: {
    has_caducados: aCerrar.length > 0,
    eventos: aCerrar,
    has_alertas: alertas.length > 0,
    alertas,
  }
}];
"""

for n in wf["nodes"]:
    if n["name"] == "Calcular Eventos Caducados 25d":
        n["parameters"]["jsCode"] = NUEVO_CALCULAR
        print("  Actualizado: Calcular Eventos Caducados 25d (incluye alertas)")
        calc_pos = n["position"]
        break


# ─── 4. Helpers para nodos nuevos ────────────────────────────
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


def noop_node(name, pos):
    return {
        "parameters": {},
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.noOp",
        "typeVersion": 1,
        "position": pos,
    }


def telegram_node(name, pos, cred_id, cred_name):
    return {
        "parameters": {
            "chatId": "={{ $json.chat_id }}",
            "text": "={{ $json.text }}",
            "additionalFields": {},
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "n8n-nodes-base.telegram",
        "typeVersion": 1.2,
        "position": pos,
        "credentials": {"telegramApi": {"id": cred_id, "name": cred_name}},
    }


# ─── 5. Crear nodos del path Telegram ───────────────────────
FORMAT_MSG_CODE = r"""const data = $('Calcular Eventos Caducados 25d').first().json;
const alertas = data.alertas || [];

let texto = '⚠️ Lotes con 25d+ y reservas pendientes (' + alertas.length + ')\n\n';
for (const a of alertas) {
  texto += '• ' + a.id_evento + ' — ' + a.dias + 'd — ' + a.reservas_cantidad + ' reservados\n';
}
texto += '\nRevisar manualmente:\n' + """ + json.dumps(GESTION_URL) + r""";

return [{
  json: {
    chat_id: """ + str(int(TG_CHAT_ID)) + r""",
    text: texto,
  }
}];
"""

base_x, base_y = calc_pos[0], calc_pos[1] + 320
n_if_alertas = if_node("Hay Alertas Telegram?", "={{ $json.has_alertas }}",
                       [base_x + 200, base_y])
n_format = code_node("Format Mensaje Telegram", FORMAT_MSG_CODE,
                     [base_x + 400, base_y - 100])
n_send = telegram_node("Telegram sendMessage 25d",
                       [base_x + 600, base_y - 100], CRED_ID, CRED_NAME)
n_fin_alertas = noop_node("Cron Fin Alertas", [base_x + 800, base_y])

wf["nodes"].extend([n_if_alertas, n_format, n_send, n_fin_alertas])


# ─── 6. Conexiones ───────────────────────────────────────────
# Calcular ya conecta a "Hay Caducados?" como rama del cierre.
# Añadimos un segundo destino desde Calcular hacia "Hay Alertas Telegram?".
calcular_main = wf["connections"].get("Calcular Eventos Caducados 25d", {}).get("main", [[]])
# main[0] es la lista del primer índice de output; añadimos el segundo destino
calcular_main[0].append({"node": "Hay Alertas Telegram?", "type": "main", "index": 0})
wf["connections"].setdefault("Calcular Eventos Caducados 25d", {})["main"] = calcular_main

wf["connections"]["Hay Alertas Telegram?"] = {
    "main": [
        [{"node": "Format Mensaje Telegram", "type": "main", "index": 0}],
        [{"node": "Cron Fin Alertas", "type": "main", "index": 0}],
    ]
}
wf["connections"]["Format Mensaje Telegram"] = {
    "main": [[{"node": "Telegram sendMessage 25d", "type": "main", "index": 0}]]
}
wf["connections"]["Telegram sendMessage 25d"] = {
    "main": [[{"node": "Cron Fin Alertas", "type": "main", "index": 0}]]
}


# ─── 7. PUT ──────────────────────────────────────────────────
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_cortes_post_cron_telegram.json"
with open(NEW_FILE, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"Snapshot escrito: {NEW_FILE}")
print(f"Nodos finales: {len(body['nodes'])}")

status, result = n8n_request("PUT", f"/workflows/{WF_ID}", body)
if status == 200:
    print(f"PUT status: {status}, active: {result.get('active')}, nodes: {len(result.get('nodes', []))}")
else:
    print(f"PUT FAILED: {status} — {result}")
    sys.exit(1)
