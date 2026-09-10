"""
Conecta Niveles 2 y 3 del IPM al motor F2.5 ya desplegado por Eric.

1. Añade columna `pool` al final de tareas_recurrentes (col L).
2. Reañade enriquecimiento /ipm-sugerir al Code 'Filtrar y Generar1' (Eric lo
   reescribió para F2.5 y perdió esa integración).
3. Reorganiza las plantillas IPM:
   - Consolida id 1 (IPM-L) e id 2 (IPM-J) en UNA sola plantilla con
     `config_recurrencia="lunes,jueves"` (id 1 queda como plantilla unificada,
     id 2 se vacía).
   - Crea id 3: Fumigar madres curativo mensual (Nivel 2).
   - Crea id 4: Pulverizar foliar nutricional madres (Nivel 3).
"""
import json, os, sys, subprocess, urllib.request

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "CPUlOabXvRrGIVjy"
SS = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
APIDIR = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/api script google"

def sh(cmd, args):
    r = subprocess.run(["node", "api_script.js", cmd, json.dumps(args)],
                       capture_output=True, text=True, cwd=APIDIR)
    return json.loads(r.stdout)

# ─── 1. Añadir header `pool` en col L ───
print("[1/4] Añadiendo header `pool` en tareas_recurrentes!L1...")
r = sh("sheets:write", {"spreadsheetId": SS, "range": "tareas_recurrentes!L1", "values": [["pool"]]})
print(f"   {'OK' if r.get('success') else 'FAIL'}")

# ─── 2. Reañadir enriquecimiento IPM al Code ───
print("[2/4] PUT al workflow Control_IPM con Code que enriquece con /ipm-sugerir...")
req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req) as resp:
    wf = json.loads(resp.read())

target_node = next(n for n in wf["nodes"] if n["name"] == "Filtrar y Generar1")
old_code = target_node["parameters"]["jsCode"]

# El Code actual termina con `return plantillasFinal.map((p, i) => ({...}));`
# Necesito interceptar ese return para enriquecer items con pool antes de devolver.

OLD_RETURN = """return plantillasFinal.map((p, i) => ({
  json: {
    id: String(maxId + 1 + i),
    zona: p.zona || '',
    tarea: p.tarea || '',
    prioridad: p.prioridad || 'media',
    estado: 'pendiente',
    fecha: fechaHoy,
    recurrente: 'si',
    dia_recurrencia: p.dia_recurrencia || '',
    observaciones: p.observaciones || '',
    _id_plantilla: p.id_plantilla || ''
  }
}));"""

NEW_RETURN = """// 5. Construir items base
const items = plantillasFinal.map((p, i) => ({
  zona: p.zona || '',
  tarea: p.tarea || '',
  prioridad: p.prioridad || 'media',
  estado: 'pendiente',
  fecha: fechaHoy,
  recurrente: 'si',
  dia_recurrencia: p.dia_recurrencia || '',
  observaciones: p.observaciones || '',
  _id_plantilla: p.id_plantilla || '',
  _pool: norm(p.pool || ''),
  _idx: i,
}));

// 6. Enriquecer observaciones con /ipm-sugerir si la plantilla tenía pool.
// IMPORTANTE: en n8n Code node `fetch` NO existe — usar this.helpers.httpRequest.
const BASE_WEBHOOK = 'https://primary-production-2cf7.up.railway.app/webhook';
for (const it of items) {
  if (!it._pool) continue;
  try {
    const data = await this.helpers.httpRequest({
      method: 'GET',
      url: `${BASE_WEBHOOK}/ipm-sugerir`,
      qs: { pool: it._pool, zona: it.zona },
      json: true,
    });
    let sufijo = '';
    if (data && data.success && data.sugerido) {
      const s = data.sugerido;
      sufijo = `Sugerencia IPM: ${s.producto} (${s.dosis_sugerida}) | familia ${s.familia_irac} | ${s.motivo}`;
    } else if (data && data.motivo) {
      sufijo = `[IPM: ${data.motivo}]`;
    } else if (data && data.error) {
      sufijo = `[IPM error: ${data.error}]`;
    }
    if (sufijo) {
      it.observaciones = it.observaciones ? `${it.observaciones} | ${sufijo}` : sufijo;
    }
  } catch (e) {
    it.observaciones = (it.observaciones || '') + ` [IPM fetch err: ${String(e).slice(0, 100)}]`;
  }
}

// 7. Asignar IDs incrementales y limpiar campos internos antes de emitir
return items.map((it) => ({
  json: {
    id: String(maxId + 1 + it._idx),
    zona: it.zona,
    tarea: it.tarea,
    prioridad: it.prioridad,
    estado: it.estado,
    fecha: it.fecha,
    recurrente: it.recurrente,
    dia_recurrencia: it.dia_recurrencia,
    observaciones: it.observaciones,
    _id_plantilla: it._id_plantilla,
  }
}));"""

if OLD_RETURN not in old_code:
    print("   ⚠️ El bloque return original no coincide. Inspecciona el Code actual antes de continuar.")
    print("   Últimas 30 líneas del Code actual:")
    for line in old_code.splitlines()[-30:]:
        print("     ", line)
    sys.exit(1)

new_code = old_code.replace(OLD_RETURN, NEW_RETURN)
target_node["parameters"]["jsCode"] = new_code

body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

req = urllib.request.Request(
    f"{BASE}/workflows/{WF_ID}",
    data=json.dumps(body).encode("utf-8"),
    method="PUT",
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        print(f"   PUT status: {resp.status}, active: {result.get('active')}, nodes: {len(result.get('nodes', []))}")
except urllib.error.HTTPError as e:
    print(f"   PUT FAILED: {e.code} {e.reason}")
    print(e.read().decode("utf-8"))
    sys.exit(1)

# ─── 3. Reorganizar plantillas IPM en la hoja ───
print("[3/4] Reorganizando plantillas IPM en tareas_recurrentes...")

# Plantilla id=1 → consolidada L+J con pool=regular_madres
sh("sheets:write", {"spreadsheetId": SS, "range": "tareas_recurrentes!A2:L2", "values": [[
    "1",                            # A id_plantilla
    "madres",                       # B zona
    "Fumigar madres preventivo",    # C tarea
    "media",                        # D prioridad
    "si",                           # E activa
    "lunes,jueves",                 # F dia_recurrencia (legacy, ahora multi-día)
    "Regular L+J semanal — pool regular_madres",  # G observaciones
    "semanal",                      # H tipo_recurrencia
    "lunes,jueves",                 # I config_recurrencia
    "",                             # J ultima_disparada
    "ipm_madres",                   # K categoria_exclusiva
    "regular_madres"                # L pool ← NUEVO
]]})
print("   id=1 (IPM-L+J consolidada) ✓")

# Plantilla id=2 → vaciar (consolidada en id=1)
sh("sheets:write", {"spreadsheetId": SS, "range": "tareas_recurrentes!A3:L3", "values": [[
    "", "", "", "", "", "", "", "", "", "", "", ""
]]})
print("   id=2 vaciada (consolidada en id=1) ✓")

# Plantilla id=3 → IPM-mensual-acaros (Nivel 2)
sh("sheets:write", {"spreadsheetId": SS, "range": "tareas_recurrentes!A4:L4", "values": [[
    "3",
    "madres",
    "Fumigar madres curativo mensual",
    "alta",
    "si",
    "",
    "Mensual rotación 3 IRAC (Abamectina/Fenpiroximato/Skunk) — sustituye al regular del día",
    "mensual",
    "1",
    "",
    "ipm_madres",
    "mensual_acaros"
]]})
print("   id=3 (IPM-mensual-acaros, Nivel 2) ✓")

# Plantilla id=4 → Foliar-nutricional (Nivel 3)
sh("sheets:write", {"spreadsheetId": SS, "range": "tareas_recurrentes!A5:L5", "values": [[
    "4",
    "madres",
    "Pulverizar foliar nutricional madres",
    "media",
    "si",
    "",
    "Cada 14d — bienestar y antiestrés (Formulex+Rhyzo o Superthrive)",
    "cada_x_dias",
    "14",
    "",
    "foliar_madres",
    "foliar_nutricional"
]]})
print("   id=4 (Foliar-nutricional, Nivel 3) ✓")

# ─── 4. Verificación ───
print("[4/4] Verificación...")
r = sh("sheets:read", {"spreadsheetId": SS, "range": "tareas_recurrentes!A1:L10"})
rows = r["data"]["values"]
print("   Header:", rows[0])
for i, row in enumerate(rows[1:], start=2):
    if row and any(row):
        print(f"   fila {i}:", row)
print()
print("✅ Niveles 2 y 3 IPM configurados.")
