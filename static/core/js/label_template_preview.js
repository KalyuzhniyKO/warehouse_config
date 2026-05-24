(function () {
  const root = document.querySelector('[data-label-preview-root]');
  if (!root) return;
  const form = document.querySelector('form.label-template-form-panel');
  if (!form) return;

  const sheet = root.querySelector('[data-preview-sheet]');
  const content = root.querySelector('[data-preview-content]');
  const itemName = root.querySelector('[data-preview-item-name]');
  const internalCode = root.querySelector('[data-preview-internal-code]');
  const barcodeText = root.querySelector('[data-preview-barcode-text]');
  const barcode = root.querySelector('[data-preview-barcode]');
  const sizeBadge = root.querySelector('[data-label-size]');
  const sizeText = root.querySelector('[data-preview-mm-size]');
  const warningMargins = root.querySelector('[data-preview-warning-margins]');
  const warningBarcode = root.querySelector('[data-preview-warning-barcode]');
  const warningOverflow = root.querySelector('[data-preview-warning-overflow]');
  const warningText = root.querySelector('[data-preview-warning-text]');

  const getValue = (name, fallback = 0) => {
    const el = form.querySelector(`[name="${name}"]`);
    if (!el) return fallback;
    const raw = typeof el.value === "string" ? el.value.trim().replace(",", ".") : el.value;
    const value = parseFloat(raw);
    return Number.isFinite(value) ? value : fallback;
  };
  const isChecked = (name) => !!form.querySelector(`[name="${name}"]`)?.checked;

  const refresh = () => {
    const width = Math.min(Math.max(getValue('width_mm', 58), 20), 200);
    const height = Math.min(Math.max(getValue('height_mm', 40), 20), 200);
    const mt = Math.max(getValue('margin_top_mm', 1), 0);
    const mr = Math.max(getValue('margin_right_mm', 1), 0);
    const mb = Math.max(getValue('margin_bottom_mm', 1), 0);
    const ml = Math.max(getValue('margin_left_mm', 1), 0);
    const barcodeHeight = Math.max(getValue('barcode_height_mm', 12), 1);
    const barWidth = Math.max(getValue('barcode_bar_width_mm', 0.3), 0.1);

    const stageWidth = 330;
    const stageHeight = 230;
    const scale = Math.max(1.6, Math.min(6, stageWidth / width, stageHeight / height));

    sheet.style.width = `${width * scale}px`;
    sheet.style.height = `${height * scale}px`;

    content.style.top = `${mt * scale}px`;
    content.style.right = `${mr * scale}px`;
    content.style.bottom = `${mb * scale}px`;
    content.style.left = `${ml * scale}px`;

    itemName.style.display = isChecked('show_item_name') ? '' : 'none';
    internalCode.style.display = isChecked('show_internal_code') ? '' : 'none';
    barcodeText.style.display = isChecked('show_barcode_text') ? '' : 'none';

    itemName.style.fontSize = `${Math.max(getValue('item_name_font_size', 8), 6) * scale}px`;
    internalCode.style.fontSize = `${Math.max(getValue('internal_code_font_size', 7), 6) * scale}px`;
    barcodeText.style.fontSize = `${Math.max(getValue('barcode_text_font_size', 7), 6) * scale}px`;

    barcode.style.display = "";
    barcode.style.height = `${barcodeHeight * scale}px`;
    barcode.style.setProperty('--bar-width', `${Math.max(barWidth * scale, 1)}px`);

    sizeBadge.textContent = `${Math.round(width)} × ${Math.round(height)} мм`;
    sizeText.textContent = `${width.toFixed(1)} × ${height.toFixed(1)} мм`;

    const innerWidth = width - ml - mr;
    const innerHeight = height - mt - mb;
    const textEstimateMm = (isChecked('show_item_name') ? getValue('item_name_font_size', 8) * 0.55 : 0)
      + (isChecked('show_internal_code') ? getValue('internal_code_font_size', 7) * 0.45 : 0)
      + (isChecked('show_barcode_text') ? getValue('barcode_text_font_size', 7) * 0.45 : 0)
      + 2.4;

    const contentEstimateMm = textEstimateMm + barcodeHeight;

    warningMargins.hidden = !(innerWidth <= 0 || innerHeight <= 0 || innerWidth < width * 0.5 || innerHeight < height * 0.45);
    warningBarcode.hidden = !(barcodeHeight > innerHeight * 0.8 || innerWidth < 18);
    warningOverflow.hidden = !(contentEstimateMm > innerHeight);
    warningText.hidden = !(isChecked('show_item_name') && (innerWidth < 16 || getValue('item_name_font_size', 8) > innerHeight * 0.28));
  };

  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);

  const watchedFields = [
    "width_mm", "height_mm", "margin_top_mm", "margin_right_mm", "margin_bottom_mm", "margin_left_mm",
    "item_name_font_size", "internal_code_font_size", "barcode_text_font_size",
    "barcode_height_mm", "barcode_bar_width_mm", "show_item_name", "show_internal_code", "show_barcode_text"
  ];
  watchedFields.forEach((fieldName) => {
    const field = form.querySelector(`[name="${fieldName}"]`);
    if (!field) return;
    field.addEventListener("blur", refresh);
  });

  refresh();
})();
