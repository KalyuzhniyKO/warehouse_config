(function () {
  const form = document.querySelector('form.label-template-form-panel');
  const root = document.querySelector('[data-label-preview-root]');
  const sheet = root?.querySelector('[data-preview-sheet]');
  if (!form || !root || !sheet) return;

  const map = {
    item_name: root.querySelector('[data-label-element="item_name"]'),
    internal_code: root.querySelector('[data-label-element="internal_code"]'),
    barcode: root.querySelector('[data-label-element="barcode"]'),
    barcode_text: root.querySelector('[data-label-element="barcode_text"]'),
  };

  const toNumber = (value, fallback = 0) => {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const pxPerMm = () => sheet.clientWidth / Math.max(toNumber(form.querySelector('[name="width_mm"]')?.value, 58), 1);
  const labelSizeMm = () => ({ width: Math.max(toNumber(form.querySelector('[name="width_mm"]')?.value, 58), 1), height: Math.max(toNumber(form.querySelector('[name="height_mm"]')?.value, 40), 1) });

  const syncFromInputs = () => {
    const scale = pxPerMm();
    form.querySelectorAll('[data-element-form]').forEach((row) => {
      const type = row.dataset.elementType;
      const target = map[type];
      if (!target) return;
      const { width: labelWidth, height: labelHeight } = labelSizeMm();
      const w = Math.min(toNumber(row.querySelector('[name$="-width_mm"]')?.value, 10), labelWidth);
      const h = Math.min(toNumber(row.querySelector('[name$="-height_mm"]')?.value, 4), labelHeight);
      const x = Math.min(Math.max(0, toNumber(row.querySelector('[name$="-x_mm"]')?.value, 0)), labelWidth - w);
      const y = Math.min(Math.max(0, toNumber(row.querySelector('[name$="-y_mm"]')?.value, 0)), labelHeight - h);
      const visible = row.querySelector('[name$="-is_visible"]')?.checked;
      row.querySelector('[name$="-x_mm"]').value = x.toFixed(2);
      row.querySelector('[name$="-y_mm"]').value = y.toFixed(2);
      row.querySelector('[name$="-width_mm"]').value = w.toFixed(2);
      row.querySelector('[name$="-height_mm"]').value = h.toFixed(2);
      target.style.position = 'absolute';
      target.style.left = `${x * scale}px`;
      target.style.top = `${y * scale}px`;
      target.style.width = `${w * scale}px`;
      target.style.height = `${h * scale}px`;
      target.style.display = visible ? '' : 'none';
    });
  };

  let drag = null;
  Object.entries(map).forEach(([type, el]) => {
    if (!el) return;
    el.style.touchAction = 'none';
    el.addEventListener('pointerdown', (event) => {
      const row = form.querySelector(`[data-element-type="${type}"]`);
      if (!row) return;
      drag = { type, row, startX: event.clientX, startY: event.clientY, baseX: toNumber(row.querySelector('[name$="-x_mm"]').value, 0), baseY: toNumber(row.querySelector('[name$="-y_mm"]').value, 0) };
      el.classList.add('is-selected');
      el.setPointerCapture(event.pointerId);
    });
    el.addEventListener('pointerup', () => { drag = null; el.classList.remove('is-selected'); });
  });

  root.addEventListener('pointermove', (event) => {
    if (!drag) return;
    const scale = pxPerMm();
    const dx = (event.clientX - drag.startX) / scale;
    const dy = (event.clientY - drag.startY) / scale;
    const { width: labelWidth, height: labelHeight } = labelSizeMm();
    const xInput = drag.row.querySelector('[name$="-x_mm"]');
    const yInput = drag.row.querySelector('[name$="-y_mm"]');
    const w = toNumber(drag.row.querySelector('[name$="-width_mm"]')?.value, 10);
    const h = toNumber(drag.row.querySelector('[name$="-height_mm"]')?.value, 4);
    xInput.value = Math.min(Math.max(0, drag.baseX + dx), Math.max(0, labelWidth - w)).toFixed(2);
    yInput.value = Math.min(Math.max(0, drag.baseY + dy), Math.max(0, labelHeight - h)).toFixed(2);
    syncFromInputs();
  });

  form.addEventListener('input', syncFromInputs);
  window.addEventListener('resize', syncFromInputs);
  syncFromInputs();
})();
