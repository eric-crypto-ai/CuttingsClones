"""
Paso Nivel-1.3: extender el Code 'Filtrar y Generar1' del workflow Control_IPM
para que, cuando una plantilla tenga campo `pool` no vacío, llame a
/ipm-sugerir y enriquezca el campo `observaciones` de la tarea generada con
la sugerencia (producto + dosis + familia + motivo).

No toca otras plantillas (las de pool vacío siguen comportamiento actual).
"""
import json, os, sys, urllib.request

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "CPUlOabXvRrGIVjy"

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))
print(f"Workflow vivo: {wf['name']}, {len(wf['nodes'])} nodos")

NEW_CODE = r"""// Usar DateTime (Luxon) para timezone correcto (Europa/Madrid)
const ahora = DateTime.now().setZone('Europe/Madrid');
const diasSemana = ['domingo', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado'];
const fechaHoy = ahora.toFormat('yyyy-MM-dd');

// Luxon weekday: 1=lunes, 2=martes, ..., 7=domingo
const diaLuxon = ahora.weekday === 7 ? 'domingo' : diasSemana[ahora.weekday];

const plantillas = $('Leer Plantillas1').all().map(item => item.json);
const tareasExistentes = $('Leer Tareas Existentes1').all().map(item => item.json);

// Filtrar plantillas activas que aplican hoy
const plantillasHoy = plantillas.filter(p => {
  const activa = String(p.activa || '').trim().toLowerCase();
  if (activa !== 'si') return false;
  const diasConfig = String(p.dia_recurrencia || '').trim().toLowerCase();
  const diasArray = diasConfig.split(',').map(d => d.trim());
  return diasArray.includes(diaLuxon);
});

if (plantillasHoy.length === 0) {
  return [{ json: { _skip: true, mensaje: `Sin plantillas para ${diaLuxon} (${fechaHoy})` } }];
}

// Anti-duplicados: misma tarea + zona + fecha hoy y no hecha
const nuevas = plantillasHoy.filter(p => {
  const yaExiste = tareasExistentes.some(t =>
    String(t.tarea || '').trim().toLowerCase() === String(p.tarea || '').trim().toLowerCase()
    && String(t.zona || '').trim().toLowerCase() === String(p.zona || '').trim().toLowerCase()
    && String(t.fecha || '').trim() === fechaHoy
    && String(t.estado || '').trim().toLowerCase() !== 'hecha'
  );
  return !yaExiste;
});

if (nuevas.length === 0) {
  return [{ json: { _skip: true, mensaje: `Todas las tareas de ${diaLuxon} ya existen para ${fechaHoy}` } }];
}

// IDs incrementales
let maxId = 0;
for (const t of tareasExistentes) {
  const id = parseInt(t.id);
  if (!isNaN(id) && id > maxId) maxId = id;
}

// Construir tareas a generar
const tareasGen = nuevas.map((p, i) => ({
  id: String(maxId + 1 + i),
  zona: p.zona || '',
  tarea: p.tarea || '',
  prioridad: p.prioridad || 'media',
  estado: 'pendiente',
  fecha: fechaHoy,
  recurrente: 'si',
  dia_recurrencia: p.dia_recurrencia || '',
  observaciones: p.observaciones || '',
  _pool: String(p.pool || '').trim(),
}));

// Enriquecer con /ipm-sugerir si pool no vacío.
// IMPORTANTE: en n8n Code node `fetch` no está disponible. Se usa el helper
// nativo `this.helpers.httpRequest` que devuelve una Promise con el body.
const BASE_WEBHOOK = 'https://primary-production-2cf7.up.railway.app/webhook';
for (const t of tareasGen) {
  if (!t._pool) continue;
  try {
    const data = await this.helpers.httpRequest({
      method: 'GET',
      url: `${BASE_WEBHOOK}/ipm-sugerir`,
      qs: { pool: t._pool, zona: t.zona || '' },
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
      t.observaciones = t.observaciones ? `${t.observaciones} | ${sufijo}` : sufijo;
    }
  } catch (e) {
    t.observaciones = (t.observaciones || '') + ` [IPM fetch err: ${String(e).slice(0, 100)}]`;
  }
}

// Eliminar campo interno _pool antes de devolver
return tareasGen.map(t => ({
  json: {
    id: t.id,
    zona: t.zona,
    tarea: t.tarea,
    prioridad: t.prioridad,
    estado: t.estado,
    fecha: t.fecha,
    recurrente: t.recurrente,
    dia_recurrencia: t.dia_recurrencia,
    observaciones: t.observaciones,
  }
}));
"""

# Reemplazar el código del nodo Filtrar y Generar1
found = False
for n in wf['nodes']:
    if n['name'] == 'Filtrar y Generar1':
        n['parameters']['jsCode'] = NEW_CODE
        found = True
        break

if not found:
    print("ERROR: nodo 'Filtrar y Generar1' no encontrado")
    sys.exit(1)

body = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}

OUT = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/Configuraciones workflows n8n/n8n_control_ipm_post_nivel1_ipm.json"
with open(OUT, "w") as f:
    json.dump(body, f, indent=2, ensure_ascii=False)
print(f"JSON propuesto: {OUT}")

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
