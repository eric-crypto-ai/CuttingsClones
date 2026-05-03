"""
Test E2E del refactor F2.5 — exclusividad agronómica.

Escenario:
  - Inserta 2 plantillas TEST con misma `categoria_exclusiva=ipm_madres`,
    misma zona=madres, misma tarea, distinta prioridad.
    · TEST-mensual (id=98)  prio=alta   tipo=mensual    config=<día_de_hoy>
    · TEST-semanal (id=99)  prio=media  tipo=semanal    config=<día_semana_hoy>
  - Acelera el Schedule del cron a `*/2 * * * *` durante ~3 min.
  - Verifica que en `tareas` aparece UNA SOLA fila para hoy con tarea
    "TEST-Fumigar madres preventivo" (la generada por la mensual, prio alta).
  - Verifica que `ultima_disparada` de la plantilla mensual = hoy y la
    semanal sigue vacía (no disparó por exclusividad).

Restore garantizado vía try/finally:
  - Schedule cron vuelve a `0 6 * * *`.
  - Plantillas TEST eliminadas de `tareas_recurrentes`.
  - Tarea TEST eliminada de `tareas`.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

WORKFLOW_ID = "CPUlOabXvRrGIVjy"
N8N_BASE = "https://primary-production-2cf7.up.railway.app/api/v1"
SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
API_SCRIPT = "/Users/ericcastillo/Library/Mobile Documents/com~apple~CloudDocs/Proyecto_CuttingsClones/api script google/api_script.js"

CRON_NORMAL = "0 6 * * *"
CRON_FAST = "*/2 * * * *"
WAIT_SECONDS = 180  # 3 minutos para garantizar al menos 1 disparo del cron */2

TEST_TAREA = "TEST-Fumigar madres preventivo"  # nombre único para no chocar con prod
TEST_ID_MENSUAL = "98"
TEST_ID_SEMANAL = "99"


def n8n(method, path, body=None):
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
        body_err = e.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"HTTP {e.code} {method} {path}: {body_err}\n")
        raise


def sheets(cmd, args):
    """Llama a api_script.js."""
    p = subprocess.run(
        ["node", API_SCRIPT, cmd, json.dumps(args)],
        capture_output=True, text=True, check=False
    )
    if p.returncode != 0:
        sys.stderr.write(f"sheets error: {p.stderr}\n")
        raise RuntimeError(p.stderr)
    return json.loads(p.stdout)


def set_cron_schedule(expression):
    """Modifica el cronExpression del nodo Cron Diario 6AM1 y hace PUT."""
    wf = n8n("GET", f"/workflows/{WORKFLOW_ID}")
    cron_node = next(n for n in wf["nodes"] if n["name"] == "Cron Diario 6AM1")
    cron_node["parameters"]["rule"]["interval"][0]["expression"] = expression

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
    resp = n8n("PUT", f"/workflows/{WORKFLOW_ID}", body)
    print(f"  cron schedule → '{expression}' (versionId={resp.get('versionId')})")


def insertar_plantillas_test():
    today = datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")  # CEST aprox
    # Día del mes de hoy y nombre del día
    dt = datetime.now()
    dia_mes = str(dt.day)
    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    dia_semana = dias[dt.weekday()]
    print(f"  hoy = {today}, día del mes = {dia_mes}, día semana = {dia_semana}")
    # Append en filas K4-K5 (después de las 2 plantillas reales)
    sheets("sheets:append", {
        "spreadsheetId": SPREADSHEET_ID,
        "range": "tareas_recurrentes!A:K",
        "values": [
            [TEST_ID_MENSUAL, "madres", TEST_TAREA, "alta", "si", "", "TEST E2E F2.5 — mensual prio alta", "mensual", dia_mes, "", "ipm_madres"],
            [TEST_ID_SEMANAL, "madres", TEST_TAREA, "media", "si", "", "TEST E2E F2.5 — semanal prio media", "semanal", dia_semana, "", "ipm_madres"],
        ],
    })
    print(f"  ✓ Insertadas 2 plantillas TEST (id={TEST_ID_MENSUAL} mensual día {dia_mes} alta, id={TEST_ID_SEMANAL} semanal {dia_semana} media)")


def leer_tareas_recurrentes():
    r = sheets("sheets:read", {
        "spreadsheetId": SPREADSHEET_ID,
        "range": "tareas_recurrentes!A1:K20",
    })
    rows = r["data"]["values"]
    headers = rows[0]
    return [dict(zip(headers, r + [""] * (len(headers) - len(r)))) for r in rows[1:]]


def leer_tareas():
    r = sheets("sheets:read", {
        "spreadsheetId": SPREADSHEET_ID,
        "range": "tareas!A1:Z200",
    })
    rows = r["data"]["values"]
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, r + [""] * (len(headers) - len(r)))) for r in rows[1:]]


def cleanup_plantillas_test():
    """Borra las plantillas TEST por id de la hoja."""
    rows_full = sheets("sheets:read", {
        "spreadsheetId": SPREADSHEET_ID,
        "range": "tareas_recurrentes!A1:K50",
    })["data"]["values"]
    headers = rows_full[0]
    # Recoger filas a conservar (excluir las TEST)
    keep = []
    for row in rows_full[1:]:
        d = dict(zip(headers, row + [""] * (len(headers) - len(row))))
        if str(d.get("id_plantilla", "")).strip() in (TEST_ID_MENSUAL, TEST_ID_SEMANAL):
            continue
        # Padding a 11 columnas
        padded = list(row) + [""] * (11 - len(row))
        keep.append(padded[:11])
    # Limpiar y reescribir
    sheets("sheets:clear", {
        "spreadsheetId": SPREADSHEET_ID,
        "range": "tareas_recurrentes!A2:Z50",
    })
    if keep:
        sheets("sheets:write", {
            "spreadsheetId": SPREADSHEET_ID,
            "range": f"tareas_recurrentes!A2:K{1+len(keep)}",
            "values": keep,
        })
    print(f"  ✓ Plantillas TEST eliminadas, {len(keep)} plantillas reales conservadas")


def cleanup_tareas_test():
    """Borra de la hoja `tareas` cualquier fila con tarea = TEST-..."""
    rows_full = sheets("sheets:read", {
        "spreadsheetId": SPREADSHEET_ID,
        "range": "tareas!A1:Z2000",
    })["data"]["values"]
    if not rows_full:
        return
    headers = rows_full[0]
    keep = []
    eliminadas = 0
    for row in rows_full[1:]:
        d = dict(zip(headers, row + [""] * (len(headers) - len(row))))
        if str(d.get("tarea", "")).strip() == TEST_TAREA:
            eliminadas += 1
            continue
        padded = list(row) + [""] * (len(headers) - len(row))
        keep.append(padded[:len(headers)])
    if eliminadas == 0:
        return
    # Reescribir
    last_col = chr(ord("A") + len(headers) - 1)
    sheets("sheets:clear", {
        "spreadsheetId": SPREADSHEET_ID,
        "range": f"tareas!A2:{last_col}2000",
    })
    if keep:
        sheets("sheets:write", {
            "spreadsheetId": SPREADSHEET_ID,
            "range": f"tareas!A2:{last_col}{1+len(keep)}",
            "values": keep,
        })
    print(f"  ✓ {eliminadas} tareas TEST eliminadas de hoja `tareas`")


def main():
    print("=" * 70)
    print("F2.5 — Test E2E exclusividad agronómica")
    print("=" * 70)

    try:
        print("\n[1/5] Insertar plantillas TEST")
        insertar_plantillas_test()

        print("\n[2/5] Acelerar cron a */2 * * * *")
        set_cron_schedule(CRON_FAST)

        print(f"\n[3/5] Esperar {WAIT_SECONDS}s para que el cron dispare al menos 1 vez…")
        for i in range(WAIT_SECONDS, 0, -30):
            print(f"  …{i}s restantes")
            time.sleep(min(30, i))

        print("\n[4/5] Verificar resultado")
        plantillas = leer_tareas_recurrentes()
        tareas_hoy = [t for t in leer_tareas() if t.get("tarea") == TEST_TAREA]

        # Buscar las TEST en plantillas
        p_mensual = next((p for p in plantillas if p.get("id_plantilla") == TEST_ID_MENSUAL), None)
        p_semanal = next((p for p in plantillas if p.get("id_plantilla") == TEST_ID_SEMANAL), None)

        print(f"  · plantilla mensual id={TEST_ID_MENSUAL}: ultima_disparada='{(p_mensual or {}).get('ultima_disparada','?')}'")
        print(f"  · plantilla semanal id={TEST_ID_SEMANAL}: ultima_disparada='{(p_semanal or {}).get('ultima_disparada','?')}'")
        print(f"  · tareas '{TEST_TAREA}' creadas hoy: {len(tareas_hoy)}")
        for t in tareas_hoy:
            print(f"      id={t.get('id')} fecha={t.get('fecha')} prioridad={t.get('prioridad')} estado={t.get('estado')}")

        # Veredicto
        ok = True
        if len(tareas_hoy) != 1:
            print(f"  ✗ ESPERADO 1 tarea, ACTUAL {len(tareas_hoy)}")
            ok = False
        elif tareas_hoy[0].get("prioridad") != "alta":
            print(f"  ✗ ESPERADO prio=alta, ACTUAL {tareas_hoy[0].get('prioridad')}")
            ok = False
        if (p_mensual or {}).get("ultima_disparada", "") == "":
            print("  ✗ ESPERADO ultima_disparada de mensual con fecha, ACTUAL vacío")
            ok = False
        if (p_semanal or {}).get("ultima_disparada", "") != "":
            print(f"  ⚠ ultima_disparada de semanal NO debería estar (no debió disparar): '{p_semanal.get('ultima_disparada')}'")
            ok = False
        print()
        print(f"  RESULTADO: {'✓ PASS' if ok else '✗ FAIL'}")

    finally:
        print("\n[5/5] Restore (siempre se ejecuta)")
        try:
            set_cron_schedule(CRON_NORMAL)
        except Exception as e:
            print(f"  ⚠ Error restaurando cron: {e}. Verifica manualmente.")
        try:
            cleanup_plantillas_test()
        except Exception as e:
            print(f"  ⚠ Error limpiando plantillas: {e}")
        try:
            cleanup_tareas_test()
        except Exception as e:
            print(f"  ⚠ Error limpiando tareas: {e}")


if __name__ == "__main__":
    main()
