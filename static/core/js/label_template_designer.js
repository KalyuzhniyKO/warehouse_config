(function () {
  const form = document.querySelector('form.label-template-form-panel');
  const root = document.querySelector('[data-label-preview-root]');
  const sheet = root?.querySelector('[data-preview-sheet]');
  if (!form || !root || !sheet) return;
  const gridToggle = root.querySelector('[data-grid-toggle]');
  const snapToggle = root.querySelector('[data-snap-toggle]');
  const resetBtn = root.querySelector('[data-reset-layout]');
  const optimizeBtn = root.querySelector('[data-optimize-layout]');
  const stage = root.querySelector('[data-label-designer-stage]');
  const zoomInBtn = root.querySelector('[data-label-zoom-in]');
  const zoomOutBtn = root.querySelector('[data-label-zoom-out]');
  const zoomFitBtn = root.querySelector('[data-label-zoom-fit]');
  const zoomValue = root.querySelector('[data-label-zoom-value]');
  const selectedSummary = root.querySelector('[data-selected-element-summary]');
  const warningsBox = root.querySelector('[data-element-warnings]');

  const map = Object.fromEntries(Array.from(root.querySelectorAll('[data-label-element]')).map((el) => [el.dataset.labelElement, el]));
  const defaultCoords = {};
  const elementLabels = {
    item_name: root.dataset.labelItemName || 'Назва товару',
    internal_code: root.dataset.labelInternalCode || 'Внутрішній код',
    barcode: root.dataset.labelBarcode || 'Штрихкод',
    barcode_text: root.dataset.labelBarcodeText || 'Текст штрихкоду',
  };
  let selectedType = null;
  let drag = null;
  let zoom = 1;
  let fitPxPerMmBase = 1;
  const ZOOM_MIN = 0.7;
  const ZOOM_MAX = 3;
  const ZOOM_STEP = 0.1;

  const toNumber = (value, fallback = 0) => {
    const parsed = parseFloat(String(value ?? '').trim().replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const round2 = (n) => Math.round(n * 100) / 100;
  const pxPerMm = () => sheet.clientWidth / Math.max(toNumber(form.querySelector('[name="width_mm"]')?.value, 58), 1);
  const labelSizeMm = () => ({ width: Math.max(toNumber(form.querySelector('[name="width_mm"]')?.value, 58), 1), height: Math.max(toNumber(form.querySelector('[name="height_mm"]')?.value, 40), 1) });
  const gridStep = () => (snapToggle?.checked ? 1 : 0);
  const getRowValues = (row) => ({
    type: row.dataset.elementType, x: toNumber(row.querySelector('[name$="-x_mm"]')?.value, 0), y: toNumber(row.querySelector('[name$="-y_mm"]')?.value, 0), w: toNumber(row.querySelector('[name$="-width_mm"]')?.value, 10), h: toNumber(row.querySelector('[name$="-height_mm"]')?.value, 4), font: toNumber(row.querySelector('[name$="-font_size"]')?.value, 8),
  });

  const selectElement = (type) => {
    selectedType = type;
    form.querySelectorAll('[data-element-form]').forEach((row) => { const active = row.dataset.elementType === type; row.classList.toggle('is-selected', active); row.classList.toggle('label-element-list-item--selected', active); });
    Object.entries(map).forEach(([t, el]) => el.classList.toggle('is-selected', t === type));
    if (selectedSummary && type) {
      const row = form.querySelector(`[data-element-type="${type}"]`);
      if (row) { const v = getRowValues(row); selectedSummary.textContent = `X: ${v.x.toFixed(2)} мм · Y: ${v.y.toFixed(2)} мм · W: ${v.w.toFixed(2)} мм · H: ${v.h.toFixed(2)} мм`; }
    }
  };
  const clamp = (row, x, y) => {
    const { width: labelWidth, height: labelHeight } = labelSizeMm();
    const w = toNumber(row.querySelector('[name$="-width_mm"]')?.value, 10);
    const h = toNumber(row.querySelector('[name$="-height_mm"]')?.value, 4);
    return { x: Math.min(Math.max(0, x), Math.max(0, labelWidth - w)), y: Math.min(Math.max(0, y), Math.max(0, labelHeight - h)) };
  };
  const applyGridClass = () => sheet.classList.toggle('show-grid', !!gridToggle?.checked);
  const fitZoom = () => 1;
  const updateZoomUi = () => { if (zoomValue) zoomValue.textContent = `${Math.round(zoom * 100)}%`; };
  const setZoom = (next, keepCenter = false) => {
    const prevRect = sheet.getBoundingClientRect();
    const prevCenterX = stage ? stage.scrollLeft + stage.clientWidth / 2 : 0;
    const prevCenterY = stage ? stage.scrollTop + stage.clientHeight / 2 : 0;
    zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, round2(next)));
    const { width, height } = labelSizeMm();
    const availableW = Math.max((stage?.clientWidth || 820) - 28, 220);
    const availableH = Math.max((stage?.clientHeight || 520) - 28, 160);
    fitPxPerMmBase = Math.min(availableW / width, availableH / height);
    const visualPxPerMm = fitPxPerMmBase * zoom;
    sheet.style.width = `${Math.round(width * visualPxPerMm)}px`;
    sheet.style.height = `${Math.round(height * visualPxPerMm)}px`;
    updateZoomUi();
    syncFromInputs();
    if (keepCenter && stage) {
      const nextRect = sheet.getBoundingClientRect();
      const ratioX = prevRect.width ? prevCenterX / prevRect.width : 0.5;
      const ratioY = prevRect.height ? prevCenterY / prevRect.height : 0.5;
      stage.scrollLeft = Math.max(0, ratioX * nextRect.width - stage.clientWidth / 2);
      stage.scrollTop = Math.max(0, ratioY * nextRect.height - stage.clientHeight / 2);
    }
  };

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
    });
    if (warningsBox) {
      warningsBox.innerHTML = '';
      const { width: lw, height: lh } = labelSizeMm();
      form.querySelectorAll('[data-element-form]').forEach((row) => {
        const { type, x, y, w, h, font } = getRowValues(row);
        if (!row.querySelector('[name$="-is_visible"]')?.checked) return;
        const issues = [];
        if (x + w > lw || y + h > lh) issues.push(root.dataset.warningOverflow || 'Елемент виходить за межі етикетки.');
        if (w < 2 || h < 2) issues.push(root.dataset.warningSmall || 'Елемент занадто малий.');
        const lineHeightMm = Math.max(1.8, font * 0.42);
        if ((type === 'item_name' || type === 'internal_code' || type === 'barcode_text') && lineHeightMm > h) {
          issues.push(root.dataset.warningTextClip || 'Текст може обрізатися у PDF.');
        }
        if (type === 'barcode') {
          const tooNarrow = w < 30;
          const tooLow = h < 12;
          const areaTooSmall = (w * h) < 420;
          if ((tooNarrow && tooLow) || areaTooSmall) issues.push(root.dataset.barcodeSizeWarningText || 'Barcode warning');
        }
        if (type === 'barcode_text') {
          const currentText = map.barcode_text?.textContent?.trim() || '4820000000012';
          const avgCharMm = font * 0.23;
          if (avgCharMm * currentText.length > w || h < Math.max(3.2, lineHeightMm)) {
            issues.push(root.dataset.warningBarcodeText || 'Підпис штрихкоду може не вміститися.');
          }
        }
        if (!issues.length) return;
        const warning = document.createElement('div');
        warning.className = 'label-preview-warning';
        warning.textContent = `${elementLabels[type] || type}: ${issues.join(' ')}`;
        warningsBox.appendChild(warning);
      });
    }
  };

  const optimizedLayout = (labelW, labelH, fontMap = {}) => {
    const pad = Math.max(2, Math.min(labelW * 0.06, 4));
    const width = Math.max(12, labelW - pad * 2);
    const gap = Math.max(1, labelH * 0.025);
    const itemH = Math.max(4.5, Math.min(6.2, Math.max((fontMap.item_name || 8) * 0.58, labelH * 0.14)));
    const codeH = Math.max(3.8, Math.min(5.2, Math.max((fontMap.internal_code || 6) * 0.56, labelH * 0.11)));
    const textH = Math.max(3.6, Math.min(5, Math.max((fontMap.barcode_text || 7) * 0.58, labelH * 0.1)));
    const minBarcodeH = Math.max(10.5, labelH * 0.27);
    const maxBarcodeH = Math.max(minBarcodeH, labelH * 0.42);
    const yItem = pad;
    const yCode = yItem + itemH + gap;
    const yBarcode = yCode + codeH + gap * 1.7;
    const barcodeH = Math.max(minBarcodeH, Math.min(maxBarcodeH, labelH - pad - textH - yBarcode));
    const yText = yBarcode + barcodeH + gap;
    return {
      item_name: { x: pad, y: yItem, w: width, h: itemH },
      internal_code: { x: pad, y: yCode, w: width, h: codeH },
      barcode: { x: pad, y: yBarcode, w: width, h: barcodeH },
      barcode_text: { x: pad, y: yText, w: width, h: textH },
    };
  };

  const applyPresetLayout = (layout) => {
    form.querySelectorAll('[data-element-form]').forEach((row) => {
      const d = layout[row.dataset.elementType];
      if (!d) return;
      row.querySelector('[name$="-x_mm"]').value = round2(toNumber(d.x, 0)).toFixed(2);
      row.querySelector('[name$="-y_mm"]').value = round2(toNumber(d.y, 0)).toFixed(2);
      row.querySelector('[name$="-width_mm"]').value = round2(toNumber(d.w, 10)).toFixed(2);
      row.querySelector('[name$="-height_mm"]').value = round2(toNumber(d.h, 4)).toFixed(2);
    });
  };

  form.querySelectorAll('[data-element-form]').forEach((row) => {
    const type = row.dataset.elementType;
    const xInput = row.querySelector('[name$="-x_mm"]');
    const yInput = row.querySelector('[name$="-y_mm"]');
    defaultCoords[type] = {
      x: xInput?.value || '0',
      y: yInput?.value || '0',
      w: row.querySelector('[name$="-width_mm"]')?.value || '10',
      h: row.querySelector('[name$="-height_mm"]')?.value || '4',
    };
    row.addEventListener('click', () => selectElement(type));
    row.querySelector('[data-select-element]')?.addEventListener('click', () => selectElement(type));
  });

  Object.entries(map).forEach(([type, el]) => {
    el.style.touchAction = 'none';
      el.addEventListener('pointerdown', (event) => {
      const row = form.querySelector(`[data-element-type="${type}"]`); if (!row) return;
      selectElement(type);
      drag = { type, row, startX: event.clientX, startY: event.clientY, baseX: toNumber(row.querySelector('[name$="-x_mm"]').value, 0), baseY: toNumber(row.querySelector('[name$="-y_mm"]').value, 0), pointerId: event.pointerId };
      document.body.style.userSelect = 'none';
      document.body.style.overflow = 'hidden';
      el.style.cursor = 'grabbing';
      el.setPointerCapture(event.pointerId); event.preventDefault();
    });
    const finishDrag = () => { drag = null; document.body.style.userSelect = ''; document.body.style.overflow = ''; el.style.cursor = 'grab'; };
    el.addEventListener('pointerup', finishDrag);
    el.addEventListener('pointercancel', finishDrag);
    el.addEventListener('focus', () => selectElement(type));
  });

  root.addEventListener('pointermove', (event) => {
    if (!drag) return;
    if (event.pointerId !== drag.pointerId) return;
    const scale = pxPerMm(); if (!scale) return;
    let x = drag.baseX + (event.clientX - drag.startX) / scale;
    let y = drag.baseY + (event.clientY - drag.startY) / scale;
    const step = gridStep(); if (step > 0) { x = Math.round(x / step) * step; y = Math.round(y / step) * step; }
    const c = clamp(drag.row, x, y);
    drag.row.querySelector('[name$="-x_mm"]').value = c.x.toFixed(2); drag.row.querySelector('[name$="-y_mm"]').value = c.y.toFixed(2);
    syncFromInputs();
    event.preventDefault();
  });
  root.addEventListener('pointerup', () => { drag = null; document.body.style.userSelect = ''; document.body.style.overflow = ''; });
  root.addEventListener('pointercancel', () => { drag = null; document.body.style.userSelect = ''; document.body.style.overflow = ''; });

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
    applyPresetLayout(defaultCoords);
    syncFromInputs();
  });

  optimizeBtn?.addEventListener('click', () => {
    const { width, height } = labelSizeMm();
    const fontMap = {};
    form.querySelectorAll('[data-element-form]').forEach((row) => {
      fontMap[row.dataset.elementType] = toNumber(row.querySelector('[name$="-font_size"]')?.value, 8);
    });
    applyPresetLayout(optimizedLayout(width, height, fontMap));
    syncFromInputs();
  });

  form.addEventListener('input', syncFromInputs);
  form.addEventListener('blur', (e)=>{ if(e.target.matches('[name$="-x_mm"],[name$="-y_mm"],[name$="-width_mm"],[name$="-height_mm"]')) syncFromInputs();}, true);
  gridToggle?.addEventListener('change', applyGridClass);
  window.addEventListener('resize', () => setZoom(zoom));
  zoomInBtn?.addEventListener('click', () => setZoom(zoom + ZOOM_STEP, true));
  zoomOutBtn?.addEventListener('click', () => setZoom(zoom - ZOOM_STEP, true));
  zoomFitBtn?.addEventListener('click', () => setZoom(fitZoom()));
  applyGridClass(); setZoom(fitZoom()); selectElement(form.querySelector('[data-element-form]')?.dataset.elementType || null);
})();
