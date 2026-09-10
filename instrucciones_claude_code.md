# Instrucciones para Claude Code — Mejoras Backend CuttingsClones

## CONTEXTO DEL PROYECTO

Tengo un sistema de gestión de tareas para una empresa de cultivo (CuttingsClones). La arquitectura es:
- **Frontend**: `index.html` estático en GitHub Pages
- **Backend**: webhooks en n8n desplegado en Railway (`https://primary-production-2cf7.up.railway.app/webhook`)
- **Base de datos**: Google Sheets (spreadsheetId: `17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI`)
- **API local**: `api_script.js` (Node.js con googleapis) para leer/escribir Sheets y Drive

### Pestañas actuales en el Sheet:
- `tareas` (gid=1404161276): columnas → id, zona, tarea, prioridad, estado, fecha, recurrente, dia_recurrencia, observaciones
- `tareas_recurrentes` (gid=1626272047): plantillas de tareas recurrentes → id, zona, tarea, prioridad, observaciones, activa, dia_recurrencia
- Pestañas de IPM (ya funcionan, no tocar)

### Webhooks actuales en n8n:
- `GET /info-landing` → info general
- `GET /ipm-productos` → productos IPM
- `GET /ipm-lista` → lista IPM
- `POST /ipm-guardar` → guardar registro IPM
- `GET /tareas-lista` → lista tareas pendientes agrupadas por zona
- `POST /tareas-eliminar` → elimina una tarea (recibe `{id}`)
- `POST /tareas-posponer` → pospone tarea (recibe `{id, nueva_fecha}`)

### Zonas del sistema: madres, esquejes, floracion, limpieza, mantenimiento

---

## FASE 1: Preparar la base de datos (Google Sheets)

### 1.1 — Ampliar columnas de la pestaña `tareas`

Usando el api_script.js, necesito añadir estas columnas nuevas a la pestaña `tareas` (después de las existentes):
- `motivo_posponer` (texto: razón del último aplazamiento)
- `veces_pospuesta` (número: contador de veces pospuesta, default 0)
- `fecha_completada` (fecha: cuándo se marcó como hecha)

**Importante**: NO borrar datos existentes. Solo añadir las cabeceras en las columnas que estén vacías tras las actuales.

Para hacer esto:
1. Primero lee la fila 1 de `tareas` para ver qué columnas hay actualmente
2. Añade las nuevas cabeceras en las columnas siguientes

```bash
# Ejemplo: si las columnas actuales van de A a I, las nuevas irían en J, K, L
node api_script.js sheets:read '{"spreadsheetId":"17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI","range":"tareas!1:1"}'
# Luego escribe las nuevas cabeceras en la posición correcta
```

### 1.2 — Ampliar la pestaña `tareas_recurrentes` para recurrencia avanzada

Añadir columnas:
- `tipo_recurrencia` (valores: `semanal`, `quincenal`, `mensual`, `cada_x_dias`)
- `config_recurrencia` (el valor asociado: nombre del día, número de día del mes, o número de días)
- `ultima_generada` (fecha YYYY-MM-DD de la última vez que se generó esta tarea)

**Nota**: la columna `dia_recurrencia` existente se mantiene por compatibilidad. Para las plantillas existentes, rellenar `tipo_recurrencia` con `"semanal"` y copiar `dia_recurrencia` a `config_recurrencia`.

```bash
# Lee primero las cabeceras actuales
node api_script.js sheets:read '{"spreadsheetId":"17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI","range":"tareas_recurrentes!1:1"}'
```

### 1.3 — Crear nueva pestaña `compras`

```bash
node api_script.js sheets:add-sheet '{"spreadsheetId":"17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI","title":"compras"}'
```

Luego escribir las cabeceras:
```bash
node api_script.js sheets:write '{"spreadsheetId":"17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI","range":"compras!A1","values":[["id","item","cantidad","unidad","estado","fecha_añadido","notas"]]}'
```

### 1.4 — Crear nueva pestaña `historial_tareas`

Para mover tareas completadas y mantener limpia la pestaña principal:

```bash
node api_script.js sheets:add-sheet '{"spreadsheetId":"17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI","title":"historial_tareas"}'
```

Cabeceras (mismas que tareas + fecha_completada):
```bash
node api_script.js sheets:write '{"spreadsheetId":"17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI","range":"historial_tareas!A1","values":[["id","zona","tarea","prioridad","estado","fecha","recurrente","dia_recurrencia","observaciones","motivo_posponer","veces_pospuesta","fecha_completada"]]}'
```

---

## FASE 2: Nuevos workflows de n8n

### 2.1 — Workflow: Crear Tarea (`POST /tareas-crear`)

**Flujo:**
1. Webhook POST recibe: `{zona, tarea, prioridad, fecha, observaciones}`
2. Validar que zona, tarea y fecha no estén vacíos
3. Leer todas las tareas de la pestaña `tareas` para obtener el max(id)
4. Code node: generar nueva fila con id = max + 1, estado = "pendiente", recurrente = "no", veces_pospuesta = 0
5. Append a la pestaña `tareas`
6. Responder `{ok: true, id: nuevo_id}`

**JSON del workflow n8n para importar:**

```json
{
  "name": "Crear_Tarea",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "tareas-crear",
        "responseMode": "responseNode",
        "options": { "allowedOrigins": "*" }
      },
      "name": "Webhook Crear",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2.1,
      "position": [260, 340],
      "webhookId": "tareas-crear"
    },
    {
      "parameters": {
        "conditions": {
          "conditions": [
            {
              "leftValue": "={{ $json.body.zona }}",
              "rightValue": "",
              "operator": { "type": "string", "operation": "isNotEmpty", "singleValue": true }
            },
            {
              "leftValue": "={{ $json.body.tarea }}",
              "rightValue": "",
              "operator": { "type": "string", "operation": "isNotEmpty", "singleValue": true }
            },
            {
              "leftValue": "={{ $json.body.fecha }}",
              "rightValue": "",
              "operator": { "type": "string", "operation": "isNotEmpty", "singleValue": true }
            }
          ],
          "combinator": "and"
        }
      },
      "name": "Validar Campos",
      "type": "n8n-nodes-base.if",
      "typeVersion": 2,
      "position": [500, 340]
    },
    {
      "parameters": {
        "respondWith": "json",
        "responseBody": "={ \"ok\": false, \"error\": \"faltan_campos_requeridos\" }"
      },
      "name": "Error Validacion",
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.5,
      "position": [740, 540]
    },
    {
      "parameters": {
        "documentId": {
          "__rl": true,
          "value": "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI",
          "mode": "list",
          "cachedResultName": "Control_IPM"
        },
        "sheetName": {
          "__rl": true,
          "value": 1404161276,
          "mode": "list",
          "cachedResultName": "tareas"
        },
        "options": {}
      },
      "name": "Leer Tareas",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4.7,
      "position": [740, 340],
      "credentials": {
        "googleSheetsOAuth2Api": {
          "id": "U9MmYhXUgVdOQej5",
          "name": "Google Sheets account"
        }
      }
    },
    {
      "parameters": {
        "jsCode": "const body = $('Webhook Crear').first().json.body;\nconst filas = $input.all().map(item => item.json);\n\nlet maxId = 0;\nfor (const t of filas) {\n  const id = parseInt(t.id);\n  if (!isNaN(id) && id > maxId) maxId = id;\n}\n\nreturn [{\n  json: {\n    id: String(maxId + 1),\n    zona: body.zona,\n    tarea: body.tarea,\n    prioridad: body.prioridad || 'media',\n    estado: 'pendiente',\n    fecha: body.fecha,\n    recurrente: 'no',\n    dia_recurrencia: '',\n    observaciones: body.observaciones || '',\n    motivo_posponer: '',\n    veces_pospuesta: '0',\n    fecha_completada: ''\n  }\n}];"
      },
      "name": "Generar Tarea",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [980, 340]
    },
    {
      "parameters": {
        "operation": "append",
        "documentId": {
          "__rl": true,
          "value": "17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI",
          "mode": "list",
          "cachedResultName": "Control_IPM"
        },
        "sheetName": {
          "__rl": true,
          "value": 1404161276,
          "mode": "list",
          "cachedResultName": "tareas"
        },
        "columns": {
          "mappingMode": "defineBelow",
          "value": {
            "id": "={{ $json.id }}",
            "zona": "={{ $json.zona }}",
            "tarea": "={{ $json.tarea }}",
            "prioridad": "={{ $json.prioridad }}",
            "estado": "={{ $json.estado }}",
            "fecha": "={{ $json.fecha }}",
            "recurrente": "={{ $json.recurrente }}",
            "dia_recurrencia": "={{ $json.dia_recurrencia }}",
            "observaciones": "={{ $json.observaciones }}",
            "motivo_posponer": "={{ $json.motivo_posponer }}",
            "veces_pospuesta": "={{ $json.veces_pospuesta }}",
            "fecha_completada": "={{ $json.fecha_completada }}"
          },
          "matchingColumns": [],
          "schema": [
            {"id": "id", "displayName": "id", "type": "string", "display": true},
            {"id": "zona", "displayName": "zona", "type": "string", "display": true},
            {"id": "tarea", "displayName": "tarea", "type": "string", "display": true},
            {"id": "prioridad", "displayName": "prioridad", "type": "string", "display": true},
            {"id": "estado", "displayName": "estado", "type": "string", "display": true},
            {"id": "fecha", "displayName": "fecha", "type": "string", "display": true},
            {"id": "recurrente", "displayName": "recurrente", "type": "string", "display": true},
            {"id": "dia_recurrencia", "displayName": "dia_recurrencia", "type": "string", "display": true},
            {"id": "observaciones", "displayName": "observaciones", "type": "string", "display": true},
            {"id": "motivo_posponer", "displayName": "motivo_posponer", "type": "string", "display": true},
            {"id": "veces_pospuesta", "displayName": "veces_pospuesta", "type": "string", "display": true},
            {"id": "fecha_completada", "displayName": "fecha_completada", "type": "string", "display": true}
          ]
        },
        "options": {}
      },
      "name": "Guardar Tarea",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4.7,
      "position": [1220, 340],
      "credentials": {
        "googleSheetsOAuth2Api": {
          "id": "U9MmYhXUgVdOQej5",
          "name": "Google Sheets account"
        }
      }
    },
    {
      "parameters": {
        "respondWith": "json",
        "responseBody": "={ \"ok\": true }"
      },
      "name": "Respuesta OK",
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.5,
      "position": [1460, 340]
    }
  ],
  "connections": {
    "Webhook Crear": { "main": [[{ "node": "Validar Campos", "type": "main", "index": 0 }]] },
    "Validar Campos": { "main": [[{ "node": "Leer Tareas", "type": "main", "index": 0 }], [{ "node": "Error Validacion", "type": "main", "index": 0 }]] },
    "Leer Tareas": { "main": [[{ "node": "Generar Tarea", "type": "main", "index": 0 }]] },
    "Generar Tarea": { "main": [[{ "node": "Guardar Tarea", "type": "main", "index": 0 }]] },
    "Guardar Tarea": { "main": [[{ "node": "Respuesta OK", "type": "main", "index": 0 }]] }
  },
  "active": true,
  "settings": { "executionOrder": "v1" }
}
```

### 2.2 — Workflow: Marcar Hecha (reemplaza tareas-eliminar)

**Cambio clave**: en vez de borrar la fila, cambia `estado` a `"hecha"` y rellena `fecha_completada` con la fecha actual.

**Flujo:**
1. Webhook POST recibe: `{id}`
2. Lee tareas
3. Busca la tarea por id
4. Actualiza: `estado = "hecha"`, `fecha_completada = fechaHoy`
5. Responde `{ok: true}`

**Code node:**
```javascript
const idBuscado = $('Webhook Eliminar').first().json.body.id;
const filas = $input.all().map(item => item.json);
const tarea = filas.find(f => String(f.id).trim() === String(idBuscado).trim());

if (!tarea) {
  throw new Error('tarea_no_encontrada');
}

const hoy = new Date().toISOString().split('T')[0];

return [{
  json: {
    id: tarea.id,
    estado: 'hecha',
    fecha_completada: hoy
  }
}];
```

**Google Sheets Update node**: actualiza por matching column `id`, campos `estado` y `fecha_completada`.

**Importante**: El webhook `tareas-lista` DEBE filtrar `estado !== 'hecha'` en su Code node. Revisa que el workflow actual de listado ya haga este filtro. Si no, añade esta línea en su Code node:
```javascript
const tareasPendientes = todasLasTareas.filter(t => 
  String(t.estado || '').trim().toLowerCase() !== 'hecha'
);
```

### 2.3 — Workflow: Posponer mejorado (con motivo)

**Modificar** el webhook `tareas-posponer` existente para recibir: `{id, nueva_fecha, motivo}`

**Code node actualizado:**
```javascript
const idBuscado = $('Webhook Posponer').first().json.body.id;
const nuevaFecha = $('Webhook Posponer').first().json.body.nueva_fecha;
const motivo = $('Webhook Posponer').first().json.body.motivo || '';

const filas = $input.all().map(item => item.json);
const tarea = filas.find(f => String(f.id).trim() === String(idBuscado).trim());

if (!tarea) {
  throw new Error('tarea_no_encontrada');
}

const vecesActual = parseInt(tarea.veces_pospuesta) || 0;

return [{
  json: {
    id: tarea.id,
    fecha: nuevaFecha,
    motivo_posponer: motivo,
    veces_pospuesta: String(vecesActual + 1)
  }
}];
```

**Google Sheets Update**: matching por `id`, actualiza `fecha`, `motivo_posponer`, `veces_pospuesta`.

### 2.4 — Workflow: Lista de Compras (3 webhooks)

#### GET /compras-lista
Lee la pestaña `compras`, filtra `estado === "pendiente"`, devuelve JSON.

#### POST /compras-crear
Recibe `{item, cantidad, unidad, notas}`. Genera ID autoincremental. Append con `estado = "pendiente"`, `fecha_añadido = hoy`.

#### POST /compras-comprado
Recibe `{id}`. Actualiza `estado = "comprado"` en la fila con ese ID.

**Estos 3 se pueden hacer como un solo workflow con 3 webhooks y un Switch node**, o como 3 workflows separados (más simple).

### 2.5 — Workflow: Resumen Diario (Cron → Email)

**Cron**: todos los días a las 7:00 AM (después del cron de recurrentes a las 6:00).

**Flujo:**
1. Schedule Trigger a las 7:00
2. Leer pestaña `tareas` completa
3. Leer pestaña `compras` (solo pendientes)
4. Code node que genera el resumen:

```javascript
const tareas = $('Leer Tareas').all().map(item => item.json);
const compras = $('Leer Compras').all().map(item => item.json);

const hoy = new Date().toISOString().split('T')[0];

const pendientes = tareas.filter(t => 
  t.estado !== 'hecha' && t.fecha === hoy
);
const atrasadas = tareas.filter(t => 
  t.estado !== 'hecha' && t.fecha < hoy
);
const comprasPend = compras.filter(c => c.estado === 'pendiente');

// Formatear tareas por prioridad
function formatTarea(t) {
  const icons = {alta: '🔴', media: '🟡', baja: '🟢'};
  return `${icons[t.prioridad] || '⚪'} [${t.zona}] ${t.tarea}`;
}

let msg = `🌱 *Buenos días — Resumen CuttingsClones*\n`;
msg += `📅 ${hoy}\n\n`;

msg += `📋 *TAREAS HOY (${pendientes.length}):*\n`;
if (pendientes.length === 0) msg += `  ✅ No hay tareas para hoy\n`;
else pendientes.forEach(t => msg += `  ${formatTarea(t)}\n`);

msg += `\n⚠️ *ATRASADAS (${atrasadas.length}):*\n`;
if (atrasadas.length === 0) msg += `  ✅ Todo al día\n`;
else atrasadas.forEach(t => {
  const diasAtraso = Math.floor((new Date(hoy) - new Date(t.fecha)) / 86400000);
  msg += `  ❗ ${formatTarea(t)} (hace ${diasAtraso} días)\n`;
});

msg += `\n🛒 *COMPRAS PENDIENTES (${comprasPend.length}):*\n`;
if (comprasPend.length === 0) msg += `  ✅ Nada pendiente\n`;
else comprasPend.forEach(c => {
  msg += `  - ${c.item}${c.cantidad ? ' (' + c.cantidad + (c.unidad ? ' ' + c.unidad : '') + ')' : ''}\n`;
});

return [{ json: { mensaje: msg } }];
```

5. Send Email node (o Telegram node) con el contenido de `mensaje`.

**Para Gmail**: usa el node "Gmail" con tu cuenta OAuth ya conectada.
**Para Telegram**: 
  - Crea un bot con @BotFather
  - Usa el node "Telegram" con el token del bot y tu chat_id

### 2.6 — Workflow: Cron Recurrentes Mejorado (recurrencia avanzada)

**Reemplazar** el Code node "Filtrar y Generar" del workflow `Cron Tareas Recurrentes` con esta lógica:

```javascript
const dias = ['domingo', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado'];
const hoy = new Date();
const diaHoy = dias[hoy.getDay()];
const fechaHoy = hoy.toISOString().split('T')[0];
const diaDelMes = hoy.getDate();

const plantillas = $('Leer Plantillas').all().map(item => item.json);
const tareasExistentes = $('Leer Tareas Existentes').all().map(item => item.json);

function diasEntre(fecha1, fecha2) {
  if (!fecha1 || !fecha2) return 9999;
  return Math.floor((new Date(fecha2) - new Date(fecha1)) / 86400000);
}

const plantillasHoy = plantillas.filter(p => {
  const activa = String(p.activa || '').trim().toLowerCase();
  if (activa !== 'si') return false;
  
  const tipo = String(p.tipo_recurrencia || 'semanal').trim().toLowerCase();
  const config = String(p.config_recurrencia || p.dia_recurrencia || '').trim().toLowerCase();
  const ultimaGen = String(p.ultima_generada || '').trim();
  
  switch(tipo) {
    case 'semanal':
      return config === diaHoy;
    
    case 'quincenal':
      if (config !== diaHoy) return false;
      return diasEntre(ultimaGen, fechaHoy) >= 13; // 13 para dar margen
    
    case 'mensual':
      return parseInt(config) === diaDelMes;
    
    case 'cada_x_dias':
      const intervalo = parseInt(config);
      if (isNaN(intervalo) || intervalo <= 0) return false;
      return diasEntre(ultimaGen, fechaHoy) >= intervalo;
    
    default:
      // Compatibilidad: si no tiene tipo, tratar como semanal
      return config === diaHoy;
  }
});

if (plantillasHoy.length === 0) return [];

// Anti-duplicados
const nuevas = plantillasHoy.filter(p => {
  return !tareasExistentes.some(t => 
    String(t.tarea || '').trim().toLowerCase() === String(p.tarea || '').trim().toLowerCase()
    && String(t.zona || '').trim().toLowerCase() === String(p.zona || '').trim().toLowerCase()
    && String(t.fecha || '').trim() === fechaHoy
    && String(t.estado || '').trim().toLowerCase() !== 'hecha'
  );
});

if (nuevas.length === 0) return [];

let maxId = 0;
for (const t of tareasExistentes) {
  const id = parseInt(t.id);
  if (!isNaN(id) && id > maxId) maxId = id;
}

return nuevas.map((p, i) => ({
  json: {
    id: String(maxId + 1 + i),
    zona: p.zona || '',
    tarea: p.tarea || '',
    prioridad: p.prioridad || 'media',
    estado: 'pendiente',
    fecha: fechaHoy,
    recurrente: 'si',
    dia_recurrencia: p.dia_recurrencia || p.config_recurrencia || '',
    observaciones: p.observaciones || '',
    motivo_posponer: '',
    veces_pospuesta: '0',
    fecha_completada: ''
  }
}));
```

**Además**: después del node "Crear Tareas", añadir un nuevo node para actualizar `ultima_generada` en las plantillas. Esto requiere un segundo Google Sheets Update node que escriba `fechaHoy` en la columna `ultima_generada` de cada plantilla procesada.

---

## FASE 3: Actualizar el Frontend (index.html)

### 3.1 — Formulario "Añadir Tarea"

Añadir una nueva sección ANTES de la sección de tareas:

```html
<!-- CREAR TAREA -->
<section>
  <div class="section-header">
    <div class="section-icon">➕</div>
    <h2>Añadir tarea</h2>
  </div>
  <form id="formTarea">
    <div class="form-row">
      <div class="form-group">
        <label for="tarea-zona">Zona</label>
        <select id="tarea-zona" required>
          <option value="">Selecciona</option>
          <option value="madres">Madres</option>
          <option value="esquejes">Esquejes</option>
          <option value="floracion">Floración</option>
          <option value="limpieza">Limpieza</option>
          <option value="mantenimiento">Mantenimiento</option>
        </select>
      </div>
      <div class="form-group">
        <label for="tarea-prioridad">Prioridad</label>
        <select id="tarea-prioridad">
          <option value="media">Media</option>
          <option value="alta">Alta</option>
          <option value="baja">Baja</option>
        </select>
      </div>
    </div>
    <div class="form-row" style="margin-top:8px">
      <div class="form-group">
        <label for="tarea-nombre">Tarea</label>
        <input type="text" id="tarea-nombre" placeholder="Descripción de la tarea" required />
      </div>
      <div class="form-group" style="max-width:140px">
        <label for="tarea-fecha">Fecha</label>
        <input type="date" id="tarea-fecha" required />
      </div>
    </div>
    <div class="form-row" style="margin-top:8px">
      <div class="form-group">
        <label for="tarea-obs">Observaciones</label>
        <input type="text" id="tarea-obs" placeholder="Opcional" />
      </div>
      <button type="submit" class="btn btn-primary">Guardar</button>
    </div>
  </form>
  <div id="mensajeTarea" class="mensaje"></div>
</section>
```

**JavaScript para el formulario:**
```javascript
document.getElementById('tarea-fecha').value = fechaHoyISO();

document.getElementById('formTarea').addEventListener('submit', async function(e) {
  e.preventDefault();
  var msg = document.getElementById('mensajeTarea');
  msg.textContent = 'Guardando...';
  
  try {
    var res = await fetch(base_url + '/tareas-crear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        zona: document.getElementById('tarea-zona').value,
        tarea: document.getElementById('tarea-nombre').value,
        prioridad: document.getElementById('tarea-prioridad').value,
        fecha: document.getElementById('tarea-fecha').value,
        observaciones: document.getElementById('tarea-obs').value
      })
    });
    if (!res.ok) throw new Error('error');
    var data = await res.json();
    if (!data.ok) throw new Error('no ok');
    msg.textContent = 'Tarea creada correctamente';
    document.getElementById('tarea-nombre').value = '';
    document.getElementById('tarea-obs').value = '';
    await cargarTareas();
  } catch (e) {
    msg.textContent = 'Error al crear tarea';
  }
});
```

### 3.2 — Posponer con motivo (actualizar frontend)

Modificar el panel inline de posponer en `renderBloqueZona` para incluir campo de motivo:

Dentro del `posponer-panel`, ANTES del `posponer-custom`, añadir:
```html
<div class="form-group" style="margin-bottom:8px">
  <input type="text" id="motivo-{id}" placeholder="Motivo (opcional)" style="width:100%;font-size:12px;padding:6px 8px;background:white" />
</div>
```

Actualizar las funciones JavaScript:
```javascript
async function posponerTarea(id, fecha) {
  var motivoInput = document.getElementById('motivo-' + id);
  var motivo = motivoInput ? motivoInput.value : '';
  
  try {
    var res = await fetch(base_url + '/tareas-posponer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id, nueva_fecha: fecha, motivo: motivo })
    });
    if (!res.ok) throw new Error('error');
    var data = await res.json();
    if (!data.ok) throw new Error('no ok');
    await cargarTareas();
  } catch (e) {
    alert('No se pudo posponer la tarea');
  }
}
```

### 3.3 — Sección Lista de Compras

Añadir nueva sección después de tareas:

```html
<!-- LISTA DE COMPRAS -->
<section>
  <div class="section-header">
    <div class="section-icon">🛒</div>
    <h2>Lista de compras</h2>
  </div>
  <form id="formCompra" class="form-row">
    <div class="form-group">
      <input type="text" id="compra-item" placeholder="Artículo" required />
    </div>
    <div class="form-group" style="max-width:80px">
      <input type="text" id="compra-cantidad" placeholder="Cant." />
    </div>
    <div class="form-group" style="max-width:80px">
      <input type="text" id="compra-unidad" placeholder="Ud." />
    </div>
    <button type="submit" class="btn btn-primary">+</button>
  </form>
  <div id="listaCompras" class="cargando" style="margin-top:10px">Cargando...</div>
</section>
```

**JavaScript:**
```javascript
async function cargarCompras() {
  var contenedor = document.getElementById('listaCompras');
  try {
    var res = await fetch(base_url + '/compras-lista');
    if (!res.ok) throw new Error('error');
    var data = await res.json();
    var items = data.items || [];
    
    if (items.length === 0) {
      contenedor.innerHTML = '<p class="sin-datos">Lista vacía</p>';
      return;
    }
    
    var html = '';
    for (var i = 0; i < items.length; i++) {
      var c = items[i];
      html += '<div class="tarea-card" style="display:flex;align-items:center;gap:8px">';
      html += '<button class="btn btn-done btn-sm" onclick="marcarComprado(\'' + escapeAttr(c.id) + '\')" style="flex:none">✓</button>';
      html += '<span style="flex:1;font-size:13px"><strong>' + escapeHtml(c.item) + '</strong>';
      if (c.cantidad) html += ' — ' + escapeHtml(c.cantidad) + (c.unidad ? ' ' + escapeHtml(c.unidad) : '');
      html += '</span>';
      html += '</div>';
    }
    contenedor.innerHTML = html;
  } catch (e) {
    contenedor.innerHTML = '<p class="error">Error al cargar</p>';
  }
}

async function marcarComprado(id) {
  try {
    var res = await fetch(base_url + '/compras-comprado', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id })
    });
    if (!res.ok) throw new Error('error');
    await cargarCompras();
  } catch (e) {
    alert('Error al marcar como comprado');
  }
}

document.getElementById('formCompra').addEventListener('submit', async function(e) {
  e.preventDefault();
  try {
    var res = await fetch(base_url + '/compras-crear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item: document.getElementById('compra-item').value,
        cantidad: document.getElementById('compra-cantidad').value,
        unidad: document.getElementById('compra-unidad').value
      })
    });
    if (!res.ok) throw new Error('error');
    document.getElementById('compra-item').value = '';
    document.getElementById('compra-cantidad').value = '';
    document.getElementById('compra-unidad').value = '';
    await cargarCompras();
  } catch (e) {
    alert('Error al añadir');
  }
});

// Añadir cargarCompras() al init
```

En la sección `// ── INIT ──` añadir:
```javascript
cargarCompras();
```

### 3.4 — Filtros de tareas (frontend)

Añadir botones de filtro justo antes de `contenedorTareas`:

```html
<div id="filtrosTareas" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
  <button class="btn btn-sm btn-primary" onclick="filtrarTareas('todas')">Todas</button>
  <button class="btn btn-sm btn-done" onclick="filtrarTareas('hoy')">Hoy</button>
  <button class="btn btn-sm btn-postpone" onclick="filtrarTareas('atrasadas')">Atrasadas</button>
  <button class="btn btn-sm" style="background:#eee" onclick="filtrarTareas('alta')">🔴 Alta</button>
</div>
```

**JavaScript:**
```javascript
var todasLasTareasCache = {};

// Modificar cargarTareas para cachear los datos:
async function cargarTareas() {
  var contenedor = document.getElementById('contenedorTareas');
  try {
    var res = await fetch(base_url + '/tareas-lista');
    if (!res.ok) throw new Error('error');
    var data = await res.json();
    todasLasTareasCache = data.items_por_zona || {};
    renderTareasFiltradas('todas');
  } catch (e) {
    contenedor.className = 'error';
    contenedor.textContent = 'Error al cargar tareas';
  }
}

function renderTareasFiltradas(filtro) {
  var contenedor = document.getElementById('contenedorTareas');
  var hoy = fechaHoyISO();
  var zonas = ['madres', 'esquejes', 'floracion', 'limpieza', 'mantenimiento'];
  
  var datosFiltrados = {};
  for (var i = 0; i < zonas.length; i++) {
    var z = zonas[i];
    var tareas = todasLasTareasCache[z] || [];
    
    if (filtro === 'hoy') {
      tareas = tareas.filter(function(t) { return t.fecha === hoy; });
    } else if (filtro === 'atrasadas') {
      tareas = tareas.filter(function(t) { return t.fecha < hoy; });
    } else if (filtro === 'alta' || filtro === 'media' || filtro === 'baja') {
      tareas = tareas.filter(function(t) { return t.prioridad === filtro; });
    }
    
    datosFiltrados[z] = tareas;
  }
  
  contenedor.className = 'tareas-grid';
  var html = '';
  for (var i = 0; i < zonas.length; i++) {
    html += renderBloqueZona(zonas[i], datosFiltrados[zonas[i]]);
  }
  contenedor.innerHTML = html;
}

function filtrarTareas(filtro) {
  renderTareasFiltradas(filtro);
}
```

---

## FASE 4: Panel de Administración (admin.html)

Crear un segundo HTML `admin.html` con funcionalidades extra para el gestor:

### Secciones del admin:
1. **Dashboard rápido**: conteo de tareas pendientes, atrasadas, completadas hoy
2. **Gestión de tareas**: vista tabla completa con todos los estados + filtros
3. **Crear tarea** (mismo formulario que landing)
4. **Gestión de plantillas recurrentes**: crear/editar/desactivar plantillas con la nueva recurrencia avanzada
5. **Historial**: ver tareas completadas con fechas
6. **Lista de compras** con gestión completa
7. **Estadísticas**: tareas completadas por semana, zonas con más carga, etc.

Este archivo usa los MISMOS webhooks. No necesita backends nuevos (solo algún webhook adicional para leer historial y plantillas).

### Webhooks adicionales necesarios para admin:
- `GET /tareas-todas` → devuelve TODAS las tareas (incluidas hechas), para el panel admin
- `GET /tareas-recurrentes-lista` → devuelve las plantillas recurrentes
- `POST /tareas-recurrentes-crear` → crea nueva plantilla recurrente
- `POST /tareas-recurrentes-editar` → edita plantilla existente
- `GET /historial-lista` → lee la pestaña historial_tareas

---

## RESUMEN DE ORDEN DE EJECUCIÓN

1. **FASE 1**: Modificar Google Sheets (añadir columnas y pestañas) — Usar api_script.js
2. **FASE 2**: Crear/modificar workflows en n8n — Importar JSONs o crear manualmente
3. **FASE 3**: Actualizar index.html con nuevas secciones y funcionalidades
4. **FASE 4**: Crear admin.html (opcional, segunda iteración)

---

## NOTAS PARA CLAUDE CODE

- El spreadsheetId es: `17_jk3kGPB9ukeMbhFhwgJyO3OpbWo0MY6T8ZajN7aNI`
- La base_url de webhooks es: `https://primary-production-2cf7.up.railway.app/webhook`
- Las credenciales de Google Sheets en n8n usan el ID: `U9MmYhXUgVdOQej5`
- Las zonas son fijas: madres, esquejes, floracion, limpieza, mantenimiento
- Todo el frontend es vanilla JS (no React, no frameworks)
- El CSS usa variables CSS definidas en :root
- Los IDs de pestaña conocidos: tareas=1404161276, tareas_recurrentes=1626272047
