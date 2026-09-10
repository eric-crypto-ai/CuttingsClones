"""
Paso 2 del plan IPM: añade webhook GET /ipm-sugerir al workflow Control_IPM.

Sugiere el producto a aplicar dado un pool (regular_madres / mensual_acaros /
foliar_nutricional), respetando carencias y filtrando opcionalmente por
apto_cosecha.

Algoritmo (FIFO sobre últimas aplicaciones, bloqueado por carencia):
1. Lee productos_ipm filtrado por activo='si' y pool=<X>.
2. Lee Control_IPM (todas las filas históricas).
3. Para cada producto candidato, calcula días desde última aplicación.
4. Filtra los que NO cumplen intervalo_carencia_dias.
5. Devuelve el de mayor dias_desde_ultima como `sugerido` + las siguientes 3
   como `alternativas` + lista de `bloqueados_por_carencia`.

Patrón en serie con executeOnce (lección de CORTES.md §5.3 — n8n no ejecuta
ramas paralelas sin convergencia).
"""
import json, os, sys, uuid, urllib.request

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "CPUlOabXvRrGIVjy"  # Control_IPM
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
GID_PRODUCTOS = 1951917119
GID_CONTROL = 0
SHEETS_CRED = {"id": "U9MmYhXUgVdOQej5", "name": "Google Sheets account"}

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))
print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")


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


SUGERIR_CODE = r"""const productos = $('Read productos_ipm Sugerir').all().map(i => i.json);
const aplicaciones = $('Read Control_IPM Sugerir').all().map(i => i.json);

const trigger = $('Webhook IPM Sugerir').first().json;
const pool = String((trigger.query && trigger.query.pool) || '').trim();
const aptoCosechaParam = String((trigger.query && trigger.query.apto_cosecha) || '').trim().toLowerCase();
const filtraAptoCosecha = aptoCosechaParam === 'si' || aptoCosechaParam === 'true';
const dosisModo = String((trigger.query && trigger.query.dosis_modo) || 'preventiva').trim().toLowerCase();
const zona = String((trigger.query && trigger.query.zona) || '').trim();

if (!pool) {
  return [{ json: {
    success: false,
    error: "query param 'pool' requerido (regular_madres / mensual_acaros / foliar_nutricional)"
  } }];
}

// Parsear fecha tolerando 'DD/MM/YYYY' y 'YYYY-MM-DD'
function parseFecha(s) {
  if (!s) return null;
  s = String(s).trim();
  const m1 = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (m1) {
    const dt = new Date(Number(m1[3]), Number(m1[2]) - 1, Number(m1[1]));
    return isNaN(dt.getTime()) ? null : dt;
  }
  const m2 = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m2) {
    const dt = new Date(Number(m2[1]), Number(m2[2]) - 1, Number(m2[3]));
    return isNaN(dt.getTime()) ? null : dt;
  }
  const fallback = new Date(s);
  return isNaN(fallback.getTime()) ? null : fallback;
}

// Última aplicación por producto (matching exacto sobre Control_IPM.producto)
const ultimaPorProducto = {};
for (const a of aplicaciones) {
  const prod = String(a.producto || '').trim();
  if (!prod) continue;
  const fecha = parseFecha(a.fecha);
  if (!fecha) continue;
  if (!ultimaPorProducto[prod] || fecha > ultimaPorProducto[prod]) {
    ultimaPorProducto[prod] = fecha;
  }
}

const hoy = new Date();
hoy.setHours(0, 0, 0, 0);

const candidatos = productos
  .filter(p => String(p.activo || '').trim().toLowerCase() === 'si')
  .filter(p => String(p.pool || '').trim() === pool)
  .filter(p => !filtraAptoCosecha || String(p.apto_cosecha || '').trim().toLowerCase() === 'si')
  .map(p => {
    const ult = ultimaPorProducto[p.producto];
    const dias = ult ? Math.floor((hoy - ult) / (1000 * 60 * 60 * 24)) : 9999;
    const carencia = Number(p.intervalo_carencia_dias) || 0;
    const cumple = dias >= carencia;
    let dosis = '';
    if (dosisModo === 'curativa' && p.dosis_curativa) dosis = p.dosis_curativa;
    else dosis = p.dosis_preventiva || p.dosis_curativa || '';
    return {
      producto: p.producto,
      principio_activo: p.principio_activo,
      familia_irac: p.familia_irac,
      target_principal: p.target_principal,
      agresividad: p.agresividad,
      dosis_sugerida: dosis,
      apto_cosecha: p.apto_cosecha,
      pool: p.pool,
      dias_desde_ultima: dias,
      carencia_minima: carencia,
      cumple_carencia: cumple,
    };
  });

if (candidatos.length === 0) {
  return [{ json: {
    success: true, pool, zona, apto_cosecha: filtraAptoCosecha,
    sugerido: null, alternativas: [], bloqueados_por_carencia: [],
    motivo: "No hay productos catalogados en este pool con los filtros aplicados."
  } }];
}

const elegibles = candidatos.filter(c => c.cumple_carencia);
elegibles.sort((a, b) => b.dias_desde_ultima - a.dias_desde_ultima);

const sugerido = elegibles[0] || null;

let motivoSugerencia = '';
if (sugerido) {
  if (sugerido.dias_desde_ultima === 9999) {
    motivoSugerencia = `Producto sin aplicaciones registradas — primer uso recomendado.`;
  } else {
    motivoSugerencia = `${sugerido.dias_desde_ultima}d desde la ultima aplicacion (carencia minima ${sugerido.carencia_minima}d).`;
  }
}

return [{ json: {
  success: true,
  pool,
  zona,
  apto_cosecha: filtraAptoCosecha,
  dosis_modo: dosisModo,
  sugerido: sugerido ? { ...sugerido, motivo: motivoSugerencia } : null,
  alternativas: elegibles.slice(1, 4),
  bloqueados_por_carencia: candidatos.filter(c => !c.cumple_carencia).map(c => ({
    producto: c.producto,
    dias_desde_ultima: c.dias_desde_ultima,
    carencia_minima: c.carencia_minima,
    le_falta_dias: Math.max(0, c.carencia_minima - c.dias_desde_ultima),
  })),
} }];
"""

# Posicionar nodos en zona libre — los webhooks IPM están en x=-928, y=112/560/1008
# Pongo el nuevo abajo del último (y=1456)
base_x, base_y = -928, 1456

n_webhook = webhook_node("Webhook IPM Sugerir", "ipm-sugerir", [base_x, base_y])
n_read_prod = sheet_read_node("Read productos_ipm Sugerir", GID_PRODUCTOS, "productos_ipm",
                                [base_x + 220, base_y], execute_once=True)
n_read_ctrl = sheet_read_node("Read Control_IPM Sugerir", GID_CONTROL, "Control_IPM",
                                [base_x + 440, base_y], execute_once=True)
n_code = code_node("Calcular Sugerencia IPM", SUGERIR_CODE, [base_x + 660, base_y])
n_respond = respond_node("Respond IPM Sugerir", [base_x + 880, base_y])

wf["nodes"].extend([n_webhook, n_read_prod, n_read_ctrl, n_code, n_respond])

wf["connections"]["Webhook IPM Sugerir"] = {
    "main": [[{"node": "Read productos_ipm Sugerir", "type": "main", "index": 0}]]
}
wf["connections"]["Read productos_ipm Sugerir"] = {
    "main": [[{"node": "Read Control_IPM Sugerir", "type": "main", "index": 0}]]
}
wf["connections"]["Read Control_IPM Sugerir"] = {
    "main": [[{"node": "Calcular Sugerencia IPM", "type": "main", "index": 0}]]
}
wf["connections"]["Calcular Sugerencia IPM"] = {
    "main": [[{"node": "Respond IPM Sugerir", "type": "main", "index": 0}]]
}

body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

NEW_FILE = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_control_ipm_post_sugerir.json"
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
