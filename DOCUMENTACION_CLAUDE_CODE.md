# Documentación: API Script — Google Sheets & Google Drive

## ¿Qué es esto?

Tienes acceso a `api_script.js`, un script de Node.js que te permite leer y escribir datos en Google Sheets y Google Drive del usuario. Puedes ejecutarlo directamente desde la terminal con el comando `node api_script.js`.

**Importante:** El script necesita el archivo `credentials.json` en el mismo directorio, o la variable de entorno `GOOGLE_CREDENTIALS_PATH` apuntando a él.

---

## Instalación (solo la primera vez)

```bash
npm install googleapis
```

---

## Cómo usar el script

```
node api_script.js <comando> '<JSON con argumentos>'
```

Todos los resultados se imprimen en stdout como JSON con el formato:
```json
{ "success": true, "data": { ... } }
```
o en caso de error:
```json
{ "success": false, "error": "mensaje de error" }
```

---

## Comandos de Google Sheets

### `sheets:read` — Leer un rango

Lee los valores de un rango de celdas.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `spreadsheetId` | string | ✅ | ID del spreadsheet (parte de la URL: `.../spreadsheets/d/<ID>/...`) |
| `range` | string | ✅ | Rango en notación A1. Ej: `"Sheet1!A1:D10"`, `"Hoja1!B:B"` |

**Ejemplo:**
```bash
node api_script.js sheets:read '{"spreadsheetId":"1BxiM...","range":"Sheet1!A1:C5"}'
```

**Respuesta:**
```json
{
  "success": true,
  "data": {
    "values": [["Nombre", "Edad", "Ciudad"], ["Ana", "28", "Madrid"]],
    "range": "Sheet1!A1:C2"
  }
}
```

---

### `sheets:write` — Escribir en un rango

Sobreescribe un rango con los valores dados.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `spreadsheetId` | string | ✅ | ID del spreadsheet |
| `range` | string | ✅ | Rango de destino. Ej: `"Sheet1!A1"` |
| `values` | array[][] | ✅ | Array de filas. Cada fila es un array de valores |
| `valueInputOption` | string | ❌ | `"USER_ENTERED"` (default) interpreta fórmulas; `"RAW"` escribe literal |

**Ejemplo:**
```bash
node api_script.js sheets:write '{
  "spreadsheetId": "1BxiM...",
  "range": "Sheet1!A1",
  "values": [["Nombre","Edad"],["Ana",28],["Luis",35]]
}'
```

---

### `sheets:append` — Agregar filas al final

Añade filas nuevas al final de los datos existentes en el rango indicado.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `spreadsheetId` | string | ✅ | ID del spreadsheet |
| `range` | string | ✅ | Hoja de destino. Ej: `"Sheet1"` o `"Sheet1!A:A"` |
| `values` | array[][] | ✅ | Filas a agregar |

**Ejemplo:**
```bash
node api_script.js sheets:append '{
  "spreadsheetId": "1BxiM...",
  "range": "Sheet1",
  "values": [["Pedro", 42, "Barcelona"]]
}'
```

---

### `sheets:clear` — Limpiar un rango

Borra el contenido de un rango (sin borrar el formato).

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `spreadsheetId` | string | ✅ | ID del spreadsheet |
| `range` | string | ✅ | Rango a limpiar |

**Ejemplo:**
```bash
node api_script.js sheets:clear '{"spreadsheetId":"1BxiM...","range":"Sheet1!A2:D100"}'
```

---

### `sheets:list-sheets` — Listar pestañas

Lista todas las pestañas (hojas) de un spreadsheet con sus metadatos.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `spreadsheetId` | string | ✅ | ID del spreadsheet |

**Ejemplo:**
```bash
node api_script.js sheets:list-sheets '{"spreadsheetId":"1BxiM..."}'
```

**Respuesta:**
```json
{
  "success": true,
  "data": {
    "sheets": [
      {"sheetId": 0, "title": "Sheet1", "index": 0, "rowCount": 1000, "columnCount": 26}
    ]
  }
}
```

---

### `sheets:add-sheet` — Crear pestaña nueva

Crea una hoja nueva dentro de un spreadsheet existente.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `spreadsheetId` | string | ✅ | ID del spreadsheet |
| `title` | string | ✅ | Nombre de la nueva pestaña |

**Ejemplo:**
```bash
node api_script.js sheets:add-sheet '{"spreadsheetId":"1BxiM...","title":"Resumen 2025"}'
```

---

### `sheets:batch-write` — Escribir en múltiples rangos

Escribe en varios rangos distintos con una sola llamada.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `spreadsheetId` | string | ✅ | ID del spreadsheet |
| `data` | array | ✅ | Array de objetos `{range, values}` |

**Ejemplo:**
```bash
node api_script.js sheets:batch-write '{
  "spreadsheetId": "1BxiM...",
  "data": [
    {"range": "Sheet1!A1", "values": [["Título"]]},
    {"range": "Sheet1!A3", "values": [["Dato 1", "Dato 2"]]}
  ]
}'
```

---

## Comandos de Google Drive

### `drive:list` — Listar archivos

Lista archivos y carpetas. Todos los filtros son opcionales.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `folderId` | string | ❌ | ID de carpeta para filtrar por carpeta padre |
| `mimeType` | string | ❌ | Filtrar por tipo MIME. Ej: `"application/vnd.google-apps.spreadsheet"` |
| `pageSize` | number | ❌ | Máximo de resultados (default: 50) |
| `query` | string | ❌ | Filtro extra en sintaxis de Drive API |

**Tipos MIME útiles:**
- Google Sheet: `application/vnd.google-apps.spreadsheet`
- Google Doc: `application/vnd.google-apps.document`
- Carpeta: `application/vnd.google-apps.folder`
- PDF: `application/pdf`
- Texto: `text/plain`

**Ejemplo:**
```bash
node api_script.js drive:list '{"folderId":"1xyz...","mimeType":"application/vnd.google-apps.spreadsheet"}'
```

---

### `drive:get` — Obtener metadatos de archivo

Obtiene información detallada de un archivo por su ID.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `fileId` | string | ✅ | ID del archivo en Drive |

**Ejemplo:**
```bash
node api_script.js drive:get '{"fileId":"1abc..."}'
```

---

### `drive:upload` — Subir archivo de texto

Crea un archivo nuevo en Drive con contenido de texto o JSON.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `name` | string | ✅ | Nombre del archivo |
| `content` | string | ✅ | Contenido del archivo |
| `mimeType` | string | ❌ | Tipo MIME (default: `text/plain`) |
| `folderId` | string | ❌ | ID de carpeta donde guardarlo |

**Ejemplo:**
```bash
node api_script.js drive:upload '{
  "name": "reporte.txt",
  "content": "Este es el contenido del archivo",
  "folderId": "1xyz..."
}'
```

---

### `drive:read-text` — Leer contenido de archivo de texto

Lee el contenido de un archivo de texto almacenado en Drive.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `fileId` | string | ✅ | ID del archivo |

**Ejemplo:**
```bash
node api_script.js drive:read-text '{"fileId":"1abc..."}'
```

---

### `drive:update-content` — Actualizar contenido de archivo

Reemplaza el contenido de un archivo existente en Drive.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `fileId` | string | ✅ | ID del archivo a actualizar |
| `content` | string | ✅ | Nuevo contenido |
| `mimeType` | string | ❌ | Tipo MIME (default: `text/plain`) |

---

### `drive:create-folder` — Crear carpeta

Crea una carpeta nueva en Drive.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `name` | string | ✅ | Nombre de la carpeta |
| `parentFolderId` | string | ❌ | ID de la carpeta padre |

---

### `drive:create-sheet` — Crear Google Sheet vacío

Crea un Google Sheet nuevo vacío desde Drive.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `name` | string | ✅ | Nombre del spreadsheet |
| `folderId` | string | ❌ | Carpeta donde crearlo |

---

### `drive:move` — Mover archivo

Mueve un archivo a una carpeta diferente.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `fileId` | string | ✅ | ID del archivo |
| `newFolderId` | string | ✅ | ID de la carpeta destino |

---

### `drive:rename` — Renombrar archivo

Cambia el nombre de un archivo o carpeta.

**Argumentos:**
| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `fileId` | string | ✅ | ID del archivo |
| `newName` | string | ✅ | Nuevo nombre |

---

## Cómo encontrar los IDs

**ID de un Google Sheet o carpeta de Drive:**
En la URL del navegador:
```
https://docs.google.com/spreadsheets/d/  1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms  /edit
                                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                                        Este es el spreadsheetId
```
```
https://drive.google.com/drive/folders/  1AbCdEfGhIjKlMnOpQrStUv  
                                         ^^^^^^^^^^^^^^^^^^^^^^^^
                                              Este es el folderId
```

---

## Flujos de trabajo típicos

### Leer datos y procesar

```bash
# 1. Leer datos de una hoja
node api_script.js sheets:read '{"spreadsheetId":"ID","range":"Sheet1!A:D"}'

# 2. Procesar los datos y escribir resultados en otra hoja
node api_script.js sheets:write '{"spreadsheetId":"ID","range":"Resultados!A1","values":[...]}'
```

### Crear un reporte y guardarlo en Drive

```bash
# 1. Leer datos del Sheet
node api_script.js sheets:read '{"spreadsheetId":"ID","range":"Sheet1!A1:Z100"}'

# 2. Crear carpeta de reportes si no existe
node api_script.js drive:create-folder '{"name":"Reportes 2025","parentFolderId":"CARPETA_PADRE"}'

# 3. Subir el reporte generado
node api_script.js drive:upload '{"name":"reporte_marzo.txt","content":"...","folderId":"CARPETA_REPORTES"}'
```

### Actualizar datos de forma incremental

```bash
# Agregar filas nuevas sin borrar las existentes
node api_script.js sheets:append '{
  "spreadsheetId": "ID",
  "range": "Sheet1",
  "values": [["2025-03-27", "Venta", 150.00]]
}'
```

---

## Notas importantes

- El script devuelve siempre JSON. Parsea `data` para acceder a los resultados.
- Los IDs de spreadsheet y carpeta nunca cambian aunque cambies el nombre del archivo.
- La Service Account necesita tener acceso compartido al archivo para poder leer/escribir.
- Para archivos Google Docs o Sheets nativos, usa `drive:read-text` solo si exportas a texto plano. Para Sheets siempre usa los comandos `sheets:*`.
- `sheets:write` sobreescribe el rango completo. Usa `sheets:append` si quieres añadir sin borrar.
