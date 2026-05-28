(() => {
  const form = document.querySelector('[data-label-designer-form]');
  if (!form) return;

  const root = form.querySelector('[data-label-preview-root]');
  const stage = form.querySelector('[data-label-designer-stage]');
  const sheet = form.querySelector('[data-preview-sheet]');
  const content = form.querySelector('[data-preview-content]');
  const list = form.querySelector('.label-element-list');
  if (!root || !stage || !sheet || !content || !list) return;

  const emptyTpl = form.querySelector('[data-empty-element-form]');
  const totalForms = form.querySelector('#id_elements-TOTAL_FORMS');
  const addBtn = form.querySelector('[data-add-custom-text]');
  const sizeBadge = form.querySelector('[data-label-size]');
  const mmSize = form.querySelector('[data-preview-mm-size]');
  const summary = form.querySelector('[data-selected-element-summary]');

  const widthInput = form.querySelector('[name="width_mm"]');
  const heightInput = form.querySelector('[name="height_mm"]');
  const gridToggle = form.querySelector('[data-grid-toggle]');
  const zoomValue = form.querySelector('[data-label-zoom-value]');
  const zoomIn = form.querySelector('[data-label-zoom-in]');
  const zoomOut = form.querySelector('[data-label-zoom-out]');
  const zoomFit = form.querySelector('[data-label-zoom-fit]');
  const resetBtn = form.querySelector('[data-reset-layout]');
  const optimizeBtn = form.querySelector('[data-optimize-layout]');

  const defaults = {
    item_name: { x: 3, y: 3, width: 52, height: 6 },
    internal_code: { x: 3, y: 10, width: 52, height: 5 },
    barcode: { x: 3, y: 17, width: 52, height: 14 },
    barcode_text: { x: 3, y: 33, width: 52, height: 5 },
    custom_text: { x: 3, y: 3, width: 25, height: 6 },
  };

  const map = new Map();
  let selectedKey = null;
  let zoom = 1;
  const pxBase = 4.2;

  const toN = (v, d = 0) => {
    const n = parseFloat(String(v || '').replace(',', '.'));
    return Number.isFinite(n) ? n : d;
  };
  const pxPerMm = () => pxBase * zoom;
  const keyOf = (row) => row.dataset.formIndex || row.dataset.elementType;
  const isVisible = (row) => row.querySelector('[name$="-is_visible"]')?.checked && !row.querySelector('[name$="-DELETE"]')?.checked;

  const elementText = (type, row) => ({
    item_name: 'Дріт оцинкований Ø3 мм',
    internal_code: 'Код: YT-000001',
    barcode_text: '4820000000012',
    custom_text: row.querySelector('[name$="-text"]')?.value || 'Текст',
  }[type] || '');

  const buildEl = (row) => {
    const key = keyOf(row);
    if (map.has(key)) return map.get(key);
    const type = row.dataset.elementType;
    const el = document.createElement('div');
    el.dataset.labelElement = type;
    el.dataset.formIndex = row.dataset.formIndex;
    el.tabIndex = 0;
    el.className = type === 'barcode' ? 'label-preview-barcode' : 'label-preview-field';
    if (type === 'barcode') el.innerHTML = '<span class="label-element-hitbox" aria-hidden="true"></span>';
    content.appendChild(el);
    map.set(key, el);
    return el;
  };

  const updateSheet = () => {
    const width = Math.max(20, toN(widthInput?.value, 58));
    const height = Math.max(20, toN(heightInput?.value, 40));
    sheet.style.width = `${width * pxPerMm()}px`;
    sheet.style.height = `${height * pxPerMm()}px`;
    content.style.position = 'relative';
    content.style.width = '100%';
    content.style.height = '100%';
    if (sizeBadge) sizeBadge.textContent = `${width} × ${height} мм`;
    if (mmSize) mmSize.textContent = `Розмір етикетки: ${width} × ${height} мм`;
    if (zoomValue) zoomValue.textContent = `${Math.round(zoom * 100)}%`;
  };

  const syncRow = (row) => {
    const type = row.dataset.elementType;
    const el = buildEl(row);
    const p = defaults[type] || defaults.custom_text;
    const x = toN(row.querySelector('[name$="-x_mm"]')?.value, p.x);
    const y = toN(row.querySelector('[name$="-y_mm"]')?.value, p.y);
    const w = Math.max(1, toN(row.querySelector('[name$="-width_mm"]')?.value, p.width));
    const h = Math.max(1, toN(row.querySelector('[name$="-height_mm"]')?.value, p.height));

    Object.assign(el.style, {
      position: 'absolute',
      left: `${x * pxPerMm()}px`,
      top: `${y * pxPerMm()}px`,
      width: `${w * pxPerMm()}px`,
      height: `${h * pxPerMm()}px`,
      display: isVisible(row) ? '' : 'none',
      fontSize: `${Math.max(6, toN(row.querySelector('[name$="-font_size"]')?.value, 8)) * zoom}px`,
      lineHeight: '1.15',
    });

    if (type !== 'barcode') {
      el.textContent = elementText(type, row);
      el.classList.toggle('label-preview-barcode-text', type === 'barcode_text');
      el.classList.toggle('label-preview-item-name', type === 'item_name');
      el.classList.toggle('label-preview-internal-code', type === 'internal_code');
    }
  };

  const sync = () => {
    updateSheet();
    form.querySelectorAll('[data-element-form]').forEach(syncRow);
  };

  const select = (row) => {
    selectedKey = keyOf(row);
    form.querySelectorAll('[data-element-form]').forEach((r) => r.classList.toggle('is-selected', keyOf(r) === selectedKey));
    map.forEach((el, key) => el.classList.toggle('is-selected', key === selectedKey));
    if (summary) {
      const x = row.querySelector('[name$="-x_mm"]')?.value || '0';
      const y = row.querySelector('[name$="-y_mm"]')?.value || '0';
      const w = row.querySelector('[name$="-width_mm"]')?.value || '0';
      const h = row.querySelector('[name$="-height_mm"]')?.value || '0';
      summary.textContent = `${row.dataset.elementType}: x=${x} мм, y=${y} мм, w=${w} мм, h=${h} мм`;
    }
  };

  const wireRow = (row) => {
    if (!row.dataset.formIndex) row.dataset.formIndex = String(Array.from(form.querySelectorAll('[data-element-form]')).indexOf(row));
    buildEl(row);
    row.addEventListener('click', () => select(row));
    row.addEventListener('input', () => syncRow(row));
  };

  const applyDefaultLayout = () => {
    form.querySelectorAll('[data-element-form]').forEach((row) => {
      const type = row.dataset.elementType;
      const d = defaults[type];
      if (!d) return;
      const set = (s, v) => { const n = row.querySelector(s); if (n) n.value = String(v); };
      set('[name$="-x_mm"]', d.x.toFixed(2));
      set('[name$="-y_mm"]', d.y.toFixed(2));
      set('[name$="-width_mm"]', d.width.toFixed(2));
      set('[name$="-height_mm"]', d.height.toFixed(2));
      const del = row.querySelector('[name$="-DELETE"]'); if (del) del.checked = false;
      const vis = row.querySelector('[name$="-is_visible"]'); if (vis) vis.checked = true;
    });
    sync();
  };

  const autoLayout = () => applyDefaultLayout();

  const addCustomText = () => {
    if (!emptyTpl || !totalForms) return;
    const idx = Number(totalForms.value || 0);
    const wrap = document.createElement('div');
    wrap.innerHTML = emptyTpl.innerHTML.replaceAll('__prefix__', String(idx)).trim();
    const row = wrap.firstElementChild;
    if (!row) return;
    row.dataset.formIndex = String(idx);
    row.dataset.elementType = 'custom_text';
    list.appendChild(row);
    totalForms.value = String(idx + 1);

    const set = (s, v) => {
      const n = row.querySelector(s);
      if (!n) return;
      if (n.type === 'checkbox') n.checked = Boolean(v); else n.value = String(v);
    };
    set('[name$="-element_type"]', 'custom_text');
    set('[name$="-text"]', 'Новий текст');
    set('[name$="-x_mm"]', '3.00');
    set('[name$="-y_mm"]', '3.00');
    set('[name$="-width_mm"]', '25.00');
    set('[name$="-height_mm"]', '6.00');
    set('[name$="-font_size"]', '7');
    set('[name$="-is_visible"]', true);
    wireRow(row);
    syncRow(row);
    select(row);
  };

  zoomIn?.addEventListener('click', () => { zoom = Math.min(3, zoom + 0.1); sync(); });
  zoomOut?.addEventListener('click', () => { zoom = Math.max(0.4, zoom - 0.1); sync(); });
  zoomFit?.addEventListener('click', () => { zoom = 1; sync(); });
  gridToggle?.addEventListener('change', () => sheet.classList.toggle('show-grid', gridToggle.checked));
  resetBtn?.addEventListener('click', applyDefaultLayout);
  optimizeBtn?.addEventListener('click', autoLayout);
  addBtn?.addEventListener('click', addCustomText);
  widthInput?.addEventListener('input', updateSheet);
  heightInput?.addEventListener('input', updateSheet);

  form.querySelectorAll('[data-element-form]').forEach(wireRow);
  sync();
})();
