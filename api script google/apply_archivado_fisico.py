"""
F2.5 — Archivado físico de tareas hechas.

Refactor del flujo `/tareas-eliminar` en Control_IPM (CPUlOabXvRrGIVjy).
Cambia la semántica de "update estado=hecha (queda en tareas)" a "mover
físicamente a historial_tareas". El path se mantiene por compat con el
frontend ya en producción.

Cadena nueva:
  webhook tareas eliminar
    → Get row(s) in sheet4 (Sheets read tareas, sin cambios)
    → Code in JavaScript4 (refactor: emite fila completa + fecha_completada=hoy + _row_number)
    → Archivar en historial (Sheets append en historial_tareas, autoMapInputData)
    → Borrar de tareas (Sheets delete, toDelete=rows, startIndex=row_number)
    → Edit Fields1 ({ok:true}, sin cambios)
    → Respond to Webhook5

Idempotente respecto a la estructura: si el script se vuelve a ejecutar,
detecta nodos ya creados y solo actualiza parámetros.
"""
import json
import os
import sys
import urllib.error
import urllib.request

WORKFLOW_ID = "CPUlOabXvRrGIVjy"
N8N_BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEET_TAREAS_GID = 1404161276
SHEET_HISTORIAL_GID = 1697172259
CREDENTIAL_ID = "U9MmYhXUgVdOQej5"

NEW_CODE = r"""const idBuscado = String($('webhook tareas eliminar').first().json.body.id || '').trim();
if (!idBuscado) throw new Error('falta_id');

// $input.all() devuelve TODOS los items en orden de fila (sin huecos:
// Sheets read salta filas vacías). Para el delete necesitamos el row_number
// FÍSICO de Sheets — no podemos confiar en la columna `row_number` (es
// artefacto vacío en las filas reales). Lo calculamos: índice 0-based
// + 2 (1=header, 1-based).
const items = $input.all();
const idx = items.findIndex(it => String((it.json || {}).id || '').trim() === idBuscado);
if (idx === -1) throw new Error(`tarea_no_encontrada: ${idBuscado}`);

const duplicados = items.filter(it => String((it.json || {}).id || '').trim() === idBuscado).length;
if (duplicados > 1) throw new Error(`id_duplicado: ${idBuscado} aparece ${duplicados} veces`);

const t = items[idx].json;
const rowNumberFisico = idx + 2;
const hoy = DateTime.now().setZone('Europe/Madrid').toFormat('yyyy-MM-dd');

return [{
  json: {
    id: t.id || '',
    zona: t.zona || '',
    tarea: t.tarea || '',
    prioridad: t.prioridad || '',
    estado: 'hecha',
    fecha: t.fecha || '',
    recurrente: t.recurrente || '',
    dia_recurrencia: t.dia_recurrencia || '',
    observaciones: t.observaciones || '',
    id_evento_origen: t.id_evento_origen || '',
    tipo_origen: t.tipo_origen || '',
    motivo_posponer: t.motivo_posponer || '',
    veces_pospuesta: t.veces_pospuesta || '',
    fecha_completada: hoy,
    _row_number: rowNumberFisico,
  }
}];
"""


def build_archivar_node(position):
    return {
        "parameters": {
            "operation": "append",
            "documentId": {
                "__rl": True,
                "value": SPREADSHEET_ID,
                "mode": "list",
                "cachedResultName": "Control_IPM",
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=drivesdk",
            },
            "sheetName": {
                "__rl": True,
                "value": SHEET_HISTORIAL_GID,
                "mode": "list",
                "cachedResultName": "historial_tareas",
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={SHEET_HISTORIAL_GID}",
            },
            "columns": {
                "mappingMode": "autoMapInputData",
                "matchingColumns": [],
            },
            "options": {},
        },
        "id": "f2-5-archivado-historial-append",
        "name": "Archivar en historial",
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "position": position,
        "credentials": {"googleSheetsOAuth2Api": {"id": CREDENTIAL_ID, "name": "Google Sheets account"}},
    }


def build_borrar_node(position):
    return {
        "parameters": {
            "operation": "delete",
            "documentId": {
                "__rl": True,
                "value": SPREADSHEET_ID,
                "mode": "list",
                "cachedResultName": "Control_IPM",
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=drivesdk",
            },
            "sheetName": {
                "__rl": True,
                "value": SHEET_TAREAS_GID,
                "mode": "list",
                "cachedResultName": "tareas",
                "cachedResultUrl": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={SHEET_TAREAS_GID}",
            },
            "toDelete": "rows",
            "startIndex": "={{ $('Code in JavaScript4').first().json._row_number }}",
            "numberToDelete": 1,
        },
        "id": "f2-5-archivado-tareas-delete",
        "name": "Borrar de tareas",
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "position": position,
        "credentials": {"googleSheetsOAuth2Api": {"id": CREDENTIAL_ID, "name": "Google Sheets account"}},
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
    print("→ GET workflow Control_IPM")
    wf = http("GET", f"/workflows/{WORKFLOW_ID}")
    nodes = wf["nodes"]
    conns = wf.setdefault("connections", {})

    # 1. Patch Code
    code = next((n for n in nodes if n["name"] == "Code in JavaScript4"), None)
    if not code:
        sys.exit("Nodo 'Code in JavaScript4' no encontrado")
    code["parameters"]["jsCode"] = NEW_CODE
    print("✓ Code 'Code in JavaScript4' reescrito (emite fila completa)")

    # 2. Reemplazar Update row in sheet por Archivar en historial
    update_existing = next((n for n in nodes if n["name"] == "Update row in sheet"), None)
    if update_existing:
        archivar_pos = update_existing["position"]
        # Eliminar Update
        nodes.remove(update_existing)
        if "Update row in sheet" in conns:
            del conns["Update row in sheet"]
        print("✓ Nodo 'Update row in sheet' eliminado")
    else:
        archivar_pos = [-272, 2256]

    archivar_existing = next((n for n in nodes if n["name"] == "Archivar en historial"), None)
    if archivar_existing:
        for k, v in build_archivar_node(archivar_pos).items():
            if k != "id":
                archivar_existing[k] = v
        print("✓ 'Archivar en historial' actualizado (idempotente)")
    else:
        nodes.append(build_archivar_node(archivar_pos))
        print("✓ 'Archivar en historial' añadido")

    # 3. Crear/actualizar Borrar de tareas
    borrar_pos = [archivar_pos[0] + 224, archivar_pos[1]]
    borrar_existing = next((n for n in nodes if n["name"] == "Borrar de tareas"), None)
    if borrar_existing:
        for k, v in build_borrar_node(borrar_pos).items():
            if k != "id":
                borrar_existing[k] = v
        print("✓ 'Borrar de tareas' actualizado (idempotente)")
    else:
        nodes.append(build_borrar_node(borrar_pos))
        print("✓ 'Borrar de tareas' añadido")

    # 4. Mover Edit Fields1 y Respond a la derecha si chocan posiciones
    edit_node = next((n for n in nodes if n["name"] == "Edit Fields1"), None)
    if edit_node:
        edit_node["position"] = [borrar_pos[0] + 224, borrar_pos[1]]
    respond_node = next((n for n in nodes if n["name"] == "Respond to Webhook5"), None)
    if respond_node and edit_node:
        respond_node["position"] = [edit_node["position"][0] + 224, edit_node["position"][1]]

    # 5. Reescribir conexiones de la cadena
    conns["Code in JavaScript4"] = {"main": [[{"node": "Archivar en historial", "type": "main", "index": 0}]]}
    conns["Archivar en historial"] = {"main": [[{"node": "Borrar de tareas", "type": "main", "index": 0}]]}
    conns["Borrar de tareas"] = {"main": [[{"node": "Edit Fields1", "type": "main", "index": 0}]]}
    # Edit Fields1 → Respond ya existía
    print("✓ Conexiones reescritas: Code → Archivar → Borrar → Edit Fields1 → Respond")

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
