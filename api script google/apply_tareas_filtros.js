/**
 * tareas — arreglar filtro y añadir vistas por estado/fecha.
 *
 * Problema diagnosticado:
 *   - Hoja `tareas` con dos bloques de datos: filas 1-55 y 990-1000.
 *   - 934 filas vacías intermedias (56-989) creadas por el comportamiento
 *     de `append` de n8n al detectar la tabla.
 *   - Filtro básico previo abarcaba sólo F1:F992 → las filas 993-1000
 *     quedaban fuera del filtro y mostraban "hechas" siempre.
 *
 * Acciones:
 *   1. Eliminar filas 56-989 (vacías) — datos pasan a ser contiguos 1-66.
 *   2. Asegurar gridProperties.rowCount >= 5000 (margen para appends futuros).
 *   3. Limpiar filtro básico previo y crear uno nuevo en A1:M5000
 *      con criterio "ocultar vacío y hecha" en columna F (estado).
 *   4. Crear 3 Vistas de filtro:
 *        - "Solo pendientes"            → estado = pendiente
 *        - "Pendientes hoy o futuras"   → estado = pendiente AND fecha ≥ hoy
 *        - "Pendientes vencidas"        → estado = pendiente AND fecha < hoy
 *      Las 3 ordenadas por fecha asc.
 *
 * Idempotencia:
 *   - Si rows 56-989 ya están eliminadas (rowCount detectado < 989), se omite borrado.
 *   - Las vistas de filtro con los nombres anteriores se eliminan y se vuelven a crear,
 *     para garantizar criterios consistentes en cada ejecución.
 */
const path = require("path");
const { google } = require(path.resolve(__dirname, "..", "node_modules", "googleapis"));

const SPREADSHEET_ID = "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI";
const SHEET_TITLE = "tareas";
const FV_NAMES = [
  "Solo pendientes",
  "Pendientes hoy o futuras",
  "Pendientes vencidas",
];

// columnas (0-indexed):
// A=0 row_number, B=1 id, C=2 zona, D=3 tarea, E=4 prioridad,
// F=5 estado,    G=6 fecha, H=7 recurrente, I=8 dia_recurrencia,
// J=9 observaciones, K=10 id_evento_origen, L=11 tipo_origen
const COL_ESTADO = 5;
const COL_FECHA = 6;

const TARGET_ROW_COUNT = 5000;
const FILTER_END_ROW = 5000; // endRowIndex es exclusivo

async function main() {
  const auth = new google.auth.GoogleAuth({
    keyFile: path.join(__dirname, "credentials.json"),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const sheets = google.sheets({ version: "v4", auth: await auth.getClient() });

  // 1. Leer estado actual
  const meta = await sheets.spreadsheets.get({
    spreadsheetId: SPREADSHEET_ID,
    fields: "sheets(properties(title,sheetId,gridProperties),basicFilter,filterViews(filterViewId,title))",
  });
  const sheet = meta.data.sheets.find((s) => s.properties.title === SHEET_TITLE);
  if (!sheet) throw new Error(`Hoja '${SHEET_TITLE}' no encontrada`);
  const sheetId = sheet.properties.sheetId;
  const rowCount = sheet.properties.gridProperties.rowCount;
  console.log(`Hoja '${SHEET_TITLE}' sheetId=${sheetId} rowCount=${rowCount}`);

  // Detectar bloques de datos para confirmar que las filas 56-989 están vacías
  const valuesRes = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${SHEET_TITLE}!B1:B${rowCount}`,
  });
  const colB = valuesRes.data.values || [];
  const filledRows = [];
  for (let i = 0; i < colB.length; i++) {
    if ((colB[i] && colB[i][0] || "").trim()) filledRows.push(i + 1);
  }
  console.log(`Filas con id rellenado: ${filledRows.length}`);
  console.log(`Primera fila con id: ${filledRows[0]}, última: ${filledRows[filledRows.length - 1]}`);

  const requests = [];

  // 2. Eliminar filas 56-989 si siguen vacías y existen
  // Comprobar que ninguna fila 56-989 tiene id (defensa adicional)
  const gapRowsWithId = filledRows.filter((r) => r >= 56 && r <= 989);
  if (gapRowsWithId.length > 0) {
    console.log(`ABORT: hay ${gapRowsWithId.length} filas con datos en 56-989. Revisar manualmente.`);
    process.exit(1);
  }
  if (rowCount >= 989 && filledRows.some((r) => r >= 990)) {
    requests.push({
      deleteDimension: {
        range: {
          sheetId,
          dimension: "ROWS",
          startIndex: 55, // fila 56 (0-indexed)
          endIndex: 989, // exclusivo → borra hasta fila 989
        },
      },
    });
    console.log("→ deleteDimension: filas 56-989 (934 filas vacías)");
  } else {
    console.log("→ deleteDimension: omitido (ya limpio)");
  }

  // 3. Extender gridProperties.rowCount a TARGET_ROW_COUNT si hace falta
  // Tras la eliminación rowCount será (rowCount - 934). Lo reponemos.
  const rowsAfterDelete = gapRowsWithId.length === 0 && rowCount >= 989 ? rowCount - 934 : rowCount;
  if (rowsAfterDelete < TARGET_ROW_COUNT) {
    requests.push({
      updateSheetProperties: {
        properties: {
          sheetId,
          gridProperties: { rowCount: TARGET_ROW_COUNT },
        },
        fields: "gridProperties.rowCount",
      },
    });
    console.log(`→ updateSheetProperties: rowCount → ${TARGET_ROW_COUNT}`);
  }

  // 4. Limpiar filtro básico previo
  if (sheet.basicFilter) {
    requests.push({ clearBasicFilter: { sheetId } });
    console.log("→ clearBasicFilter (filtro básico previo)");
  }

  // 5. Crear filtro básico nuevo: A1:M5000 con criterio "ocultar vacío y hecha" en col F
  requests.push({
    setBasicFilter: {
      filter: {
        range: {
          sheetId,
          startRowIndex: 0,
          endRowIndex: FILTER_END_ROW,
          startColumnIndex: 0,
          endColumnIndex: 13, // A..M (exclusivo) → 0..12
        },
        filterSpecs: [
          {
            columnIndex: COL_ESTADO,
            filterCriteria: { hiddenValues: ["", "hecha"] },
          },
        ],
      },
    },
  });
  console.log("→ setBasicFilter: A1:M5000, ocultar '' y 'hecha' en col F");

  // 6. Eliminar vistas de filtro previas con los mismos nombres (idempotencia)
  const previousFVs = (sheet.filterViews || []).filter((fv) => FV_NAMES.includes(fv.title));
  for (const fv of previousFVs) {
    requests.push({ deleteFilterView: { filterId: fv.filterViewId } });
    console.log(`→ deleteFilterView: '${fv.title}' (id=${fv.filterViewId})`);
  }

  // 7. Crear 3 vistas de filtro
  const baseRange = {
    sheetId,
    startRowIndex: 0,
    endRowIndex: FILTER_END_ROW,
    startColumnIndex: 0,
    endColumnIndex: 13,
  };
  const sortByFechaAsc = [{ dimensionIndex: COL_FECHA, sortOrder: "ASCENDING" }];

  // 7.1 Solo pendientes
  requests.push({
    addFilterView: {
      filter: {
        title: "Solo pendientes",
        range: baseRange,
        sortSpecs: sortByFechaAsc,
        filterSpecs: [
          {
            columnIndex: COL_ESTADO,
            filterCriteria: {
              condition: {
                type: "TEXT_EQ",
                values: [{ userEnteredValue: "pendiente" }],
              },
            },
          },
        ],
      },
    },
  });

  // 7.2 Pendientes hoy o futuras (fecha >= hoy)
  requests.push({
    addFilterView: {
      filter: {
        title: "Pendientes hoy o futuras",
        range: baseRange,
        sortSpecs: sortByFechaAsc,
        filterSpecs: [
          {
            columnIndex: COL_ESTADO,
            filterCriteria: {
              condition: {
                type: "TEXT_EQ",
                values: [{ userEnteredValue: "pendiente" }],
              },
            },
          },
          {
            columnIndex: COL_FECHA,
            filterCriteria: {
              // DATE_ON_OR_AFTER no está soportado en filtros → usamos
              // DATE_AFTER YESTERDAY (≡ hoy o posterior).
              condition: {
                type: "DATE_AFTER",
                values: [{ relativeDate: "YESTERDAY" }],
              },
            },
          },
        ],
      },
    },
  });

  // 7.3 Pendientes vencidas (fecha < hoy)
  requests.push({
    addFilterView: {
      filter: {
        title: "Pendientes vencidas",
        range: baseRange,
        sortSpecs: sortByFechaAsc,
        filterSpecs: [
          {
            columnIndex: COL_ESTADO,
            filterCriteria: {
              condition: {
                type: "TEXT_EQ",
                values: [{ userEnteredValue: "pendiente" }],
              },
            },
          },
          {
            columnIndex: COL_FECHA,
            filterCriteria: {
              condition: {
                type: "DATE_BEFORE",
                values: [{ relativeDate: "TODAY" }],
              },
            },
          },
        ],
      },
    },
  });
  console.log("→ addFilterView × 3 (Solo pendientes / Pendientes hoy o futuras / Pendientes vencidas)");

  // 8. Aplicar todo en un único batchUpdate
  console.log(`\nEnviando batchUpdate con ${requests.length} requests…`);
  const res = await sheets.spreadsheets.batchUpdate({
    spreadsheetId: SPREADSHEET_ID,
    requestBody: { requests },
  });
  console.log("✓ batchUpdate OK");

  // 9. Verificación post-aplicación
  const verify = await sheets.spreadsheets.get({
    spreadsheetId: SPREADSHEET_ID,
    fields: "sheets(properties(title,gridProperties),basicFilter,filterViews(filterViewId,title))",
  });
  const sheetAfter = verify.data.sheets.find((s) => s.properties.title === SHEET_TITLE);
  console.log("\n— Estado tras aplicar —");
  console.log("rowCount:", sheetAfter.properties.gridProperties.rowCount);
  console.log("basicFilter range:", JSON.stringify(sheetAfter.basicFilter?.range));
  console.log("basicFilter criteria:", JSON.stringify(sheetAfter.basicFilter?.filterSpecs));
  console.log("filterViews:", (sheetAfter.filterViews || []).map((fv) => fv.title));
}

main().catch((e) => {
  console.error("FATAL:", e.message);
  if (e.errors) console.error(JSON.stringify(e.errors, null, 2));
  process.exit(1);
});
