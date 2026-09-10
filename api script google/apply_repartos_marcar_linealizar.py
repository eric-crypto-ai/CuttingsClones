"""
Linealiza el flujo /repartos-marcar-entregado en el workflow Gestion_Economica.

Bug detectado 2026-05-08:
  La rama A (Sheets update reparto → Respond) y la rama B (read mov_bote →
  compose → append mov_bote) corren en paralelo desde "Find reparto target".
  Respond se envía antes de que termine la rama B, lo que permite al portal
  lanzar la siguiente llamada antes de que se haya escrito el movimiento del
  bote. Resultado: race en movimientos_bote y filas perdidas cuando se marcan
  varios "ingresos al bote" seguidos (ej. con "✓ Ingresar todos").

Fix:
  Linealizar la cadena. Todo el procesamiento del mov_bote ocurre ANTES del
  Respond. Si el reparto no es bote (o ya estaba entregado), un IF redirige
  directamente al Respond.

Nuevo flujo:
  Webhook → read repartos → Find reparto target → Sheets update reparto
    → IF "es_bote && !ya_entregado"
         ├ TRUE  → read mov_bote → Compose → append mov_bote → Respond
         └ FALSE → Respond
"""
import json
import os
import urllib.request
import uuid

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "OGYN277IKvO9OVpH"

req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req, timeout=30) as resp:
    wf = json.loads(resp.read().decode("utf-8"))
print(f"Workflow vivo: {wf['name']} | {len(wf['nodes'])} nodos")


# ── 1. Localizar nodos existentes ──────────────────────────────
def find_node(name):
    for n in wf["nodes"]:
        if n["name"] == name:
            return n
    raise RuntimeError(f"Nodo no encontrado: {name}")


N_FIND = find_node("Find reparto target")
N_UPDATE = find_node("Sheets update reparto")
N_RESPOND = find_node("Respond repartos-marcar")
N_READ_MOV = find_node("Sheets read mov_bote (for marcar)")
N_COMPOSE = find_node("Compose mov bote (if applies)")
N_APPEND = find_node("Sheets append mov_bote (from reparto)")


# ── 2. Crear nodo IF "Es bote pendiente?" ──────────────────────
IF_NAME = "IF es bote pendiente?"
if_node = {
    "parameters": {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
            "conditions": [{
                "id": str(uuid.uuid4()),
                "leftValue": "={{ $('Find reparto target').item.json.es_bote && !$('Find reparto target').item.json.ya_entregado }}",
                "rightValue": "",
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }],
            "combinator": "and",
        },
        "options": {},
    },
    "id": str(uuid.uuid4()),
    "name": IF_NAME,
    "type": "n8n-nodes-base.if",
    "typeVersion": 2,
    "position": [1100, 5020],
}

# Reposicionar nodos para mantener el lienzo legible
N_UPDATE["position"] = [900, 5020]
if_node["position"] = [1100, 5020]
N_READ_MOV["position"] = [1300, 5120]
N_COMPOSE["position"] = [1500, 5120]
N_APPEND["position"] = [1700, 5120]
N_RESPOND["position"] = [1900, 5020]


# ── 3. Simplificar el código de "Compose mov bote" ─────────────
# Ya no necesita los early-returns por es_bote / ya_entregado porque
# el IF ya filtra. Pero los dejamos como guarda extra (defensa en profundidad).
N_COMPOSE["parameters"]["jsCode"] = (
    "const target = $('Find reparto target').item.json;\n"
    "// Doble guarda — el IF previo ya filtra, pero por defensa:\n"
    "if (!target.es_bote) return [];\n"
    "if (target.ya_entregado) return [];\n"
    "const movs = $('Sheets read mov_bote (for marcar)').all().map(i => i.json).filter(m => m.id_mov);\n"
    "let saldo_previo = 0;\n"
    "if (movs.length > 0) saldo_previo = Number(movs[movs.length - 1].saldo_despues || 0);\n"
    "return [{\n"
    "  json: {\n"
    "    id_mov: \"M\" + Date.now(),\n"
    "    fecha: new Date().toISOString().slice(0, 10),\n"
    "    tipo: \"cobro\",\n"
    "    importe: target.importe,\n"
    "    concepto: \"Ingreso al bote desde reparto \" + target.id_reparto,\n"
    "    id_referencia: target.id_reparto,\n"
    "    socio: \"\",\n"
    "    saldo_despues: saldo_previo + target.importe\n"
    "  }\n"
    "}];\n"
)


# ── 4. Insertar el IF en la lista de nodos ─────────────────────
existing_names = {n["name"] for n in wf["nodes"]}
if IF_NAME in existing_names:
    # Ya existía (re-ejecución idempotente): localizarlo y dejar el id ya presente
    for i, n in enumerate(wf["nodes"]):
        if n["name"] == IF_NAME:
            wf["nodes"][i] = if_node
            break
else:
    wf["nodes"].append(if_node)


# ── 5. Reescribir las conexiones de la rama afectada ───────────
conns = wf.setdefault("connections", {})

# Find reparto target → ahora solo va a "Sheets update reparto"
conns["Find reparto target"] = {
    "main": [[{"node": "Sheets update reparto", "type": "main", "index": 0}]]
}

# Sheets update reparto → IF es bote pendiente?
conns["Sheets update reparto"] = {
    "main": [[{"node": IF_NAME, "type": "main", "index": 0}]]
}

# IF: TRUE → Sheets read mov_bote, FALSE → Respond
conns[IF_NAME] = {
    "main": [
        [{"node": "Sheets read mov_bote (for marcar)", "type": "main", "index": 0}],  # TRUE
        [{"node": "Respond repartos-marcar", "type": "main", "index": 0}],            # FALSE
    ]
}

# read mov_bote → Compose
conns["Sheets read mov_bote (for marcar)"] = {
    "main": [[{"node": "Compose mov bote (if applies)", "type": "main", "index": 0}]]
}

# Compose → append
conns["Compose mov bote (if applies)"] = {
    "main": [[{"node": "Sheets append mov_bote (from reparto)", "type": "main", "index": 0}]]
}

# append → Respond  (NUEVO: ahora también desemboca en Respond)
conns["Sheets append mov_bote (from reparto)"] = {
    "main": [[{"node": "Respond repartos-marcar", "type": "main", "index": 0}]]
}


# ── 6. PUT al workflow ─────────────────────────────────────────
# n8n API: solo acepta name, nodes, connections, settings, staticData en PUT
allowed = {"name", "nodes", "connections", "settings", "staticData"}
payload = {k: v for k, v in wf.items() if k in allowed}

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    f"{BASE}/workflows/{WF_ID}",
    data=data,
    method="PUT",
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    print(f"OK: {out.get('name')} actualizado | {len(out.get('nodes', []))} nodos")
except urllib.error.HTTPError as e:
    print("ERROR PUT:", e.code, e.reason)
    print(e.read().decode("utf-8")[:1000])
    raise
