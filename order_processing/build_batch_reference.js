const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, AlignmentType, ShadingType, BorderStyle, ImageRun } = require('docx');
const ORANGE='FF6A00', INK='1D1D1D', GREY='595959', PALE='F5F5F5', LIGHT='FFF1E6';
const noB={style:BorderStyle.NONE,size:0,color:'FFFFFF'}, thin={style:BorderStyle.SINGLE,size:4,color:'D9D9D9'};
// Defensive: always coerce to string. (Incident 10 Aug 2026 — a raw JSON number passed straight into
// TextRun silently rendered as a BLANK cell, dropping Qty off 59 documents in one run before anyone
// caught it. This alone is not the safety net — see validateDoc() below, which is the real gate.)
const T=(t,o={})=>new TextRun({text:String(t??''),size:o.size||20,bold:o.bold,color:o.color,italics:o.italics,font:'Calibri'});
const P=(r,o={})=>new Paragraph({children:Array.isArray(r)?r:[r],spacing:{after:o.after??80},alignment:o.align});
const logo=fs.readFileSync('tso-logo.png');
function cell(ch,o={}){return new TableCell({width:{size:o.w,type:WidthType.DXA},shading:o.fill?{type:ShadingType.CLEAR,fill:o.fill}:undefined,margins:{top:o.pad??70,bottom:o.pad??70,left:110,right:110},borders:o.borders,verticalAlign:o.va,columnSpan:o.span,children:ch});}
const TSO_DEL=['DELIVER TO TSO','Trade Superstore Online','Unit 8, Tomlinson Industrial Estate','Alfreton Road, Derby DE21 4ED','0333 090 9217'];
function header(title, ref){
 return [new Table({width:{size:9700,type:WidthType.DXA},columnWidths:[4850,4850],borders:{top:noB,bottom:noB,left:noB,right:noB,insideHorizontal:noB,insideVertical:noB},rows:[new TableRow({children:[
  cell([new Paragraph({children:[new ImageRun({type:'png',data:logo,transformation:{width:210,height:80}})],spacing:{after:0}})],{w:4850}),
  cell([new Paragraph({alignment:AlignmentType.RIGHT,spacing:{after:40},children:[T(title,{size:40,bold:true,color:ORANGE})]}),
       new Paragraph({alignment:AlignmentType.RIGHT,spacing:{after:0},children:[T((title=='PACKING SLIP'?'Ref: ':'PO No: ')+ref,{size:24,bold:true,color:INK})]}),
       new Paragraph({alignment:AlignmentType.RIGHT,spacing:{after:0},children:[T('Date: 23 July 2026',{size:20,color:GREY})]})],{w:4850,va:'center'})]})]}), P(T('',{size:6}),{after:60})];
}
const block=(t,ls)=>[new Paragraph({spacing:{after:40},children:[T(t,{bold:true,size:19,color:ORANGE})]}),...ls.map(l=>new Paragraph({spacing:{after:0},children:[T(l,{size:19,color:INK})]}))];
function fromSupDel(sup,del){
 return [new Table({width:{size:9700,type:WidthType.DXA},columnWidths:[3234,3233,3233],borders:{top:thin,bottom:thin,left:thin,right:thin,insideHorizontal:thin,insideVertical:thin},rows:[new TableRow({children:[
  cell(block('FROM',['Trade Superstore Online (TSO UK Ltd)','Unit 8, Tomlinson Industrial Estate','Alfreton Road, Derby, DE21 4ED','T: 0333 090 9217','hello@tradesuperstoreonline.co.uk']),{w:3234,fill:PALE}),
  cell(block('SUPPLIER',sup),{w:3233}), cell(block('DELIVER TO',del),{w:3233})]})]}), P(T('',{size:6}),{after:40})];
}
function metaRow(acct,order,req,contact){
 return [new Table({width:{size:9700,type:WidthType.DXA},columnWidths:[2425,2425,2425,2425],borders:{top:thin,bottom:thin,left:thin,right:thin,insideHorizontal:thin,insideVertical:thin},rows:[
  new TableRow({children:['Our account no','TSO order no','Requested delivery','Contact for delivery'].map(h=>cell([P(T(h,{bold:true,size:18,color:'FFFFFF'}),{after:0})],{w:2425,fill:INK}))}),
  new TableRow({children:[acct,order,req,contact].map(v=>cell([P(T(v,{size:19}),{after:0})],{w:2425}))})]}), P(T('',{size:6}),{after:40})];
}
function notesBlock(notes){
 return [new Table({width:{size:9700,type:WidthType.DXA},columnWidths:[9700],borders:{top:thin,bottom:thin,left:thin,right:thin,insideHorizontal:thin,insideVertical:thin},rows:[
  new TableRow({children:[cell([P(T('DELIVERY NOTES',{bold:true,size:18,color:'FFFFFF'}),{after:0})],{w:9700,fill:INK})]}),
  new TableRow({children:[cell(notes.map(n=>P(T(n,{size:19}),{after:0})),{w:9700,pad:90})]})]}), P(T('',{size:6}),{after:40})];
}
function termsBlock(){
 const terms = [
  '1. NO SUBSTITUTIONS \u2014 do not substitute any product without our prior written agreement.',
  '2. THE DELIVERY ADDRESS IS OUR CUSTOMER \u2014 you are supplying Trade Superstore Online, not the end user. Do not contact them for any reason except to arrange the delivery itself.',
  '3. NEVER discuss with the end customer: our trade account, prices, replacements, shortages, stock issues or anything else. Replacements, shortages, out-of-stock, delays or damage must be raised with US FIRST (0333 090 9217 / hello@tradesuperstoreonline.co.uk) \u2014 never with the end customer.',
  '4. REPLACEMENT deliveries: collect the original/faulty goods at the same time. If the collection cannot be made, do not drop off the replacement \u2014 we will not be liable for uncollected replacements.',
  '5. Do not leave pallets with the customer.',
  '6. NO PRICING PAPERWORK with the goods \u2014 no invoices, price lists or priced delivery notes to be left with or shown to the customer. Paperwork with the goods should quote our TSO order number only.',
  '7. Delivery problems (no answer, refused, access issues): contact us BEFORE rebooking or returning the goods \u2014 do not negotiate with the customer.',
  '8. Any change to the delivery date must be advised to us so that we can inform the customer.'
 ];
 return [P(T('SUPPLIER TERMS \u2014 APPLY TO EVERY ORDER', {bold:true, size:19}), {before:120, after:40}),
  new Table({width:{size:9700,type:WidthType.DXA},columnWidths:[9700],borders:{top:thin,bottom:thin,left:thin,right:thin,insideHorizontal:thin,insideVertical:thin},rows:[new TableRow({children:[cell(terms.map(n=>P(T(n,{size:17}),{after:20})),{w:9700,pad:90})]})]}), P(T('',{size:6}),{after:40})];
}
function poDoc(d){
 const c=[...header('PURCHASE ORDER', d.po), ...fromSupDel(d.sup, d.dl), ...metaRow(d.acct,d.order,d.req,d.contact)];
 const cols=[1700,4200,700,1600,1500];
 const rows=[new TableRow({children:['SKU','Description','Qty','Unit cost (ex VAT)','Line total'].map((h,i)=>cell([P(T(h,{bold:true,size:18,color:'FFFFFF'}),{after:0})],{w:cols[i],fill:ORANGE}))})];
 d.lines.forEach((l,i)=>rows.push(new TableRow({children:l.map((v,j)=>cell([P(T(v,{size:19}),{after:0,align:j>=3?AlignmentType.RIGHT:(j==2?AlignmentType.CENTER:undefined)})],{w:cols[j],fill:i%2?PALE:undefined}))})));
 const sum=(lab,val,b)=>new TableRow({children:[cell([P(T('',{size:19}),{after:0})],{w:cols[0]+cols[1]+cols[2],span:3,borders:{top:noB,left:noB,bottom:noB,right:noB}}),cell([P(T(lab,{size:19,bold:!!b}),{after:0,align:AlignmentType.RIGHT})],{w:cols[3],fill:b?LIGHT:undefined}),cell([P(T(val,{size:19,bold:!!b}),{after:0,align:AlignmentType.RIGHT})],{w:cols[4],fill:b?LIGHT:undefined})]});
 d.sums.forEach(s=>rows.push(sum(s[0],s[1],s[2])));
 c.push(new Table({width:{size:9700,type:WidthType.DXA},columnWidths:cols,borders:{top:thin,bottom:thin,left:thin,right:thin,insideHorizontal:thin,insideVertical:thin},rows}));
 c.push(P(T('',{size:6}),{after:40}));
 c.push(...notesBlock(d.notes));
 c.push(...termsBlock());
 c.push(P([T('Please confirm: ',{bold:true,size:18,color:INK}),T('line prices, delivery charge and delivery date by return, quoting our PO number on your order confirmation, delivery note and invoice. Please notify us before dispatch of any shortages, substitutions or price changes.',{size:18,color:GREY})],{after:60}));
 c.push(P(T('Invoices to: accounts@tradesuperstoreonline.co.uk \u2022 Order queries: hello@tradesuperstoreonline.co.uk \u2022 0333 090 9217',{size:17,color:GREY,italics:true}),{after:0}));
 return c;
}
function slipDoc(d){
 const sup = d.sup || ['Decor8 Northern / Painters World','FAO Rick Thompson','rick.thompson@decor8northern.co.uk','T: 0161 763 7007','Credit account - no pre-payment'];
 const del = d.tso ? TSO_DEL : d.dl;
 const acct = d.sup && d.sup.join(' ').includes('yx3956') ? 'yx3956' : 'On account';
 const c=[...header('PACKING SLIP', d.po), ...fromSupDel(sup, del), ...metaRow(acct, d.order, d.tso?'Next working day':'Standard', d.contact || 'TSO - 0333 090 9217')];
 const cols=[2200,6300,1200];
 const rows=[new TableRow({children:['SKU','Description','Qty'].map((h,i)=>cell([P(T(h,{bold:true,size:18,color:'FFFFFF'}),{after:0,align:i==2?AlignmentType.CENTER:undefined})],{w:cols[i],fill:ORANGE}))})];
 d.lines.forEach((l,i)=>rows.push(new TableRow({children:l.map((v,j)=>cell([P(T(v,{size:19}),{after:0,align:j==2?AlignmentType.CENTER:undefined})],{w:cols[j],fill:i%2?PALE:undefined}))})));
 c.push(new Table({width:{size:9700,type:WidthType.DXA},columnWidths:cols,borders:{top:thin,bottom:thin,left:thin,right:thin,insideHorizontal:thin,insideVertical:thin},rows}));
 c.push(P(T('',{size:6}),{after:40}));
 c.push(...notesBlock(d.notes));
 c.push(...termsBlock());
 c.push(P([T('Please confirm: ',{bold:true,size:18,color:INK}),T('availability, price, any delivery charge and the delivery date by return, quoting our order number on your order confirmation, delivery note and invoice. Please notify us before dispatch of any shortages or substitutions.',{size:18,color:GREY})],{after:60}));
 c.push(P(T('Invoices to: accounts@tradesuperstoreonline.co.uk \u2022 Order queries: hello@tradesuperstoreonline.co.uk \u2022 0333 090 9217',{size:17,color:GREY,italics:true}),{after:0}));
 return c;
}
// ============================================================================
// MANDATORY VALIDATION GATE (added 11 Aug 2026, after the 10 Aug qty-blank incident)
// ============================================================================
// "If anything is ever missed off the PO you can't continue just missing it" — Daniela.
// This is NOT a spot-check / sample. It runs on every single line of every single
// document, every run, no exceptions, and it BLOCKS the whole batch (writes nothing)
// if anything required is blank. A blank cell must never reach a PDF a supplier opens —
// fixing it after upload is not good enough; the build must refuse to produce it.
// isBlank() treats undefined/null/empty-string/whitespace-only as blank. Numbers, "0",
// and "confirm"-style placeholder text all count as present — only truly missing values fail.
function isBlank(v){ return v===undefined || v===null || String(v).trim()===''; }
function fail(errors, doc, msg){ errors.push(`[${doc}] ${msg}`); }
function validateDoc(d, kind, errors){
 const label = d.order || d.po || '(unknown order)';
 if (isBlank(d.order) && isBlank(d.po)) fail(errors, label, 'missing order/po number');
 // POs always require an explicit supplier block. Slips fall back to a hardcoded default (slipDoc)
 // when d.sup is omitted entirely, so only validate it there if the caller actually supplied one.
 if (kind==='po' || d.sup!==undefined) {
  if (!Array.isArray(d.sup) || d.sup.length===0 || d.sup.some(isBlank)) fail(errors, label, `supplier block (sup) is missing, empty, or has a blank line: ${JSON.stringify(d.sup)}`);
 }
 // slip 'tso' in-house deliveries use the hardcoded TSO_DEL block, not d.dl — nothing to check there.
 if (!(kind==='slip' && d.tso)) {
  if (!Array.isArray(d.dl) || d.dl.length===0 || d.dl.some(isBlank)) fail(errors, label, `delivery block (dl) is missing, empty, or has a blank line: ${JSON.stringify(d.dl)}`);
 }
 if (!Array.isArray(d.lines) || d.lines.length===0) { fail(errors, label, 'has NO order lines at all — every processed order must have at least one line'); return; }
 d.lines.forEach((l, i) => {
  // Column 0 (SKU) may legitimately be blank (in-house samples, generic items) — never fails on its own.
  if (kind==='po') {
   const [sku, desc, qty, cost, total] = l;
   if (isBlank(desc)) fail(errors, label, `line ${i+1} (SKU "${sku}") is missing a Description`);
   if (isBlank(qty)) fail(errors, label, `line ${i+1} (SKU "${sku}") is missing a Qty — this exact bug shipped 59 broken documents on 10 Aug 2026, do not let it recur`);
   if (isBlank(cost)) fail(errors, label, `line ${i+1} (SKU "${sku}") is missing a Unit cost — use "confirm" if genuinely unpriced, never leave blank`);
   if (isBlank(total)) fail(errors, label, `line ${i+1} (SKU "${sku}") is missing a Line total — use "confirm" if genuinely unpriced, never leave blank`);
  } else {
   const [sku, desc, qty] = l;
   if (isBlank(desc)) fail(errors, label, `line ${i+1} (SKU "${sku}") is missing a Description`);
   if (isBlank(qty)) fail(errors, label, `line ${i+1} (SKU "${sku}") is missing a Qty — this exact bug shipped 59 broken documents on 10 Aug 2026, do not let it recur`);
  }
 });
 if (kind==='po') {
  if (!Array.isArray(d.sums) || d.sums.length===0) fail(errors, label, 'has no sums block (Goods/Delivery/VAT/Total rows)');
  else d.sums.forEach(s => { if (isBlank(s[0]) || isBlank(s[1])) fail(errors, label, `a sums row is incomplete: ${JSON.stringify(s)}`); });
 }
}
(async()=>{
 const pos = JSON.parse(fs.readFileSync('batch_pos.json'));
 const slips = JSON.parse(fs.readFileSync('batch_slips.json'));

 const errors = [];
 pos.forEach(d => validateDoc(d, 'po', errors));
 slips.forEach(d => validateDoc(d, 'slip', errors));
 if (errors.length) {
  console.error(`\nVALIDATION FAILED — ${errors.length} issue(s) found across ${pos.length + slips.length} documents. NO FILES WRITTEN.\n`);
  errors.forEach(e => console.error(' - ' + e));
  console.error('\nFix the source data in batch_pos.json / batch_slips.json (or the upstream data that generated them) and re-run. Do not hand-edit a PDF or Word doc to patch this — fix the data and rebuild.\n');
  process.exit(1);
 }
 console.log(`Validation passed: ${pos.length + slips.length} documents, ${pos.reduce((n,d)=>n+d.lines.length,0) + slips.reduce((n,d)=>n+d.lines.length,0)} lines, all required fields present.`);

 for (const d of pos){ const doc=new Document({styles:{default:{document:{run:{font:'Calibri',size:20}}}},sections:[{properties:{page:{margin:{top:800,bottom:800,left:1000,right:1000}}},children:poDoc(d)}]}); fs.writeFileSync(d.file, await Packer.toBuffer(doc)); console.log('ok',d.file); }
 for (const d of slips){ const doc=new Document({styles:{default:{document:{run:{font:'Calibri',size:20}}}},sections:[{properties:{page:{margin:{top:800,bottom:800,left:1000,right:1000}}},children:slipDoc(d)}]}); fs.writeFileSync(d.file, await Packer.toBuffer(doc)); console.log('ok',d.file); }
})();
