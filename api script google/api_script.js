#!/usr/bin/env node
/**
 * ============================================================
 *  API SCRIPT — Google Sheets & Google Drive for Claude Code
 * ============================================================
 * Uso: node api_script.js <comando> [argumentos en JSON]
 *
 * Requiere:
 *   - Node.js >= 18
 *   - npm install googleapis
 *   - Variable de entorno GOOGLE_CREDENTIALS_PATH apuntando
 *     al archivo credentials.json de tu Service Account,
 *     O bien coloca credentials.json en el mismo directorio.
 * ============================================================
 */

const { google } = require("googleapis");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

// ─── Autenticación ───────────────────────────────────────────
function getAuth() {
  const credPath =
    process.env.GOOGLE_CREDENTIALS_PATH ||
    path.join(__dirname, "credentials.json");

  if (!fs.existsSync(credPath)) {
    throw new Error(
      `No se encontró credentials.json en: ${credPath}\n` +
        `Descarga la clave de tu Service Account desde Google Cloud Console.`
    );
  }

  const credentials = JSON.parse(fs.readFileSync(credPath, "utf8"));

  return new google.auth.GoogleAuth({
    credentials,
    scopes: [
      "https://www.googleapis.com/auth/spreadsheets",
      "https://www.googleapis.com/auth/drive",
    ],
  });
}

// ─── Helpers ─────────────────────────────────────────────────
function ok(data) {
  console.log(JSON.stringify({ success: true, data }, null, 2));
}
function fail(msg) {
  console.error(JSON.stringify({ success: false, error: String(msg) }, null, 2));
  process.exit(1);
}
function arg(obj, key, required = true) {
  if (required && obj[key] === undefined)
    throw new Error(`Falta el argumento: ${key}`);
  return obj[key];
}

// ─── SHEETS: Leer rango ──────────────────────────────────────
async function sheetsRead({ spreadsheetId, range }) {
  const auth = getAuth();
  const sheets = google.sheets({ version: "v4", auth });
  const res = await sheets.spreadsheets.values.get({ spreadsheetId, range });
  ok({ values: res.data.values || [], range: res.data.range });
}

// ─── SHEETS: Escribir rango ──────────────────────────────────
async function sheetsWrite({ spreadsheetId, range, values, valueInputOption = "USER_ENTERED" }) {
  const auth = getAuth();
  const sheets = google.sheets({ version: "v4", auth });
  const res = await sheets.spreadsheets.values.update({
    spreadsheetId,
    range,
    valueInputOption,
    requestBody: { values },
  });
  ok({
    updatedRange: res.data.updatedRange,
    updatedRows: res.data.updatedRows,
    updatedColumns: res.data.updatedColumns,
    updatedCells: res.data.updatedCells,
  });
}

// ─── SHEETS: Agregar filas (append) ──────────────────────────
async function sheetsAppend({ spreadsheetId, range, values, valueInputOption = "USER_ENTERED" }) {
  const auth = getAuth();
  const sheets = google.sheets({ version: "v4", auth });
  const res = await sheets.spreadsheets.values.append({
    spreadsheetId,
    range,
    valueInputOption,
    insertDataOption: "INSERT_ROWS",
    requestBody: { values },
  });
  ok({
    updatedRange: res.data.updates?.updatedRange,
    updatedRows: res.data.updates?.updatedRows,
  });
}

// ─── SHEETS: Limpiar rango ───────────────────────────────────
async function sheetsClear({ spreadsheetId, range }) {
  const auth = getAuth();
  const sheets = google.sheets({ version: "v4", auth });
  const res = await sheets.spreadsheets.values.clear({ spreadsheetId, range });
  ok({ clearedRange: res.data.clearedRange });
}

// ─── SHEETS: Crear hoja nueva ─────────────────────────────────
async function sheetsAddSheet({ spreadsheetId, title }) {
  const auth = getAuth();
  const sheets = google.sheets({ version: "v4", auth });
  const res = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [{ addSheet: { properties: { title } } }],
    },
  });
  const newSheet = res.data.replies[0].addSheet.properties;
  ok({ sheetId: newSheet.sheetId, title: newSheet.title });
}

// ─── SHEETS: Listar hojas ────────────────────────────────────
async function sheetsListSheets({ spreadsheetId }) {
  const auth = getAuth();
  const sheets = google.sheets({ version: "v4", auth });
  const res = await sheets.spreadsheets.get({ spreadsheetId });
  ok({
    sheets: res.data.sheets.map((s) => ({
      sheetId: s.properties.sheetId,
      title: s.properties.title,
      index: s.properties.index,
      rowCount: s.properties.gridProperties?.rowCount,
      columnCount: s.properties.gridProperties?.columnCount,
    })),
  });
}

// ─── SHEETS: Batch update (escritura múltiple) ────────────────
async function sheetsBatchWrite({ spreadsheetId, data, valueInputOption = "USER_ENTERED" }) {
  // data = [{ range, values }, ...]
  const auth = getAuth();
  const sheets = google.sheets({ version: "v4", auth });
  const res = await sheets.spreadsheets.values.batchUpdate({
    spreadsheetId,
    requestBody: { valueInputOption, data },
  });
  ok({ totalUpdatedCells: res.data.totalUpdatedCells });
}

// ─── DRIVE: Listar archivos ───────────────────────────────────
async function driveList({ folderId, mimeType, pageSize = 50, query } = {}) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });

  let q = "trashed = false";
  if (folderId) q += ` and '${folderId}' in parents`;
  if (mimeType) q += ` and mimeType = '${mimeType}'`;
  if (query) q += ` and ${query}`;

  const res = await drive.files.list({
    q,
    pageSize,
    fields: "files(id, name, mimeType, size, modifiedTime, parents, webViewLink)",
  });
  ok({ files: res.data.files });
}

// ─── DRIVE: Obtener metadatos de archivo ──────────────────────
async function driveGet({ fileId }) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });
  const res = await drive.files.get({
    fileId,
    fields: "id, name, mimeType, size, modifiedTime, parents, webViewLink, description",
  });
  ok(res.data);
}

// ─── DRIVE: Subir archivo de texto / JSON ────────────────────
async function driveUpload({ name, content, mimeType = "text/plain", folderId }) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });

  const metadata = { name };
  if (folderId) metadata.parents = [folderId];

  const media = {
    mimeType,
    body: require("stream").Readable.from([content]),
  };

  const res = await drive.files.create({
    requestBody: metadata,
    media,
    fields: "id, name, webViewLink",
  });
  ok(res.data);
}

// ─── DRIVE: Leer contenido de archivo de texto ───────────────
async function driveReadText({ fileId }) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });
  const res = await drive.files.get(
    { fileId, alt: "media" },
    { responseType: "text" }
  );
  ok({ content: res.data });
}

// ─── DRIVE: Actualizar contenido de archivo ───────────────────
async function driveUpdateContent({ fileId, content, mimeType = "text/plain" }) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });
  const media = {
    mimeType,
    body: require("stream").Readable.from([content]),
  };
  const res = await drive.files.update({
    fileId,
    media,
    fields: "id, name, modifiedTime",
  });
  ok(res.data);
}

// ─── DRIVE: Crear carpeta ─────────────────────────────────────
async function driveCreateFolder({ name, parentFolderId }) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });
  const metadata = {
    name,
    mimeType: "application/vnd.google-apps.folder",
  };
  if (parentFolderId) metadata.parents = [parentFolderId];
  const res = await drive.files.create({
    requestBody: metadata,
    fields: "id, name, webViewLink",
  });
  ok(res.data);
}

// ─── DRIVE: Crear Google Sheet vacío desde Drive ─────────────
async function driveCreateSheet({ name, folderId }) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });
  const metadata = {
    name,
    mimeType: "application/vnd.google-apps.spreadsheet",
  };
  if (folderId) metadata.parents = [folderId];
  const res = await drive.files.create({
    requestBody: metadata,
    fields: "id, name, webViewLink",
  });
  ok(res.data);
}

// ─── DRIVE: Mover archivo a otra carpeta ──────────────────────
async function driveMove({ fileId, newFolderId }) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });

  // Obtener padres actuales
  const file = await drive.files.get({ fileId, fields: "parents" });
  const previousParents = (file.data.parents || []).join(",");

  const res = await drive.files.update({
    fileId,
    addParents: newFolderId,
    removeParents: previousParents,
    fields: "id, name, parents",
  });
  ok(res.data);
}

// ─── DRIVE: Renombrar archivo ─────────────────────────────────
async function driveRename({ fileId, newName }) {
  const auth = getAuth();
  const drive = google.drive({ version: "v3", auth });
  const res = await drive.files.update({
    fileId,
    requestBody: { name: newName },
    fields: "id, name",
  });
  ok(res.data);
}

// ─── Dispatcher principal ─────────────────────────────────────
const COMMANDS = {
  // Sheets
  "sheets:read": sheetsRead,
  "sheets:write": sheetsWrite,
  "sheets:append": sheetsAppend,
  "sheets:clear": sheetsClear,
  "sheets:add-sheet": sheetsAddSheet,
  "sheets:list-sheets": sheetsListSheets,
  "sheets:batch-write": sheetsBatchWrite,

  // Drive
  "drive:list": driveList,
  "drive:get": driveGet,
  "drive:upload": driveUpload,
  "drive:read-text": driveReadText,
  "drive:update-content": driveUpdateContent,
  "drive:create-folder": driveCreateFolder,
  "drive:create-sheet": driveCreateSheet,
  "drive:move": driveMove,
  "drive:rename": driveRename,
};

async function main() {
  const [, , command, rawArgs] = process.argv;

  if (!command || command === "--help" || command === "-h") {
    console.log(`
╔══════════════════════════════════════════════════════════╗
║          API Script — Google Sheets & Drive              ║
╚══════════════════════════════════════════════════════════╝

Uso: node api_script.js <comando> '<JSON con argumentos>'

Comandos disponibles:
  SHEETS
    sheets:read           Lee un rango de una hoja
    sheets:write          Escribe en un rango
    sheets:append         Agrega filas al final
    sheets:clear          Limpia un rango
    sheets:add-sheet      Crea una pestaña nueva
    sheets:list-sheets    Lista todas las pestañas
    sheets:batch-write    Escribe en múltiples rangos

  DRIVE
    drive:list            Lista archivos/carpetas
    drive:get             Obtiene metadatos de un archivo
    drive:upload          Sube contenido de texto
    drive:read-text       Lee el contenido de un archivo de texto
    drive:update-content  Actualiza el contenido de un archivo
    drive:create-folder   Crea una carpeta
    drive:create-sheet    Crea un Google Sheet vacío
    drive:move            Mueve un archivo a otra carpeta
    drive:rename          Renombra un archivo

Ejemplos:
  node api_script.js sheets:read '{"spreadsheetId":"1abc...","range":"Sheet1!A1:D10"}'
  node api_script.js sheets:append '{"spreadsheetId":"1abc...","range":"Sheet1","values":[["Hola","Mundo"]]}'
  node api_script.js drive:list '{"folderId":"1xyz..."}'
    `);
    return;
  }

  const handler = COMMANDS[command];
  if (!handler) {
    fail(`Comando desconocido: "${command}". Usa --help para ver la lista.`);
    return;
  }

  let args = {};
  if (rawArgs) {
    try {
      args = JSON.parse(rawArgs);
    } catch {
      fail(`El segundo argumento debe ser un JSON válido. Recibido: ${rawArgs}`);
      return;
    }
  }

  try {
    await handler(args);
  } catch (err) {
    fail(err.message || err);
  }
}

main();
