"""
F2 §4.2 — Cron Resumen Diario consolidado a 07:00 (opción A).

Sustituye `Cron Tareas Atrasadas` 09:00 por un cron a las 07:00 con
contenido ampliado: tareas atrasadas + tareas de hoy + compras pendientes
en un único mensaje al grupo Telegram CuttingsClones · Avisos.

Cambios en `Notificaciones_Telegram` (s2ZhtB52NhxPWb1e):
  1. Schedule `Cron Tareas Atrasadas`: triggerAtHour 9 → 7.
  2. Añadir nodo `Read compras Resumen` (Sheets read hoja `compras`,
     executeOnce=true) entre `Read tareas (Tareas Atrasadas)` y
     `Code Tareas Atrasadas`. Necesario para que el Code tenga acceso
     a las 2 fuentes vía $('node').all() — patrón documentado en
     errores_recurrentes §N8N-010 y §N8N-011.
  3. Code: reescribir con 3 secciones (atrasadas + hoy + compras).
  4. IF: actualizar para verificar si hay algo (tareas o compras).

Idempotente: si los nodos ya existen, actualiza parámetros sin duplicar.
"""
import json
import os
import sys
import urllib.error
import urllib.request

WORKFLOW_ID = "s2ZhtB52NhxPWb1e"
N8N_BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEET_COMPRAS_GID = 396906245
CREDENTIAL_ID = "U9MmYhXUgVdOQej5"


NEW_CODE = r"""// Cron Resumen Diario 07:00 — F2.5 (atrasadas + hoy + compras pendientes)
// Timezone-safe: Luxon DateTime.setZone evita que la fecha varíe según el TZ
// del servidor (n8n Railway corre en UTC; Madrid es UTC+1 o UTC+2).
const tareas = $('Read tareas (Tareas Atrasadas)').all().map(i => i.json);
const compras = $('Read compras Resumen').all().map(i => i.json);

const ahora = DateTime.now().setZone('Europe/Madrid');
const hoyStr = ahora.toFormat('yyyy-MM-dd');

const norm = s => String(s || '').trim().toLowerCase();

// 1. Tareas atrasadas (estado=pendiente, fecha < hoy)
const atrasadas = tareas.filter(t => {
  const fecha = String(t.fecha || '').trim();
  return norm(t.estado) === 'pendiente' && fecha && fecha < hoyStr;
});

// 2. Tareas de hoy (estado=pendiente, fecha = hoy)
const hoyTareas = tareas.filter(t => {
  const fecha = String(t.fecha || '').trim();
  return norm(t.estado) === 'pendiente' && fecha === hoyStr;
});

// 3. Compras pendientes (estado=pendiente)
const comprasPendientes = compras.filter(c => norm(c.estado) === 'pendiente');

if (atrasadas.length === 0 && hoyTareas.length === 0 && comprasPendientes.length === 0) {
  return [{ json: { _stop: true } }];
}

function formatTareasPorZona(lista) {
  const porZona = {};
  for (const t of lista) {
    const z = String(t.zona || 'sin zona').toLowerCase();
    if (!porZona[z]) porZona[z] = [];
    porZona[z].push(t);
  }
  let s = '';
  const zonas = Object.keys(porZona).sort();
  for (const z of zonas) {
    s += '• ' + z.toUpperCase() + '\n';
    porZona[z].sort((a, b) => String(a.fecha).localeCompare(String(b.fecha)));
    for (const t of porZona[z]) {
      const prio = norm(t.prioridad);
      const flag = prio === 'alta' ? '🔴 ' : '';
      s += '  ' + flag + (t.fecha || '') + ' · ' + (t.tarea || '') + '\n';
    }
    s += '\n';
  }
  return s;
}

let texto = '☀️ Resumen del día — ' + hoyStr + '\n\n';

if (atrasadas.length > 0) {
  texto += '🚨 Atrasadas (' + atrasadas.length + ')\n\n';
  texto += formatTareasPorZona(atrasadas);
}

if (hoyTareas.length > 0) {
  texto += '📋 Hoy (' + hoyTareas.length + ')\n\n';
  texto += formatTareasPorZona(hoyTareas);
}

if (comprasPendientes.length > 0) {
  texto += '🛒 Compras pendientes (' + comprasPendientes.length + ')\n\n';
  for (const c of comprasPendientes) {
    const item = String(c.item || '').trim();
    if (item) texto += '  · ' + item + '\n';
  }
  texto += '\n';
}

return [{ json: { chat_id: -5023756424, text: texto.trim() } }];
"""


def build_read_compras(position):
    return {
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
                "value": SHEET_COMPRAS_GID,
                "mode": "list",
                "cachedResultName": "compras",
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={SHEET_COMPRAS_GID}",
            },
            "options": {},
        },
        "id": "f2-resumen-read-compras",
        "name": "Read compras Resumen",
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "position": position,
        "credentials": {"googleSheetsOAuth2Api": {"id": CREDENTIAL_ID, "name": "Google Sheets account"}},
        # executeOnce evita el N·M de N8N-011 (Reads en serie).
        "executeOnce": True,
        # alwaysOutputData por N8N-008 (compras puede estar vacía con solo header).
        "alwaysOutputData": True,
    }


def http(method, path, body=None):
    api_key = open(os.path.expanduser("~/.n8n_key")).read().strip()
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{N8N_BASE}{path}",
        data=data,
        method=method,
        headers={"X-N8N-API-KEY": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code} {method} {path}: {e.read().decode()}\n")
        raise


def main():
    print("→ GET workflow Notificaciones_Telegram")
    wf = http("GET", f"/workflows/{WORKFLOW_ID}")
    nodes = wf["nodes"]
    conns = wf.setdefault("connections", {})

    # 1. Cambiar trigger 9 → 7
    cron = next((n for n in nodes if n["name"] == "Cron Tareas Atrasadas"), None)
    if not cron:
        sys.exit("Nodo 'Cron Tareas Atrasadas' no encontrado")
    cron["parameters"]["rule"]["interval"][0]["triggerAtHour"] = 7
    print("✓ Cron Tareas Atrasadas: triggerAtHour 9 → 7")

    # 2. Añadir Read compras Resumen
    read_tareas = next((n for n in nodes if n["name"] == "Read tareas (Tareas Atrasadas)"), None)
    if not read_tareas:
        sys.exit("Nodo 'Read tareas (Tareas Atrasadas)' no encontrado")
    read_compras_pos = [read_tareas["position"][0] + 220, read_tareas["position"][1]]

    existing = next((n for n in nodes if n["name"] == "Read compras Resumen"), None)
    if existing:
        for k, v in build_read_compras(read_compras_pos).items():
            if k != "id":
                existing[k] = v
        print("✓ 'Read compras Resumen' actualizado (idempotente)")
    else:
        nodes.append(build_read_compras(read_compras_pos))
        print("✓ 'Read compras Resumen' añadido")

    # 3. Patch Code
    code = next((n for n in nodes if n["name"] == "Code Tareas Atrasadas"), None)
    if not code:
        sys.exit("Nodo 'Code Tareas Atrasadas' no encontrado")
    code["parameters"]["jsCode"] = NEW_CODE
    print("✓ Code 'Code Tareas Atrasadas' reescrito (resumen consolidado)")

    # 4. Conexiones: Read tareas → Read compras → Code (era Read tareas → Code)
    conns["Read tareas (Tareas Atrasadas)"] = {
        "main": [[{"node": "Read compras Resumen", "type": "main", "index": 0}]]
    }
    conns["Read compras Resumen"] = {
        "main": [[{"node": "Code Tareas Atrasadas", "type": "main", "index": 0}]]
    }
    print("✓ Conexiones: Read tareas → Read compras Resumen → Code Tareas Atrasadas")

    # 5. Reposicionar Code/IF/Telegram a la derecha
    code["position"] = [read_compras_pos[0] + 220, read_compras_pos[1]]
    if_node = next((n for n in nodes if n["name"] == "¿Hay Tareas Atrasadas?"), None)
    if if_node:
        if_node["position"] = [code["position"][0] + 220, code["position"][1]]
    tg = next((n for n in nodes if n["name"] == "Telegram Tareas Atrasadas"), None)
    if tg and if_node:
        tg["position"] = [if_node["position"][0] + 220, if_node["position"][1]]

    # 6. PUT
    live_settings = wf.get("settings", {}) or {}
    safe_settings = {
        "executionOrder": live_settings.get("executionOrder", "v1"),
        "callerPolicy": live_settings.get("callerPolicy", "workflowsFromSameOwner"),
    }
    if live_settings.get("timezone"):
        safe_settings["timezone"] = live_settings["timezone"]
    body = {
        "name": wf["name"],
        "nodes": wf["nodes"],
        "connections": wf["connections"],
        "settings": safe_settings,
        "staticData": wf.get("staticData"),
    }
    print(f"→ PUT ({len(body['nodes'])} nodos)")
    resp = http("PUT", f"/workflows/{WORKFLOW_ID}", body)
    print(f"✓ PUT OK — versionId={resp.get('versionId')}, active={resp.get('active')}")


if __name__ == "__main__":
    main()
