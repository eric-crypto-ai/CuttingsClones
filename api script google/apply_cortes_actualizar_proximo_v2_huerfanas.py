"""
Patch al workflow Cortes (WF_ID=H3rtLs6wi4Yty91S) — v2 endpoint
/cortes-actualizar-proximo.

Mejora estructural 3a: cuando no hay tarea con id_evento_origen=id_evento
exacto, buscar tareas huérfanas con misma genética (prefijo del id_evento
hasta el primer guion), zona=madres, tipo_origen=corte, estado=pendiente.
Devolverlas en la respuesta para que la UI pueda avisar.

Patch sobre nodos existentes:
  - "Validar Actualizar Proximo": añade búsqueda de tareas_huerfanas.
  - "Format Respuesta OK Sin Tarea": enriquece motivo_sin_tarea + lista.

Idempotente: si el código ya contiene "tareas_huerfanas", aborta.

Requiere: N8N_KEY (env o ~/.n8n_key).
"""
import json
import os
import sys
import urllib.request
import urllib.error

BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "H3rtLs6wi4Yty91S"


def _load_key():
    v = os.environ.get("N8N_KEY")
    if v:
        return v
    p = os.path.expanduser("~/.n8n_key")
    if os.path.isfile(p):
        with open(p) as f:
            return f.read().strip()
    raise SystemExit("N8N_KEY no encontrado")


API_KEY = _load_key()
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


JSCODE_VALIDAR_V2 = r"""const body = $('Webhook Actualizar Proximo').first().json.body || $('Webhook Actualizar Proximo').first().json;
const id_evento = String(body.id_evento || '').trim();
const nueva_fecha = String(body.nueva_fecha_proximo_corte_estimada || '').trim();

if (!id_evento) {
  return [{ json: { ok: false, error: 'falta id_evento' } }];
}
if (!nueva_fecha || !/^\d{4}-\d{2}-\d{2}$/.test(nueva_fecha)) {
  return [{ json: { ok: false, error: 'formato fecha invalido (YYYY-MM-DD)' } }];
}
const fechaTest = new Date(nueva_fecha + 'T00:00:00Z');
if (isNaN(fechaTest.getTime())) {
  return [{ json: { ok: false, error: 'fecha invalida' } }];
}

const eventos = $('Read eventos_corte (actualizar)').all().map(i => i.json);
const evento = eventos.find(e => String(e.id_evento || '').trim() === id_evento);
if (!evento) {
  return [{ json: { ok: false, error: 'lote no encontrado: ' + id_evento } }];
}
const estado = (String(evento.estado || '').trim().toLowerCase()) || 'activo';
if (estado !== 'activo') {
  return [{ json: { ok: false, error: 'lote no activo (estado=' + estado + '). No se permite editar fechas de lotes cerrados.' } }];
}

const tareas = $('Read tareas (actualizar)').all().map(i => i.json);
const tarea = tareas.find(t =>
  String(t.id_evento_origen || '').trim() === id_evento &&
  String(t.tipo_origen || '').trim().toLowerCase() === 'corte' &&
  String(t.zona || '').trim().toLowerCase() === 'madres' &&
  String(t.estado || '').trim().toLowerCase() === 'pendiente'
);

// Tareas huérfanas candidatas: misma genética (prefijo del id), zona=madres,
// tipo_origen=corte, estado=pendiente, pero id_evento_origen != id_evento.
// Útil cuando un lote cambia de id (p. ej. corregir fecha_corte) y deja
// tareas apuntando al id viejo.
let tareas_huerfanas = [];
if (!tarea) {
  const genetica = id_evento.split('-')[0];
  tareas_huerfanas = tareas
    .filter(t =>
      String(t.id_evento_origen || '').trim().toUpperCase().startsWith(genetica + '-') &&
      String(t.tipo_origen || '').trim().toLowerCase() === 'corte' &&
      String(t.zona || '').trim().toLowerCase() === 'madres' &&
      String(t.estado || '').trim().toLowerCase() === 'pendiente' &&
      String(t.id_evento_origen || '').trim() !== id_evento
    )
    .map(t => ({
      id: String(t.id || '').trim(),
      id_evento_origen: String(t.id_evento_origen || '').trim(),
      fecha: String(t.fecha || '').trim()
    }));
}

return [{ json: {
  ok: true,
  id_evento: id_evento,
  fecha_proximo_corte_estimada: nueva_fecha,
  tarea_existe: !!tarea,
  id_tarea: tarea ? String(tarea.id || '').trim() : '',
  tareas_huerfanas: tareas_huerfanas
} }];
"""

JSCODE_FORMAT_OK_SIN_TAREA_V2 = r"""const v = $('Validar Actualizar Proximo').first().json;
const huerfanas = v.tareas_huerfanas || [];
const motivo = huerfanas.length > 0
  ? 'tarea #4 no encontrada para ' + v.id_evento + '; hay ' + huerfanas.length + ' tarea(s) huérfana(s) de la misma genética: ' + huerfanas.map(h => h.id_evento_origen + '/' + h.id).join(', ')
  : 'tarea #4 no existe o no esta pendiente';
return [{ json: {
  ok: true,
  id_evento: v.id_evento,
  nueva_fecha: v.fecha_proximo_corte_estimada,
  tarea_actualizada: false,
  motivo_sin_tarea: motivo,
  tareas_huerfanas_candidatas: huerfanas
} }];
"""


# ─── 1. Leer workflow vivo ────────────────────────────────────────
status, wf = n8n_request("GET", f"/workflows/{WF_ID}")
if status != 200:
    raise SystemExit(f"GET workflow falló: HTTP {status} — {wf}")

print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")

# Idempotencia
nodes = wf["nodes"]
validar = next((n for n in nodes if n["name"] == "Validar Actualizar Proximo"), None)
fmt_sin = next((n for n in nodes if n["name"] == "Format Respuesta OK Sin Tarea"), None)

if not validar or not fmt_sin:
    raise SystemExit("ABORT: nodos esperados no presentes — aplica primero apply_cortes_actualizar_proximo.py")

if "tareas_huerfanas" in validar["parameters"].get("jsCode", ""):
    print("ABORT: ya tiene la mejora v2 aplicada (palabra 'tareas_huerfanas' presente).")
    sys.exit(0)


# ─── 2. Patch ─────────────────────────────────────────────────────
validar["parameters"]["jsCode"] = JSCODE_VALIDAR_V2
fmt_sin["parameters"]["jsCode"] = JSCODE_FORMAT_OK_SIN_TAREA_V2


# ─── 3. PUT ───────────────────────────────────────────────────────
body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": wf.get("settings", {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"}),
}

print(f"\nAplicando PUT con {len(wf['nodes'])} nodos (2 jsCode parcheados)...")
status, result = n8n_request("PUT", f"/workflows/{WF_ID}", body)
if status == 200:
    print(f"✓ PUT OK: HTTP {status}, active={result.get('active')}, nodes={len(result.get('nodes', []))}")
else:
    print(f"✗ PUT FALLÓ: HTTP {status} — {result}")
    sys.exit(1)

# Snapshot
SNAPSHOT = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_cortes_post_actualizar_proximo.json"
with open(SNAPSHOT, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"✓ Snapshot escrito: {SNAPSHOT}")
