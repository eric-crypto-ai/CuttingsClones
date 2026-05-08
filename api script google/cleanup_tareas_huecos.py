"""
Compacta la hoja `tareas` eliminando filas físicas vacías intermedias.

Por qué es necesario:
  El workflow `/tareas-eliminar` calcula el row físico como `idx + 2` donde
  `idx` es el índice del item en el array que emite el Sheets read. Sheets
  read salta filas vacías, así que cualquier hueco en la hoja desfasa el
  cálculo y el delete borra la fila equivocada (o ninguna). Ver
  `errores_recurrentes.md` §N8N-015.

  Este script detecta filas físicas con `id` vacío entre las filas con datos
  y las elimina vía `batchUpdate(deleteDimension)` — operación que compacta
  automáticamente las filas posteriores.

Uso:
  python3 "api script google/cleanup_tareas_huecos.py"

Idempotente: si no hay huecos, no hace nada.
"""
import os
import sys
import subprocess
import json

SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI"
SHEET_TAREAS_GID = 1404161276
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    # Reusar api_script.js para leer (ya autenticado con credentials.json)
    api_script = os.path.join(HERE, "api_script.js")
    res = subprocess.run(
        ["node", api_script, "sheets:read", json.dumps({
            "spreadsheetId": SPREADSHEET_ID,
            "range": "tareas!A1:N5000",
        })],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(res.stdout)["data"]["values"]
    if not data:
        print("Hoja vacía. Nada que hacer.")
        return

    headers = data[0]
    i_id = headers.index("id")

    # Detectar filas físicas vacías (1-based)
    huecos = []
    for n_fila, r in enumerate(data[1:], start=2):
        cells = list(r) + [""] * (len(headers) - len(r))
        if not str(cells[i_id]).strip() and not str(cells[2]).strip():  # id y tarea vacíos
            huecos.append(n_fila)

    if not huecos:
        print("✓ Sin huecos en `tareas`. Hoja ya está compacta.")
        return

    print(f"Huecos físicos detectados: {huecos}")

    # Eliminar de mayor a menor para no desplazar índices
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        os.path.join(HERE, "credentials.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    sheets = build("sheets", "v4", credentials=creds)

    requests = []
    for row in sorted(huecos, reverse=True):
        requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId": SHEET_TAREAS_GID,
                    "dimension": "ROWS",
                    "startIndex": row - 1,  # 0-based
                    "endIndex": row,
                },
            },
        })

    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()
    print(f"✓ {len(huecos)} fila(s) vacía(s) eliminada(s). Hoja compactada.")


if __name__ == "__main__":
    main()
