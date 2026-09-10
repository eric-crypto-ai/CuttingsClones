"""
Cortes — generar 4 tareas asociadas al lote en cada `/cortes-crear`.

Reescribe el jsCode del nodo `Preparar Tarea` del workflow Cortes
(WF_ID=H3rtLs6wi4Yty91S) para devolver 4 items en lugar de 1:

  #1 +3d  esquejes media — Pulverizar Clonex Mist             (obs: trazabilidad)
  #2 +6d  esquejes media — Pulverizar Formulez+Rhyzo          (obs: dosis)
  #3 +9d  esquejes media — Sumergir Formulez+Rhyzo            (obs: dosis + PH:5,8)
  #4 +intervalo_dias madres ALTA — Evaluar vigor (la antigua) (obs: trazabilidad)

Las 4 heredan id_evento_origen y tipo_origen='corte'. El nodo Guardar Tarea
(operation: append) itera sobre los N items recibidos sin cambios.

Idempotente: si el jsCode ya contiene la nueva lógica (marker `// 4 tareas`),
el script aborta sin hacer PUT.

Requiere: N8N_KEY (env o ~/.n8n_key).
"""
import json
import os
import sys
import urllib.request
import urllib.error

BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "H3rtLs6wi4Yty91S"
NODE_NAME = "Preparar Tarea"
MARKER = "// 4 tareas asociadas al lote"

NEW_JSCODE = r"""const evento = $('Preparar Evento').first().json;

// Calcular fecha = fecha_corte + N dias (UTC, mismo metodo que Preparar Evento)
function offsetDate(baseISO, days) {
  const d = new Date(baseISO + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + days);
  return d.getUTCFullYear() + '-' +
    String(d.getUTCMonth() + 1).padStart(2, '0') + '-' +
    String(d.getUTCDate()).padStart(2, '0');
}

const trazabilidad = 'Generada por evento ' + evento.id_evento +
  ' (corte ' + evento.fecha_corte + ', ' + evento.num_esquejes + ' esquejes)';

// 4 tareas asociadas al lote — 3 mirando al esqueje + 1 a la madre
const tareas = [
  {
    offset_dias: 3,
    zona: 'esquejes',
    prioridad: 'media',
    tarea: 'Pulverizar bandejas lote ' + evento.id_evento + ' con Clonex Mist',
    observaciones: trazabilidad
  },
  {
    offset_dias: 6,
    zona: 'esquejes',
    prioridad: 'media',
    tarea: 'Pulverizar bandejas lote ' + evento.id_evento + ' con Formulez y Rhyzotonic',
    observaciones: 'Formulez 3ml/litro de agua y Rhyzo 4ml por litro de agua.'
  },
  {
    offset_dias: 9,
    zona: 'esquejes',
    prioridad: 'media',
    tarea: 'Sumergir bandejas lote ' + evento.id_evento + ' con Formulez y Rhyzotonic',
    observaciones: 'Formulez 3ml/litro de agua y Rhyzo 4ml por litro de agua. PH:5,8'
  },
  {
    offset_dias: evento.intervalo_dias,
    zona: 'madres',
    prioridad: 'alta',
    tarea: 'Evaluar vigor — proximo corte ' + evento.genetica,
    observaciones: trazabilidad
  }
];

// id unico por tarea: T + (timestamp+i) + 3 random — patron Crear_Tarea
// El +i garantiza unicidad aunque las 4 ejecuten en el mismo milisegundo
const baseTs = Date.now();
return tareas.map((t, i) => ({
  json: {
    id: 'T' + (baseTs + i) + String(Math.floor(Math.random() * 900 + 100)),
    zona: t.zona,
    tarea: t.tarea,
    prioridad: t.prioridad,
    estado: 'pendiente',
    fecha: offsetDate(evento.fecha_corte, t.offset_dias),
    recurrente: '',
    dia_recurrencia: '',
    observaciones: t.observaciones,
    id_evento_origen: evento.id_evento,
    tipo_origen: 'corte'
  }
}));"""


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


# 1. Leer workflow vivo
status, wf = n8n_request("GET", f"/workflows/{WF_ID}")
if status != 200:
    raise SystemExit(f"GET workflow falló: HTTP {status} — {wf}")

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos, active={wf.get('active')}")

# 2. Localizar nodo y aplicar idempotencia
target = None
for n in wf["nodes"]:
    if n["name"] == NODE_NAME:
        target = n
        break
if target is None:
    raise SystemExit(f"FATAL: nodo '{NODE_NAME}' no existe en el workflow live")

current = target["parameters"].get("jsCode", "")
if MARKER in current:
    print(f"ABORT: el nodo '{NODE_NAME}' ya contiene la nueva lógica (marker '{MARKER}'). Nada que hacer.")
    sys.exit(0)

# 3. Reescribir jsCode
target["parameters"]["jsCode"] = NEW_JSCODE
print(f"  Actualizado jsCode de '{NODE_NAME}' (líneas: {current.count(chr(10))+1} → {NEW_JSCODE.count(chr(10))+1})")

# 4. PUT
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

status, result = n8n_request("PUT", f"/workflows/{WF_ID}", body)
if status == 200:
    print(f"PUT OK: HTTP {status}, active={result.get('active')}, nodes={len(result.get('nodes', []))}")
else:
    print(f"PUT FALLÓ: HTTP {status} — {result}")
    sys.exit(1)

# 5. Confirmación: re-leer y verificar el marker
status, wf2 = n8n_request("GET", f"/workflows/{WF_ID}")
if status == 200:
    after = next((n for n in wf2["nodes"] if n["name"] == NODE_NAME), None)
    if after and MARKER in after["parameters"].get("jsCode", ""):
        print("✓ Verificación post-PUT: marker presente en el workflow live.")
    else:
        print("⚠ Verificación post-PUT: el marker NO está en el workflow live. Revisa manualmente.")
        sys.exit(1)
