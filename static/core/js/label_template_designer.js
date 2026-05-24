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

  const pxPerMm = () => sheet.clientWidth / Math.max(parseFloat(form.querySelector('[name="width_mm"]')?.value || '58'), 1);

  const syncFromInputs = () => {
    const scale = pxPerMm();
    form.querySelectorAll('[data-element-form]').forEach((row) => {
      const type = row.dataset.elementType;
      const target = map[type];
      if (!target) return;
      const x = parseFloat(row.querySelector('[name$="-x_mm"]')?.value || '0');
      const y = parseFloat(row.querySelector('[name$="-y_mm"]')?.value || '0');
      const w = parseFloat(row.querySelector('[name$="-width_mm"]')?.value || '10');
      const h = parseFloat(row.querySelector('[name$="-height_mm"]')?.value || '4');
      const visible = row.querySelector('[name$="-is_visible"]')?.checked;
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
      drag = { type, row, startX: event.clientX, startY: event.clientY, baseX: parseFloat(row.querySelector('[name$="-x_mm"]').value || '0'), baseY: parseFloat(row.querySelector('[name$="-y_mm"]').value || '0') };
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
    const xInput = drag.row.querySelector('[name$="-x_mm"]');
    const yInput = drag.row.querySelector('[name$="-y_mm"]');
    xInput.value = Math.max(0, drag.baseX + dx).toFixed(2);
    yInput.value = Math.max(0, drag.baseY + dy).toFixed(2);
    syncFromInputs();
  });

  form.addEventListener('input', syncFromInputs);
  window.addEventListener('resize', syncFromInputs);
  syncFromInputs();
})();
