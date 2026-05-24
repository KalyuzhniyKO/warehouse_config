(function () {
  const form = document.querySelector('form.label-template-form-panel');
  const root = document.querySelector('[data-label-preview-root]');
  const sheet = root?.querySelector('[data-preview-sheet]');
  if (!form || !root || !sheet) return;
  const gridToggle = root.querySelector('[data-grid-toggle]');
  const snapToggle = root.querySelector('[data-snap-toggle]');
  const resetBtn = root.querySelector('[data-reset-layout]');

  const map = Object.fromEntries(Array.from(root.querySelectorAll('[data-label-element]')).map((el) => [el.dataset.labelElement, el]));
  const defaultCoords = {};
  let selectedType = null;
  let drag = null;

  const toNumber = (value, fallback = 0) => {
    const parsed = parseFloat(String(value ?? '').trim().replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const round2 = (n) => Math.round(n * 100) / 100;
  const pxPerMm = () => sheet.clientWidth / Math.max(toNumber(form.querySelector('[name="width_mm"]')?.value, 58), 1);
  const labelSizeMm = () => ({ width: Math.max(toNumber(form.querySelector('[name="width_mm"]')?.value, 58), 1), height: Math.max(toNumber(form.querySelector('[name="height_mm"]')?.value, 40), 1) });
  const gridStep = () => (snapToggle?.checked ? 1 : 0);

  const selectElement = (type) => {
    selectedType = type;
    form.querySelectorAll('[data-element-form]').forEach((row) => { const active = row.dataset.elementType === type; row.classList.toggle('is-selected', active); row.classList.toggle('label-element-list-item--selected', active); });
    Object.entries(map).forEach(([t, el]) => el.classList.toggle('is-selected', t === type));
  };
  const clamp = (row, x, y) => {
    const { width: labelWidth, height: labelHeight } = labelSizeMm();
    const w = toNumber(row.querySelector('[name$="-width_mm"]')?.value, 10);
    const h = toNumber(row.querySelector('[name$="-height_mm"]')?.value, 4);
    return { x: Math.min(Math.max(0, x), Math.max(0, labelWidth - w)), y: Math.min(Math.max(0, y), Math.max(0, labelHeight - h)) };
  };
  const applyGridClass = () => sheet.classList.toggle('show-grid', !!gridToggle?.checked);

  const syncFromInputs = () => {
    const scale = pxPerMm();
    form.querySelectorAll('[data-element-form]').forEach((row) => {
      const type = row.dataset.elementType;
      const target = map[type];
      if (!target) return;
      const { width: labelWidth, height: labelHeight } = labelSizeMm();
      const minW = type === 'barcode' ? 18 : 2;
      const minH = type === 'barcode' ? 8 : 2;
      const wInput = row.querySelector('[name$="-width_mm"]');
      const hInput = row.querySelector('[name$="-height_mm"]');
      const xInput = row.querySelector('[name$="-x_mm"]');
      const yInput = row.querySelector('[name$="-y_mm"]');
      const w = Math.min(Math.max(toNumber(wInput?.value, 10), minW), labelWidth);
      const h = Math.min(Math.max(toNumber(hInput?.value, 4), minH), labelHeight);
      const c = clamp(row, toNumber(xInput?.value, 0), toNumber(yInput?.value, 0));
      const visible = row.querySelector('[name$="-is_visible"]')?.checked;
      [xInput,yInput,wInput,hInput].forEach((el)=>{ if(el&&document.activeElement!==el) el.value=round2(toNumber(el.value)).toFixed(2); });
      xInput.value = c.x.toFixed(2); yInput.value = c.y.toFixed(2); wInput.value = w.toFixed(2); hInput.value = h.toFixed(2);
      target.style.cssText = `position:absolute;left:${c.x*scale}px;top:${c.y*scale}px;width:${w*scale}px;height:${h*scale}px;display:${visible?'':'none'}`;
      row.querySelector('[data-barcode-size-warning]')?.remove();
      if (type === 'barcode' && (w < 24 || h < 10)) {
        const warn = document.createElement('div'); warn.className='label-preview-warning mt-2'; warn.dataset.barcodeSizeWarning='1'; warn.textContent=root.dataset.barcodeSizeWarningText || 'Barcode warning'; row.appendChild(warn);
      }
    });
  };

  form.querySelectorAll('[data-element-form]').forEach((row) => {
    const type = row.dataset.elementType;
    const xInput = row.querySelector('[name$="-x_mm"]');
    const yInput = row.querySelector('[name$="-y_mm"]');
    defaultCoords[type] = { x: xInput?.value || '0', y: yInput?.value || '0' };
    row.addEventListener('click', () => selectElement(type));
    row.querySelector('[data-select-element]')?.addEventListener('click', () => selectElement(type));
  });

  Object.entries(map).forEach(([type, el]) => {
    el.style.touchAction = 'none';
    el.addEventListener('pointerdown', (event) => {
      const row = form.querySelector(`[data-element-type="${type}"]`); if (!row) return;
      selectElement(type);
      drag = { type, row, startX: event.clientX, startY: event.clientY, baseX: toNumber(row.querySelector('[name$="-x_mm"]').value, 0), baseY: toNumber(row.querySelector('[name$="-y_mm"]').value, 0) };
      el.setPointerCapture(event.pointerId); event.preventDefault();
    });
    el.addEventListener('pointerup', () => { drag = null; });
    el.addEventListener('focus', () => selectElement(type));
  });

  root.addEventListener('pointermove', (event) => {
    if (!drag) return;
    const scale = pxPerMm(); let x = drag.baseX + (event.clientX - drag.startX) / scale; let y = drag.baseY + (event.clientY - drag.startY) / scale;
    const step = gridStep(); if (step > 0) { x = Math.round(x / step) * step; y = Math.round(y / step) * step; }
    const c = clamp(drag.row, x, y);
    drag.row.querySelector('[name$="-x_mm"]').value = c.x.toFixed(2); drag.row.querySelector('[name$="-y_mm"]').value = c.y.toFixed(2);
    syncFromInputs();
  });

  form.addEventListener('keydown', (event) => {
    if (!selectedType || !event.key.startsWith('Arrow')) return;
    const row = form.querySelector(`[data-element-type="${selectedType}"]`); if (!row) return;
    let step = event.shiftKey ? 5 : ((event.altKey || event.ctrlKey) ? 0.5 : 1);
    let dx = 0, dy = 0; if (event.key === 'ArrowLeft') dx = -step; if (event.key === 'ArrowRight') dx = step; if (event.key === 'ArrowUp') dy = -step; if (event.key === 'ArrowDown') dy = step;
    if (!dx && !dy) return;
    const c = clamp(row, toNumber(row.querySelector('[name$="-x_mm"]').value)+dx, toNumber(row.querySelector('[name$="-y_mm"]').value)+dy);
    row.querySelector('[name$="-x_mm"]').value = c.x.toFixed(2); row.querySelector('[name$="-y_mm"]').value = c.y.toFixed(2);
    syncFromInputs(); event.preventDefault();
  });

  root.querySelectorAll('[data-align]').forEach((btn) => btn.addEventListener('click', () => {
    if (!selectedType) return;
    const row = form.querySelector(`[data-element-type="${selectedType}"]`); if (!row) return;
    const { width: lw, height: lh } = labelSizeMm(); const w = toNumber(row.querySelector('[name$="-width_mm"]').value); const h = toNumber(row.querySelector('[name$="-height_mm"]').value);
    let x = toNumber(row.querySelector('[name$="-x_mm"]').value), y = toNumber(row.querySelector('[name$="-y_mm"]').value);
    const a = btn.dataset.align; if (a==='left') x=0; if (a==='hcenter') x=(lw-w)/2; if (a==='right') x=lw-w; if (a==='top') y=0; if (a==='vcenter') y=(lh-h)/2; if (a==='bottom') y=lh-h;
    const c = clamp(row, x, y); row.querySelector('[name$="-x_mm"]').value = c.x.toFixed(2); row.querySelector('[name$="-y_mm"]').value = c.y.toFixed(2); syncFromInputs();
  }));

  resetBtn?.addEventListener('click', () => {
    if (!window.confirm(root.dataset.resetConfirm || 'Reset layout?')) return;
    form.querySelectorAll('[data-element-form]').forEach((row)=>{ const d=defaultCoords[row.dataset.elementType]; if(!d) return; row.querySelector('[name$="-x_mm"]').value=d.x; row.querySelector('[name$="-y_mm"]').value=d.y;});
    syncFromInputs();
  });

  form.addEventListener('input', syncFromInputs);
  form.addEventListener('blur', (e)=>{ if(e.target.matches('[name$="-x_mm"],[name$="-y_mm"],[name$="-width_mm"],[name$="-height_mm"]')) syncFromInputs();}, true);
  gridToggle?.addEventListener('change', applyGridClass);
  window.addEventListener('resize', syncFromInputs);
  applyGridClass(); syncFromInputs(); selectElement(form.querySelector('[data-element-form]')?.dataset.elementType || null);
})();
