"""
Truco para testear el cron IPM enriquecido sin esperar a las 6 AM:
1. Cambia el Schedule Trigger del workflow Control_IPM de '0 6 * * *' a '*/1 * * * *' (cada minuto).
2. Espera ~75 segundos para que se ejecute al menos una vez.
3. Restaura el Schedule a '0 6 * * *'.

La plantilla IPM-L ya está en 'sabado' (día actual) por el preparativo previo.
Tras esto el script consulta el endpoint para verificar la tarea creada.
"""
import json, os, sys, time, urllib.request

API_KEY = os.environ["N8N_KEY"]
BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
WF_ID = "CPUlOabXvRrGIVjy"

def get_wf():
    req = urllib.request.Request(f"{BASE}/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def put_wf(wf, body=None):
    if body is None:
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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# 1. Acelerar el Schedule Trigger
wf = get_wf()
schedule_node = next((n for n in wf["nodes"] if n["name"] == "Cron Diario 6AM1"), None)
if not schedule_node:
    print("ERROR: nodo Schedule no encontrado")
    sys.exit(1)

original_rule = json.loads(json.dumps(schedule_node["parameters"]["rule"]))
print("Schedule original:", json.dumps(original_rule)[:120])

schedule_node["parameters"]["rule"] = {
    "interval": [{"field": "cronExpression", "expression": "*/1 * * * *"}]
}
result = put_wf(wf)
print(f"Schedule acelerado a cada minuto. nodes={len(result.get('nodes', []))}")

# 2. Esperar
print("Esperando 80s para que se dispare al menos una vez...")
time.sleep(80)

# 3. Restaurar
wf = get_wf()
schedule_node = next(n for n in wf["nodes"] if n["name"] == "Cron Diario 6AM1")
schedule_node["parameters"]["rule"] = original_rule
put_wf(wf)
print("Schedule restaurado a 0 6 * * *")
