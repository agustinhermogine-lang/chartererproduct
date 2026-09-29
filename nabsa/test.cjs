const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');

const scripts=[...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
for(const [,attrs,body] of scripts)if(!attrs.includes('application/json'))new vm.Script(body);
const dataBlock=(text,id)=>text.match(new RegExp('<script[^>]*id="'+id+'"[^>]*>([\\s\\S]*?)<\\/script>'))[1];

class Element{
  constructor(tag='div'){this.tag=tag;this.children=[];this.attributes={};this.style={};this.dataset={};this.listeners={};this._value=null;this._text='';this.className='';this.classList={toggle(){}};}
  get options(){return this.children;}
  get value(){if(this.tag==='select')return this._value===null?(this.children[0]?.value||''):(this.children.some(c=>c.value===this._value)?this._value:'');return this._value||'';}
  set value(v){this._value=String(v);}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
  set textContent(t){this._text=String(t);this.children=[];}
  append(...nodes){for(let n of nodes){if(typeof n==='string'){let e=new Element();e.textContent=n;n=e;}if(n.parentElement)n.remove();n.parentElement=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children.forEach(c=>c.parentElement=null);this.children=[];this._text='';this._value=null;this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=String(v);if(k==='class')this.className=v;}
  getAttribute(k){return this.attributes[k]??null;}
  removeAttribute(k){delete this.attributes[k];}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.parentElement=null;}
  querySelectorAll(selector){return this.children.filter(e=>e.className.split(' ').includes(selector.slice(1)));}
  addEventListener(type,fn){this.listeners[type]=fn;}
}
const elements=new Map();
for(const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g))elements.set(match[2],new Element(match[1]));
const get=id=>{assert(elements.has(id),'Missing '+id);return elements.get(id);};
for(const id of ['cw-data','cw-tonnage-data','cw-iso','cw-shipper-data'])get(id).textContent=dataBlock(html,id);
const option=(select,v)=>{const e=new Element('option');e.value=v;select.append(e);};
['country','product','charterer','shipper'].forEach(v=>option(get('cw-mode'),v));
['auto','month','year'].forEach(v=>option(get('cw-grain'),v));
get('cw-from').value='2022-01';get('cw-to').value='2026-07';
for(const id of ['cw-destination','cw-charterer','cw-product']){const label=new Element('label');label.append(get(id));get('cw-search-controls').append(label);}
get('cw-shipper-control').append(get('cw-shipper'));get('cw-search-controls').append(get('cw-shipper-control'));
const svg=new Element('svg'),frame=new Element(),composition=new Element();
for(const id of new Set(Object.values(JSON.parse(dataBlock(html,'cw-iso'))).filter(Boolean))){const path=new Element('path');path.className='land';path.dataset.iso=id;svg.append(path);}
const root=get('charterer-world-map');
root.querySelector=selector=>selector==='svg'?svg:selector==='.map-frame'?frame:selector==='.composition-grid'?composition:get(selector.slice(1));
const document={getElementById:get,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),createTextNode:text=>{const e=new Element();e.textContent=text;return e;}};
const script=scripts.find(([,attrs,body])=>body.includes('const aliasGroups=')&&!attrs.includes('application/json'))[2];
const change=(id,v)=>{get(id).value=v;get(id).listeners.change();};
const tons=JSON.parse(dataBlock(html,'cw-tonnage-data'));
const countries=[...new Set(JSON.parse(dataBlock(html,'cw-data')).map(r=>r[1]))].sort();
const format=v=>new Intl.NumberFormat('es-AR',{maximumFractionDigits:3}).format(v)+' t';
(async()=>{
await vm.runInNewContext(script,{document,Intl,Map,Set,console,Array});
change('cw-to',process.argv[4]);
const sum=rs=>rs.reduce((a,r)=>a+r[r.length-1],0);
assert.equal(get('cw-total-tons').textContent,format(sum(tons)));
change('cw-product','SBM');
assert.equal(get('cw-total-tons').textContent,format(sum(tons.filter(r=>r[2]==='SBM'))));
change('cw-grain','month');
assert.equal(get('cw-evolution-table').children.length,new Set(tons.filter(r=>r[2]==='SBM').map(r=>r[3])).size);
assert.equal(get('cw-latest-change').textContent,'—');
change('cw-mode','shipper');change('cw-shipper','__ALL__');change('cw-destination','__ALL__');
const rows=JSON.parse(dataBlock(html,'cw-shipper-data'));
assert.equal(get('cw-to').value,process.argv[4]);
assert.equal(get('cw-total-tons').textContent,format(sum(rows)));
change('cw-from',process.argv[4]);change('cw-product','SBM');
assert.equal(get('cw-total-tons').textContent,format(sum(rows.filter(r=>r[3]==='SBM'&&r[4]>=process.argv[4]))));
change('cw-from','2026-08');change('cw-to','2026-08');change('cw-product','');
assert.equal(get('cw-total-tons').textContent,format(7482076.218));
change('cw-from','2026-07');change('cw-to','2026-07');
assert.equal(get('cw-total-tons').textContent,format(8642623.637));
const baselineHtml=fs.readFileSync(process.argv[3],'utf8');
const beforeRows=JSON.parse(dataBlock(baselineHtml,'cw-shipper-data')).filter(r=>r[4]<'2026-07');
assert.deepEqual(rows.filter(r=>r[4]<'2026-07'),beforeRows);
console.log('PASS NABSA totals, SBM, shipper integration, date extension and missing-month display');
})().catch(e=>{console.error(e);process.exitCode=1;});
