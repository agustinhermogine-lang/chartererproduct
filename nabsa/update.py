from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal
from datetime import datetime
import json,re,hashlib,urllib.request,sys,html
import pdfplumber
import base64,gzip,tempfile,subprocess,os
ROOT=Path(__file__).resolve().parent.parent
state_path=ROOT/'nabsa/state.json'
bundle=json.loads(state_path.read_text(encoding='utf-8'))
out=ROOT/'index.html'
current=out.read_text(encoding='utf-8')
assert hashlib.sha256(current.encode()).hexdigest()==bundle['output_sha256'], 'index.html changed outside the importer; merge template changes first'
temporary=tempfile.TemporaryDirectory()
scratch=Path(temporary.name)
url='https://www.nabsa.com.ar/assets/vessels_sailed_update.pdf'
pdf=Path(sys.argv[sys.argv.index('--pdf')+1]) if '--pdf' in sys.argv else scratch/'latest.pdf'
if '--pdf' not in sys.argv:
    request=urllib.request.Request(url,headers={'User-Agent':'ChartererProduct NABSA daily updater','Cache-Control':'no-cache'})
    body=urllib.request.urlopen(request,timeout=90).read()
    assert body.startswith(b'%PDF'), 'NABSA did not return a PDF'
    pdf.write_bytes(body)
products={'CORN':'MAIZE','MAIZE':'MAIZE','WHEAT':'WHEAT','SOYA BEAN':'SOYA','SOYBEAN':'SOYA','SOYBEANS':'SOYA','BARLEY':'BARLEY','SORGHUM':'SORGHUM','SOYBEANMEAL':'SBM','SOYBEANMEAL HIPRO':'SBM','SOYBEAN MEAL':'SBM','SOYABEANMEAL PELLETS':'SBM'}
records=[]; textcount=0
with pdfplumber.open(pdf) as doc:
    heading=doc.pages[0].extract_text()
    date=datetime.strptime(re.search(r'BUENOS AIRES, (\d{2}-[A-Za-z]{3}-\d{2})',heading)[1],'%d-%b-%y').date().isoformat()
    for page in doc.pages:
        textcount+=len(re.findall(r'\bSAILED\s+\d{2}/\d{2}/\d{4}',page.extract_text()))
        for table in page.extract_tables():
            for row in table:
                if len(row)!=11 or row[3]!='SAILED':continue
                row=[' '.join((x or '').split()) for x in row]
                row[4]=datetime.strptime(row[4],'%d/%m/%Y').date().isoformat()
                assert row[4]<=date, 'Future sailing'
                records.append(row)
assert records and len(records)==textcount,(len(records),textcount)
months={r[4][:7] for r in records}
assert min(r[4][-2:] for r in records)=='01', 'Report may not be cumulative from month start'
existing=bundle['snapshots']
assert date>=max(x['date'] for x in existing.values()), 'NABSA returned an older report'
for month in months:
    old=existing.get(month)
    assert not old or date>=old['date'], 'Report older than stored snapshot'
    existing[month]={'date':date,'url':url,'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'rows':[r for r in records if r[4].startswith(month)]}
base=gzip.decompress(base64.b64decode(bundle['baseline_gzip_base64'])).decode('utf-8').replace('\r\n','\n')
def block(id):return json.loads(re.search(r'id="'+id+r'"[^>]*>(.*?)</script>',base,re.S)[1])
cutoff=max(r[4] for r in block('cw-shipper-data'))
replaced={'2026-07'} if existing.get('2026-07',{}).get('source') else set()
baseline_tons=[r for r in block('cw-tonnage-data') if r[3] not in replaced]
baseline_shippers=[r for r in block('cw-shipper-data') if r[4] not in replaced]
baseline_relations=sorted({tuple(r[:3]) for r in baseline_tons}) if replaced else block('cw-data')
base_blocks={'cw-tonnage-data':baseline_tons,'cw-shipper-data':baseline_shippers,'cw-data':baseline_relations}
aliases=bundle['shipper_aliases']
def key(n):return re.sub(r'\s+(SA|SACI|SRL)$','',re.sub(r'\s+',' ',n.upper().replace('.','')).strip())
namekeys=defaultdict(set)
for n,c in aliases.items():namekeys[key(n)].add(c)
def shipper(n):
    if n=='NOT AVAILABLE':return 'UNKNOWN'
    options=namekeys.get(key(n),set())
    return next(iter(options)) if len(options)==1 else n
sh=defaultdict(Decimal);tn=defaultdict(Decimal);counts=Counter();newrows=[]
for month,snapshot in sorted(existing.items()):
    if month<=cutoff and month not in replaced:continue
    for r in snapshot['rows']:
        product=products.get(r[6])
        if not product or r[7]!='ARGENTINA':continue
        number=re.sub(r'\s+','',r[5])
        assert re.fullmatch(r'(?:\d+|\d{1,3}(?:\.\d{3})+),\d+',number),r
        tonnes=Decimal(number.replace('.','').replace(',','.'));assert tonnes>0
        ch=r[10] if r[10]!='NOT AVAILABLE' else 'UNKNOWN'
        dest=r[8] if r[8]!='NOT AVAILABLE' else 'UNKNOWN'
        sh[shipper(r[9]),ch,dest,product,month]+=tonnes
        tn[ch,dest,product,month]+=tonnes
        counts[product]+=1;newrows.append(r)
assert newrows,'No eligible records'
end=max(existing); relations=sorted({k[:3] for k in tn})
s=base
for id,extra in [('cw-shipper-data',[[*k,float(v)] for k,v in sorted(sh.items())]),('cw-tonnage-data',[[*k,float(v)] for k,v in sorted(tn.items())]),('cw-data',relations)]:
    pattern=r'(<script[^>]*id="'+id+r'"[^>]*>)(.*?)(</script>)';m=re.search(pattern,s,re.S)
    payload=json.dumps(base_blocks[id]+extra,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    s=s[:m.start(2)]+payload+s[m.end(2):]
s=s.replace("'BARLEY','SORGHUM'];","'BARLEY','SORGHUM','SBM'];").replace("SORGHUM:'Sorgo'}","SORGHUM:'Sorgo',SBM:'Harina de soja argentina'}")
s=s.replace('value="2026-07"','value="'+end+'"').replace('max="2026-07"','max="'+end+'"').replace("'2026-07'","'"+end+"'")
s=s.replace('2022–2026 · Hoja TONS BY CARTERER','2022–'+end[:4]+' · Excel + NABSA').replace('Histórico completo de DATOS','DATOS + NABSA')
s=s.replace('2022–2026','2022–'+end[:4])
allmonths=[];y,m=map(int,cutoff.split('-'))
while f'{y:04}-{m:02}'<end:
    m+=1
    if m==13:y+=1;m=1
    allmonths.append(f'{y:04}-{m:02}')
missing=[m for m in allmonths if m not in existing]
note=f'NABSA: reporte {date}. Datos diarios provisorios, sujetos a revisión. Coordinator = shipper. Nuevos registros: origen ARGENTINA; harina de soja disponible únicamente desde los reportes NABSA incorporados. Histórico Excel hasta {cutoff}.'
if missing:note+=' Períodos pendientes, no equivalen a cero: '+', '.join(missing)+'.'
if replaced:note+=' Julio 2026 sustituido por el acumulado NABSA aportado por el usuario (01 al 31 de julio, origen argentino); no se suma al julio del Excel.'
if '2026-08' in existing and existing['2026-08'].get('source'):note+=' Agosto 2026 incorporado del acumulado mensual aportado por el usuario (01 al 31 de agosto).'
note+=' Los acumulados incluyen solo períodos disponibles; no comparar el último período parcial con uno completo.'
s=s.replace('<p id="cw-search-help"', '<p id="cw-nabsa-status" class="text-small text-muted">'+html.escape(note)+'</p>\n<p id="cw-search-help"')
needle="      const keys=grain==='year'?[...new Set(monthRange(from,to).map(m=>m.slice(0,4)))]:monthRange(from,to);"
assert needle in s
s=s.replace(needle,"      const coveredMonths=monthRange(from,to).filter(m=>!"+json.dumps(missing)+".includes(m)&&(!productSelect.value||productSelect.value!=='SBM'||m>='"+min(existing)+"'));\n      const keys=grain==='year'?[...new Set(coveredMonths.map(m=>m.slice(0,4)))]:coveredMonths;")
# Suppress period-over-period changes with incomplete coverage instead of implying comparability.
s=s.replace("const requested=root.querySelector('#cw-grain').value;","const requested=root.querySelector('#cw-grain').value;")
s=s.replace("      renderShipperSummary(from,to);","      renderShipperSummary(from,to);\n      if(to>='"+min(existing)+"'){root.querySelector('#cw-latest-change').textContent='—';root.querySelector('#cw-grain-note').textContent+=' · datos parciales NABSA';tbody.children&&Array.from(tbody.children).forEach(tr=>{tr.children[2].textContent='—';});}")
# Validate the generated data against every retained source snapshot before writing.
def data_from(text, identifier):
    return json.loads(re.search(r'id="'+identifier+r'"[^>]*>(.*?)</script>',text,re.S)[1])
for identifier,month_column,product_column in [('cw-tonnage-data',3,2),('cw-shipper-data',4,3)]:
    generated=data_from(s,identifier)
    assert [r for r in generated if r[month_column]<'2026-07']==[r for r in data_from(base,identifier) if r[month_column]<'2026-07'], 'Historical rows changed'
    for month,snapshot in existing.items():
        if month<=cutoff and month not in replaced:continue
        expected=defaultdict(Decimal)
        for row in snapshot['rows']:
            if row[7]=='ARGENTINA' and row[6] in products:
                expected[products[row[6]]]+=Decimal(''.join(row[5].split()).replace('.','').replace(',','.'))
        actual=defaultdict(Decimal)
        for row in generated:
            if row[month_column]==month:actual[row[product_column]]+=Decimal(str(row[-1]))
        assert set(actual)==set(expected), (month,actual,expected)
        assert all(abs(actual[p]-expected[p])<Decimal('0.000001') for p in expected), (month,actual,expected)
assert 'Todos los países' in s and "SBM:'Harina de soja argentina'" in s
candidate=scratch/'index.html';candidate.write_text(s,encoding='utf-8')
baseline=scratch/'base.html';baseline.write_text(base,encoding='utf-8')
subprocess.run(['node',str(ROOT/'nabsa/test.cjs'),str(candidate),str(baseline),end],check=True)
digest=hashlib.sha256(s.encode()).hexdigest()
bundle['output_sha256']=digest
bundle['report']={'report_date':date,'source_rows':len(records),'eligible_rows':len(newrows),'products':dict(counts),'snapshot_tons':float(sum(sh.values())),'missing_months':missing,'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()}
serialized=json.dumps(bundle,ensure_ascii=False,indent=2)+'\n'
if current!=s:out.write_text(s,encoding='utf-8',newline='\n')
if state_path.read_text(encoding='utf-8')!=serialized:state_path.write_text(serialized,encoding='utf-8',newline='\n')
print(json.dumps(bundle['report']))
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as summary:
        summary.write(f"NABSA report: **{date}**. {len(records)} source rows. Validated historical preservation, monthly reconciliation and UI filters. Output SHA256: `{digest}`.\n")
