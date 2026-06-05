"""
F2.5 — Posponer con motivo + contador.

Cambios en `Control_IPM` (CPUlOabXvRrGIVjy):
  1. Code `Buscar y Preparar1` reescrito: extrae `motivo` del body (opcional)
     y lee `veces_pospuesta` actual de la fila para incrementar +1.
  2. Nodo `Actualizar Fecha1` (Sheets update) ampliado a 4 mappings:
     `id` (match), `fecha`, `motivo_posponer`, `veces_pospuesta`. Schema
     extendido para que n8n conozca las nuevas columnas.

Idempotente. Sigue el patrón de [N8N-001] (whitelist) y [N8N-014]
(settings whitelist).
"""
import json
import os
import sys
import urllib.error
import urllib.request

WORKFLOW_ID = "CPUlOabXvRrGIVjy"
N8N_BASE = "https://primary-production-2cf7.up.railway.app/api/v1"

NEW_CODE = r"""const body = $('Webhook Posponer').first().json.body || {};
const idBuscado = body.id;
const nuevaFecha = body.nueva_fecha;
const motivo = String(body.motivo || '').trim();

const filas = $input.all().map(item => item.json);
const tarea = filas.find(f => String(f.id || '').trim() === String(idBuscado || '').trim());

if (!tarea) {
  return [{ json: { encontrada: false, error: 'tarea_no_encontrada' } }];
}

const vecesActual = parseInt(String(tarea.veces_pospuesta || '0').trim(), 10);
const vecesNuevo = (isNaN(vecesActual) ? 0 : vecesActual) + 1;

return [{ json: {
  encontrada: true,
  id: tarea.id,
  nueva_fecha: nuevaFecha,
  motivo_posponer: motivo,
  veces_pospuesta: vecesNuevo
}}];
"""

NEW_COLUMNS_VALUE = {
    "id": "={{ $json.id }}",
    "fecha": "={{ $json.nueva_fecha }}",
    "motivo_posponer": "={{ $json.motivo_posponer }}",
    "veces_pospuesta": "={{ $json.veces_pospuesta }}",
}

NEW_SCHEMA = [
    {"id": "id", "displayName": "id", "required": False, "defaultMatch": True, "display": True, "type": "string", "canBeUsedToMatch": True, "removed": False},
    {"id": "fecha", "displayName": "fecha", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
    {"id": "motivo_posponer", "displayName": "motivo_posponer", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
    {"id": "veces_pospuesta", "displayName": "veces_pospuesta", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True},
]


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

    code = next((n for n in wf["nodes"] if n["name"] == "Buscar y Preparar1"), None)
    if not code:
        sys.exit("Nodo 'Buscar y Preparar1' no encontrado")
    code["parameters"]["jsCode"] = NEW_CODE
    print("✓ Code 'Buscar y Preparar1' reescrito")

    upd = next((n for n in wf["nodes"] if n["name"] == "Actualizar Fecha1"), None)
    if not upd:
        sys.exit("Nodo 'Actualizar Fecha1' no encontrado")
    cols = upd["parameters"].setdefault("columns", {})
    cols["mappingMode"] = "defineBelow"
    cols["value"] = NEW_COLUMNS_VALUE
    cols["matchingColumns"] = ["id"]
    cols["schema"] = NEW_SCHEMA
    cols["attemptToConvertTypes"] = False
    cols["convertFieldsToString"] = False
    print("✓ Mappings 'Actualizar Fecha1' ampliados (4 cols)")

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
