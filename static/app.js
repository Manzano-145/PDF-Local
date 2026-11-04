'use strict';

const TOOLS = {
  merge: {
    icon: '🧩', title: 'Unir archivos PDF', button: 'Unir PDF', multiple: true,
    desc: 'Une PDFs y ponlos en el orden que prefieras. ¡Rápido y fácil!',
  },
  split: {
    icon: '✂️', title: 'Dividir PDF', button: 'Dividir PDF', multiple: false,
    desc: 'Extrae una o varias páginas de tu PDF o convierte cada página del PDF en un archivo PDF independiente.',
  },
  unlock: {
    icon: '🔓', title: 'Desbloquear PDF', button: 'Desbloquear PDF', multiple: false,
    desc: 'Quita la contraseña de los PDF y los desbloquea, así podrás usarlos para lo que quieras.',
  },
  protect: {
    icon: '🔒', title: 'Proteger PDF', button: 'Proteger PDF', multiple: false,
    desc: 'Protege PDF con contraseña para salvaguardar información confidencial.',
  },
  organize: {
    icon: '🗂️', title: 'Ordenar PDF', button: 'Guardar cambios', multiple: true,
    desc: 'Ordena, añade y elimina páginas PDF. Arrastra y suelta las miniaturas de página y ordénalas como quieras.',
  },
  markdown: {
    icon: '📝', title: 'PDF a Markdown', button: 'Convertir a Markdown', multiple: true,
    desc: 'Extrae todo el texto del PDF, incluidas tablas, títulos y listas, en un archivo .md liviano y listo para usar como contexto en un chat de IA.',
  },
};

const $ = (selector, root = document) => root.querySelector(selector);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'className') node.className = value;
    else if (value !== false && value != null) node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child != null) node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

// ---------- State ----------

let keySeq = 0;
const nextKey = () => String(++keySeq);

const state = {
  tool: null,
  files: [],          // { key, name, file, password, thumbs, count }
  pages: [],          // organize: { key, fileKey, page, rotate, blank }
  selected: new Set(), // split: selected zero-based page indexes
  splitMode: 'ranges',
  ranges: '',
  advancedLayout: false,
  busy: false,
};

// ---------- API ----------

class ApiError extends Error {
  constructor(message, code) { super(message); this.code = code; }
}

async function api(path, formData, expect = 'blob') {
  const response = await fetch(path, { method: 'POST', body: formData });
  if (!response.ok) {
    let body = {};
    try { body = await response.json(); } catch { /* non-JSON error */ }
    throw new ApiError(body.error || `Error ${response.status}`, body.code);
  }
  if (expect === 'json') return response.json();
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/);
  return { blob: await response.blob(), name: match ? match[1] : 'resultado.pdf' };
}

function download({ blob, name }) {
  const url = URL.createObjectURL(blob);
  const link = el('a', { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const isPasswordError = (error) => error instanceof ApiError && ['password_required', 'wrong_password'].includes(error.code);

function askPassword(fileName, message) {
  const dialog = $('#password-dialog');
  const input = $('#password-input');
  $('#password-message').textContent = `${fileName}: ${message}`;
  input.value = '';
  dialog.showModal();
  input.focus();
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => {
      resolve(dialog.returnValue === 'ok' && input.value ? input.value : null);
    }, { once: true });
  });
}

/** Run `action(entry)`; if the PDF needs a password, ask for it and retry. */
async function withPassword(entry, action) {
  for (;;) {
    try {
      return await action(entry);
    } catch (error) {
      if (!isPasswordError(error)) throw error;
      const password = await askPassword(entry.name, error.message);
      if (password === null) throw new ApiError('Operación cancelada: falta la contraseña.', 'cancelled');
      entry.password = password;
    }
  }
}

async function loadThumbs(entry, limit) {
  const result = await withPassword(entry, () => {
    const form = new FormData();
    form.append('files', entry.file);
    if (entry.password) form.append('password', entry.password);
    if (limit) form.append('limit', limit);
    return api('/api/thumbnails', form, 'json');
  });
  entry.thumbs = result.pages;
  entry.count = result.count;
}

// ---------- Navigation ----------

function showHome() {
  state.tool = null;
  $('#home').hidden = false;
  $('#tool').hidden = true;
}

function openTool(id) {
  const tool = TOOLS[id];
  Object.assign(state, { tool: id, files: [], pages: [], selected: new Set(), splitMode: 'ranges', ranges: '', busy: false });
  $('#home').hidden = true;
  $('#tool').hidden = false;
  $('#tool-title').textContent = tool.title;
  $('#tool-desc').textContent = tool.desc;
  $('#file-input').multiple = tool.multiple;
  $('#run').textContent = tool.button;
  setStatus('');
  render();
}

function setStatus(text, isError = false) {
  const status = $('#status');
  status.textContent = text;
  status.classList.toggle('error', isError);
}

// ---------- File intake ----------

async function addFiles(fileList) {
  const pdfs = [...fileList].filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
  if (!pdfs.length) return setStatus('Solo se aceptan archivos PDF.', true);
  const tool = state.tool;
  const incoming = TOOLS[tool].multiple ? pdfs : pdfs.slice(0, 1);
  if (!TOOLS[tool].multiple) { state.files = []; state.pages = []; state.selected.clear(); state.ranges = ''; }

  setStatus('Procesando…');
  for (const file of incoming) {
    const entry = { key: nextKey(), name: file.name, file, password: null, thumbs: [], count: 0 };
    try {
      if (tool === 'merge') await loadThumbs(entry, 1);
      if (tool === 'split' || tool === 'organize') await loadThumbs(entry);
    } catch (error) {
      setStatus(`${file.name}: ${error.message}`, true);
      continue;
    }
    if (state.tool !== tool) return; // user navigated away meanwhile
    state.files.push(entry);
    if (tool === 'organize') {
      for (let page = 0; page < entry.count; page++) {
        state.pages.push({ key: nextKey(), fileKey: entry.key, page, rotate: 0, blank: false });
      }
    }
    render();
  }
  if (!$('#status').classList.contains('error')) setStatus('');
}

// ---------- Drag & drop reordering ----------

function makeSortable(container, onReorder) {
  let dragged = null;
  container.addEventListener('dragstart', (event) => {
    dragged = event.target.closest('[data-key]');
    if (!dragged) return;
    dragged.classList.add('dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', dragged.dataset.key);
  });
  container.addEventListener('dragover', (event) => {
    if (!dragged) return;
    event.preventDefault();
    const target = event.target.closest('[data-key]');
    if (!target || target === dragged) return;
    const rect = target.getBoundingClientRect();
    const after = event.clientX - rect.left > rect.width / 2;
    container.insertBefore(dragged, after ? target.nextSibling : target);
  });
  container.addEventListener('drop', (event) => { if (dragged) event.preventDefault(); });
  container.addEventListener('dragend', () => {
    dragged?.classList.remove('dragging');
    dragged = null;
    onReorder([...container.querySelectorAll('[data-key]')].map((node) => node.dataset.key));
  });
}

const reorderBy = (items, keys) => keys.map((key) => items.find((item) => item.key === key));

// ---------- Rendering ----------

function render() {
  const workspace = $('#workspace');
  workspace.replaceChildren();
  const hasFiles = state.files.length > 0;

  const dropzone = $('#dropzone');
  dropzone.classList.toggle('compact', hasFiles);
  $('#drop-label').textContent = hasFiles
    ? (TOOLS[state.tool].multiple ? 'Añadir más PDFs' : 'Cambiar archivo')
    : (TOOLS[state.tool].multiple ? 'Seleccionar archivos PDF' : 'Seleccionar archivo PDF');
  $('#actions').hidden = !hasFiles;

  if (!hasFiles) return;
  const renderers = {
    merge: renderMerge, split: renderSplit, unlock: renderUnlock, protect: renderProtect, organize: renderOrganize, markdown: renderMarkdown,
  };
  renderers[state.tool](workspace);
}

function thumbImage(src, rotate = 0) {
  const img = el('img', { src, alt: '' });
  if (rotate) img.style.transform = `rotate(${rotate}deg)`;
  return img;
}

function fileTile(entry, { removable = true, sortable = false } = {}) {
  const pages = entry.count ? ` · ${entry.count} pág.` : '';
  return el('div', { className: 'tile', 'data-key': sortable ? entry.key : null, draggable: sortable ? 'true' : null, title: entry.name },
    removable && el('div', { className: 'tile-actions' },
      el('button', { title: 'Quitar', onclick: () => { removeFile(entry.key); } }, '✕')),
    el('div', { className: 'thumb' }, entry.thumbs[0] ? thumbImage(entry.thumbs[0]) : el('div', { className: 'blank' })),
    el('div', { className: 'caption' }, entry.name + pages),
  );
}

function removeFile(key) {
  state.files = state.files.filter((f) => f.key !== key);
  state.pages = state.pages.filter((p) => p.fileKey !== key);
  state.selected.clear();
  render();
}

function renderMerge(workspace) {
  const grid = el('div', { className: 'grid' }, state.files.map((f) => fileTile(f, { sortable: true })));
  makeSortable(grid, (keys) => { state.files = reorderBy(state.files, keys); });
  workspace.append(
    el('p', { className: 'hint' }, 'Arrastrá los archivos para cambiar el orden en que se unirán.'),
    grid,
  );
}

function compressRanges(indexes) {
  const sorted = [...indexes].sort((a, b) => a - b).map((i) => i + 1);
  const parts = [];
  for (let i = 0; i < sorted.length; i++) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    parts.push(i === j ? `${sorted[i]}` : `${sorted[i]}-${sorted[j]}`);
    i = j;
  }
  return parts.join(', ');
}

function renderSplit(workspace) {
  const entry = state.files[0];
  const rangesInput = el('input', { type: 'text', id: 'ranges', placeholder: 'Ej: 1-3, 5, 8-10', value: state.ranges });
  rangesInput.addEventListener('input', () => { state.ranges = rangesInput.value; });

  const modeOption = (value, label) => {
    const radio = el('input', { type: 'radio', name: 'split-mode', value, checked: state.splitMode === value });
    radio.addEventListener('change', () => { state.splitMode = value; render(); });
    return el('label', {}, radio, label);
  };

  const grid = el('div', { className: 'grid' }, entry.thumbs.map((src, index) =>
    el('div', {
      className: `tile clickable${state.selected.has(index) ? ' selected' : ''}`,
      onclick: () => {
        state.selected.has(index) ? state.selected.delete(index) : state.selected.add(index);
        state.ranges = compressRanges(state.selected);
        if (state.splitMode === 'each') state.splitMode = 'extract';
        render();
      },
    },
    el('div', { className: 'thumb' }, thumbImage(src)),
    el('div', { className: 'caption' }, `Página ${index + 1}`))));

  workspace.append(
    el('div', { className: 'panel' },
      el('strong', {}, `${entry.name} · ${entry.count} páginas`),
      modeOption('ranges', 'Dividir por rangos (un PDF por cada rango)'),
      modeOption('extract', 'Extraer páginas seleccionadas en un solo PDF'),
      modeOption('each', 'Convertir cada página en un PDF independiente'),
      state.splitMode !== 'each' && rangesInput,
      el('p', { className: 'hint' }, 'Podés escribir los rangos o hacer clic en las miniaturas para seleccionar páginas. Varios PDFs se descargan en un .zip.'),
      el('button', { className: 'secondary', onclick: () => removeFile(entry.key) }, 'Quitar archivo'),
    ),
    grid,
  );
}

function renderUnlock(workspace) {
  const entry = state.files[0];
  workspace.append(
    fileTile(entry),
    el('div', { className: 'panel' },
      el('label', { for: 'unlock-password' }, 'Contraseña actual del PDF'),
      el('input', { type: 'password', id: 'unlock-password', autocomplete: 'off', placeholder: 'Contraseña' }),
      el('p', { className: 'hint' }, 'Se genera una copia sin contraseña ni restricciones.'),
    ),
  );
}

function renderProtect(workspace) {
  const entry = state.files[0];
  workspace.append(
    fileTile(entry),
    el('div', { className: 'panel' },
      el('label', { for: 'new-password' }, 'Nueva contraseña'),
      el('input', { type: 'password', id: 'new-password', autocomplete: 'new-password' }),
      el('label', { for: 'confirm-password' }, 'Repetir contraseña'),
      el('input', { type: 'password', id: 'confirm-password', autocomplete: 'new-password' }),
      el('p', { className: 'hint' }, 'Cifrado AES-256. Si olvidás la contraseña no hay forma de recuperar el contenido.'),
    ),
  );
}

function renderOrganize(workspace) {
  const filesByKey = Object.fromEntries(state.files.map((f) => [f.key, f]));
  const fileNumber = Object.fromEntries(state.files.map((f, i) => [f.key, i + 1]));
  const multipleFiles = state.files.length > 1;

  const pageTile = (page) => {
    const entry = filesByKey[page.fileKey];
    const caption = page.blank
      ? 'Página en blanco'
      : `${multipleFiles ? `Archivo ${fileNumber[page.fileKey]} · ` : ''}Página ${page.page + 1}`;
    return el('div', { className: 'tile', draggable: 'true', 'data-key': page.key, title: entry ? entry.name : '' },
      el('div', { className: 'tile-actions' },
        !page.blank && el('button', { title: 'Rotar', onclick: () => { page.rotate = (page.rotate + 90) % 360; render(); } }, '↻'),
        el('button', { title: 'Eliminar página', onclick: () => { state.pages = state.pages.filter((p) => p !== page); render(); } }, '✕')),
      el('div', { className: 'thumb' }, page.blank ? el('div', { className: 'blank' }) : thumbImage(entry.thumbs[page.page], page.rotate)),
      el('div', { className: 'caption' }, caption),
    );
  };

  const grid = el('div', { className: 'grid' }, state.pages.map(pageTile));
  makeSortable(grid, (keys) => { state.pages = reorderBy(state.pages, keys); });

  workspace.append(
    el('div', { className: 'toolbar' },
      el('button', { className: 'secondary', onclick: () => { state.pages.push({ key: nextKey(), blank: true, rotate: 0 }); render(); } }, '＋ Página en blanco'),
      el('button', { className: 'secondary', onclick: () => $('#file-input').click() }, '＋ Añadir páginas de otro PDF'),
      el('button', { className: 'secondary', onclick: () => openTool('organize') }, 'Empezar de nuevo'),
    ),
    el('p', { className: 'hint' }, `${state.pages.length} páginas en el documento final. Arrastrá las miniaturas para reordenarlas.`),
    grid,
  );
}

const mdFileName = (pdfName) => pdfName.replace(/\.pdf$/i, '') + '.md';
const markdownBlob = (text) => new Blob([text], { type: 'text/markdown;charset=utf-8' });

async function copyText(text, button) {
  await navigator.clipboard.writeText(text);
  const label = button.textContent;
  button.textContent = '✓ Copiado';
  setTimeout(() => { button.textContent = label; }, 1500);
}

function renderMarkdown(workspace) {
  const converted = state.files.filter((f) => f.markdown);
  const pending = state.files.filter((f) => !f.markdown);

  if (pending.length) {
    const checkbox = el('input', { type: 'checkbox', checked: state.advancedLayout });
    checkbox.addEventListener('change', () => { state.advancedLayout = checkbox.checked; });
    workspace.append(
      el('div', { className: 'grid' }, pending.map((f) => fileTile(f))),
      el('div', { className: 'panel' },
        el('label', {}, checkbox, 'Análisis de diseño avanzado'),
        el('p', { className: 'hint' }, 'Úsalo si el resultado sale desordenado: mejora PDFs con varias columnas o tablas sin bordes, pero es mucho más lento.')),
    );
  }

  if (converted.length > 1) {
    const combined = converted.map((f) => f.markdown).join('\n\n---\n\n');
    workspace.append(el('div', { className: 'toolbar' },
      el('button', { className: 'secondary', onclick: (event) => copyText(combined, event.currentTarget) }, '📋 Copiar todo'),
      el('button', { className: 'secondary', onclick: () => download({ blob: markdownBlob(combined), name: 'documentos.md' }) }, '⬇ Descargar todo en un .md')));
  }

  for (const entry of converted) {
    const tokens = Math.round(entry.markdown.length / 4);
    const pdfSize = (entry.file.size / 1024).toFixed(0);
    const mdSize = (markdownBlob(entry.markdown).size / 1024).toFixed(0);
    workspace.append(el('div', { className: 'panel wide' },
      el('div', { className: 'panel-head' },
        el('strong', {}, entry.name),
        el('button', { className: 'secondary', title: 'Quitar', onclick: () => removeFile(entry.key) }, '✕')),
      el('p', { className: 'hint' },
        `${entry.pages} páginas · PDF ${pdfSize} KB → Markdown ${mdSize} KB · ~${tokens.toLocaleString('es')} tokens (estimado)`),
      entry.emptyPages.length > 0 && el('p', { className: 'warning' },
        `⚠ Páginas sin texto extraíble (probablemente escaneadas): ${entry.emptyPages.join(', ')}. Su contenido no aparece en el .md.`),
      el('textarea', { className: 'preview', readonly: true, spellcheck: 'false' }, entry.markdown),
      el('div', { className: 'toolbar' },
        el('button', { className: 'secondary', onclick: (event) => copyText(entry.markdown, event.currentTarget) }, '📋 Copiar'),
        el('button', { className: 'secondary', onclick: () => download({ blob: markdownBlob(entry.markdown), name: mdFileName(entry.name) }) }, '⬇ Descargar .md'))));
  }
}

// ---------- Actions ----------

function filesForm(entries) {
  const form = new FormData();
  entries.forEach((entry) => form.append('files', entry.file));
  form.append('passwords', JSON.stringify(entries.map((entry) => entry.password)));
  return form;
}

const runners = {
  async merge() {
    if (state.files.length < 2) throw new Error('Añadí al menos dos PDFs.');
    return api('/api/merge', filesForm(state.files));
  },

  async split() {
    const entry = state.files[0];
    const form = filesForm([entry]);
    form.append('mode', state.splitMode);
    form.append('ranges', state.ranges || '');
    if (entry.password) form.append('password', entry.password);
    return api('/api/split', form);
  },

  async unlock() {
    const entry = state.files[0];
    const password = $('#unlock-password').value;
    if (!password) throw new Error('Ingresá la contraseña actual del PDF.');
    const form = filesForm([entry]);
    form.append('password', password);
    return api('/api/unlock', form);
  },

  async protect() {
    const newPassword = $('#new-password').value;
    if (!newPassword) throw new Error('Ingresá una contraseña.');
    if (newPassword !== $('#confirm-password').value) throw new Error('Las contraseñas no coinciden.');
    // An already-protected PDF needs its current password first.
    return withPassword(state.files[0], (entry) => {
      const form = filesForm([entry]);
      form.append('new_password', newPassword);
      if (entry.password) form.append('password', entry.password);
      return api('/api/protect', form);
    });
  },

  async organize() {
    if (!state.pages.length) throw new Error('El documento no tiene páginas.');
    const fileIndex = Object.fromEntries(state.files.map((f, i) => [f.key, i]));
    const pages = state.pages.map((p) => (p.blank
      ? { blank: true }
      : { file: fileIndex[p.fileKey], page: p.page, rotate: p.rotate }));
    const form = filesForm(state.files);
    form.append('pages', JSON.stringify(pages));
    return api('/api/organize', form);
  },

  async markdown() {
    // One request per file so each protected PDF can ask for its own password.
    for (const [index, entry] of state.files.entries()) {
      if (entry.markdown) continue;
      setStatus(`Convirtiendo ${index + 1} de ${state.files.length}: ${entry.name}…`);
      const result = await withPassword(entry, () => {
        const form = filesForm([entry]);
        form.append('advanced_layout', state.advancedLayout);
        return api('/api/markdown', form, 'json');
      });
      const { markdown, pages, empty_pages: emptyPages } = result.files[0];
      Object.assign(entry, { markdown, pages, emptyPages });
      render();
    }
    return null; // results are shown on screen instead of downloaded
  },
};

async function run() {
  if (state.busy) return;
  state.busy = true;
  $('#run').disabled = true;
  setStatus('Procesando…');
  try {
    const result = await runners[state.tool]();
    if (result) download(result);
    setStatus(result ? '¡Listo! El archivo se descargó.' : '¡Listo!');
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.busy = false;
    $('#run').disabled = false;
  }
}

// ---------- Wiring ----------

function init() {
  const grid = $('#tool-grid');
  for (const [id, tool] of Object.entries(TOOLS)) {
    grid.append(el('div', { className: 'tool-card', onclick: () => openTool(id) },
      el('div', { className: 'icon' }, tool.icon),
      el('h3', {}, tool.title),
      el('p', {}, tool.desc)));
  }

  $('#home-link').addEventListener('click', (event) => { event.preventDefault(); showHome(); });
  $('#back').addEventListener('click', showHome);
  $('#run').addEventListener('click', run);

  const input = $('#file-input');
  input.addEventListener('change', () => { addFiles(input.files); input.value = ''; });

  const dropzone = $('#dropzone');
  const hasFiles = (event) => event.dataTransfer && [...event.dataTransfer.types].includes('Files');
  dropzone.addEventListener('dragover', (event) => { if (hasFiles(event)) { event.preventDefault(); dropzone.classList.add('over'); } });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('over'));
  dropzone.addEventListener('drop', (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dropzone.classList.remove('over');
    addFiles(event.dataTransfer.files);
  });
  // Keep the browser from opening a PDF dropped outside the drop zone.
  window.addEventListener('dragover', (event) => { if (hasFiles(event)) event.preventDefault(); });
  window.addEventListener('drop', (event) => { if (hasFiles(event)) event.preventDefault(); });
}

init();
