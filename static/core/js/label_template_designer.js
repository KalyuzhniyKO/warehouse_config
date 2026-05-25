(() => {
  const form = document.querySelector('[data-label-designer-form]'); if (!form) return;
  const root = form.querySelector('[data-label-preview-root]'); const sheet = form.querySelector('[data-preview-content]');
  const list = form.querySelector('.label-element-list'); const emptyTpl = form.querySelector('[data-empty-element-form]');
  const totalForms = form.querySelector('#id_elements-TOTAL_FORMS'); const addBtn = form.querySelector('[data-add-custom-text]');
  const map = new Map(); let selectedKey = null; let zoom = 1; const ZMIN=.4,ZMAX=3;
  const pxPerMm = () => 4.2 * zoom; const toN=(v,d=0)=>{const n=parseFloat(v); return Number.isFinite(n)?n:d;};
  const keyOf = (row) => row.dataset.formIndex || row.dataset.elementType;
  const labelOf = (row) => row.dataset.elementType === 'custom_text' ? (row.querySelector('[name$="-text"]')?.value || 'Текст').slice(0,20) : row.querySelector('[data-select-element]').textContent;
  const buildEl = (row) => {
    const k = keyOf(row); let el = map.get(k); if (!el) { el = document.createElement('div'); el.className = 'label-preview-field'; el.dataset.labelElement = row.dataset.elementType; el.dataset.formIndex = row.dataset.formIndex; el.tabIndex = 0; sheet.appendChild(el); map.set(k, el); }
    return el;
  };
  const syncRow = (row) => {
    const del=row.querySelector('[name$="-DELETE"]'); const vis=row.querySelector('[name$="-is_visible"]');
    const el = buildEl(row); const x=toN(row.querySelector('[name$="-x_mm"]')?.value), y=toN(row.querySelector('[name$="-y_mm"]')?.value), w=toN(row.querySelector('[name$="-width_mm"]')?.value,20), h=toN(row.querySelector('[name$="-height_mm"]')?.value,6);
    el.style.cssText=`position:absolute;left:${x*pxPerMm()}px;top:${y*pxPerMm()}px;width:${w*pxPerMm()}px;height:${h*pxPerMm()}px;display:${(vis?.checked&&!del?.checked)?'':'none'}`;
    el.textContent = row.dataset.elementType === 'barcode' ? '' : (row.dataset.elementType === 'item_name' ? 'Дріт оцинкований Ø3 мм' : row.dataset.elementType === 'internal_code' ? 'Код: YT-000001' : row.dataset.elementType === 'barcode_text' ? '4820000000012' : row.querySelector('[name$="-text"]')?.value || '');
    row.querySelector('[data-select-element]').textContent = labelOf(row);
  };
  const sync = () => form.querySelectorAll('[data-element-form]').forEach(syncRow);
  const select = (row) => { selectedKey = keyOf(row); form.querySelectorAll('[data-element-form]').forEach(r=>r.classList.toggle('is-selected', keyOf(r)===selectedKey)); map.forEach((el,k)=>el.classList.toggle('is-selected',k===selectedKey)); };
  const wireRow = (row) => {
    row.addEventListener('click', ()=>select(row)); row.querySelector('[data-select-element]')?.addEventListener('click',()=>select(row));
    row.addEventListener('input', ()=>syncRow(row));
    const el=buildEl(row); let drag=null;
    el.addEventListener('pointerdown',(e)=>{select(row); drag={x:e.clientX,y:e.clientY,bx:toN(row.querySelector('[name$="-x_mm"]').value),by:toN(row.querySelector('[name$="-y_mm"]').value)}; e.preventDefault();});
    root.addEventListener('pointermove',(e)=>{if(!drag||selectedKey!==keyOf(row))return; row.querySelector('[name$="-x_mm"]').value=(drag.bx+(e.clientX-drag.x)/pxPerMm()).toFixed(2); row.querySelector('[name$="-y_mm"]').value=(drag.by+(e.clientY-drag.y)/pxPerMm()).toFixed(2); syncRow(row);});
    root.addEventListener('pointerup',()=>drag=null);
  };
  const addCustomText = () => {
    const i=Number(totalForms.value); const html=emptyTpl.innerHTML.replaceAll('__prefix__', String(i));
    const wrap=document.createElement('div'); wrap.innerHTML=html.trim(); const row=wrap.firstElementChild; row.dataset.formIndex=String(i); row.dataset.elementType='custom_text';
    list.appendChild(row); totalForms.value=String(i+1);
    const set=(s,v)=>{const n=row.querySelector(s); if(n) { if(n.type==='checkbox') n.checked=v; else n.value=v; }};
    set('[name$="-element_type"]','custom_text'); set('[name$="-text"]','Новий текст'); set('[name$="-x_mm"]','3.00'); set('[name$="-y_mm"]','3.00'); set('[name$="-width_mm"]','25.00'); set('[name$="-height_mm"]','6.00'); set('[name$="-font_size"]','7'); set('[name$="-is_visible"]',true);
    wireRow(row); syncRow(row); select(row);
  };
  form.querySelectorAll('[data-element-form]').forEach((r,idx)=>{ if(!r.dataset.formIndex) r.dataset.formIndex=String(idx); wireRow(r); });
  addBtn?.addEventListener('click', addCustomText);
  sync();
})();
