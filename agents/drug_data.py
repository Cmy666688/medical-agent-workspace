"""Build a source-attributed medication index; no patient records or model calls."""
import csv,hashlib,io,json,os,re,sqlite3,unicodedata,zipfile
from datetime import datetime,timezone
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DB=ROOT/'data'/'medication'/'knowledge.sqlite'
VERSION=2
TFDA_URL='https://data.gov.tw/dataset/9122'
DDI_URL='https://ddinter2.scbdd.com/download/'
FDA_URL='https://open.fda.gov/apis/drug/label/'

@lru_cache(maxsize=1)
def converter():
    from opencc import OpenCC
    return OpenCC('t2s')

@lru_cache(maxsize=100000)
def norm(text):
    text=converter().convert(unicodedata.normalize('NFKC',str(text or '')).casefold())
    return re.sub(r'[\s\"“”「」『』〝〞]+','',text).strip()

# Small, explicit terminology map only. It does not map brands, strengths, routes,
# indications or classes to ingredients; unknown names remain unresolved.
ALIASES={
 '布洛芬':'ibuprofen','华法林':'warfarin','二甲双胍':'metformin','西咪替丁':'cimetidine',
 '阿卡波糖':'acarbose','地高辛':'digoxin','阿莫西林':'amoxicillin',
 '对乙酰氨基酚':'acetaminophen','对乙酰胺基酚':'acetaminophen','扑热息痛':'acetaminophen',
 'paracetamol':'acetaminophen','metformin hcl':'metformin','metformin hydrochloride':'metformin',
 'warfarin sodium':'warfarin','amoxicillin trihydrate':'amoxicillin','amoxicillin (trihydrate)':'amoxicillin',
}

@lru_cache(maxsize=30000)
def canonical(name):
    # Preserve formulation/route qualifiers such as (topical) and (systemic).
    # Only the explicit TFDA equivalence notation is removed.
    name=re.sub(r'\s*\(EQ TO [^)]*\)','',str(name or ''),flags=re.IGNORECASE).strip()
    mapped={norm(k):v for k,v in ALIASES.items()}
    return norm(mapped.get(norm(name),name))

def ingredients(text):
    return sorted({canonical(part) for part in re.split(r';;|;|\n',str(text or '')) if canonical(part)})

def dumps(value): return json.dumps(value,ensure_ascii=False)

def build(source=None,target=None):
    source=Path(source or ROOT/'data'/'external')
    target=Path(target or DEFAULT_DB)
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    files={row['path']:row for row in manifest['files']}
    used=[]
    def checked(name):
        raw=(source/name).read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=files[name]['sha256']: raise ValueError('来源文件校验失败：'+name)
        used.append(dict(path=name,sha256=digest,url=files[name]['url']))
        return raw
    def zipped(name):
        with zipfile.ZipFile(io.BytesIO(checked(name))) as archive:
            member=next(item for item in archive.namelist() if item.endswith('.json'))
            if archive.getinfo(member).file_size>100*1024*1024: raise ValueError('来源文件过大')
            return json.loads(archive.read(member).decode('utf-8-sig'))
    products=zipped('tfda/drug_licenses.json.zip')
    attachments={}
    for row in zipped('tfda/labels_and_packages.json.zip'):
        group=attachments.setdefault(row['許可證字號'],{})
        for field in ('仿單圖檔連結','外盒圖檔連結'):
            values=group.setdefault(field,[])
            if row.get(field) and row[field] not in values: values.append(row[field])
    appearances={row['許可證字號']:row for row in zipped('tfda/appearance.json.zip')}
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(target.name+'.building')
    if temporary.exists(): temporary.unlink()
    db=sqlite3.connect(temporary)
    try:
        db.executescript('''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE products (id TEXT PRIMARY KEY, name_zh TEXT, name_en TEXT, components TEXT, ingredient_text TEXT, form TEXT, valid_until TEXT, cancelled TEXT, attachments TEXT, appearance TEXT);
CREATE TABLE terms (term TEXT, product TEXT, kind TEXT, PRIMARY KEY(term,product,kind));
CREATE INDEX terms_lookup ON terms(term);
CREATE TABLE component_products (component TEXT, product TEXT, PRIMARY KEY(component,product));
CREATE TABLE drug_names (term TEXT PRIMARY KEY, canonical TEXT);
CREATE TABLE ddi (a TEXT,b TEXT,level TEXT,id_a TEXT,id_b TEXT,name_a TEXT,name_b TEXT,PRIMARY KEY(a,b,level));
CREATE TABLE labels (id TEXT PRIMARY KEY, ingredient_key TEXT, names TEXT, sections TEXT, effective TEXT, set_id TEXT, routes TEXT);
CREATE INDEX labels_ingredient ON labels(ingredient_key);
''')
        for row in products:
            key=row['許可證字號']; components=ingredients(row.get('主成分略述'))
            db.execute('INSERT OR IGNORE INTO products VALUES (?,?,?,?,?,?,?,?,?,?)',(key,row.get('中文品名') or '',row.get('英文品名') or '',dumps(components),row.get('主成分略述') or '',row.get('劑型') or '',row.get('有效日期') or '',row.get('註銷狀態') or '',dumps(attachments.get(key,{})),dumps(appearances.get(key,{}))))
            for name,kind in [(key,'license'),(row.get('中文品名'),'product'),(row.get('英文品名'),'product')]:
                if name: db.execute('INSERT OR IGNORE INTO terms VALUES (?,?,?)',(norm(name),key,kind))
            for component in components:
                db.execute('INSERT OR IGNORE INTO component_products VALUES (?,?)',(component,key))
                db.execute('INSERT OR IGNORE INTO drug_names VALUES (?,?)',(component,component))
        for row in csv.DictReader(io.StringIO(checked('ddinter2/code_A.csv').decode('utf-8-sig'))):
            a,b=canonical(row['Drug_A']),canonical(row['Drug_B'])
            id_a,id_b=row['DDInterID_A'],row['DDInterID_B'];name_a,name_b=row['Drug_A'],row['Drug_B']
            if a>b: a,b=b,a;id_a,id_b=id_b,id_a;name_a,name_b=name_b,name_a
            db.execute('INSERT OR IGNORE INTO ddi VALUES (?,?,?,?,?,?,?)',(a,b,row['Level'],id_a,id_b,name_a,name_b))
            for name in (row['Drug_A'],row['Drug_B']): db.execute('INSERT OR REPLACE INTO drug_names VALUES (?,?)',(norm(name),canonical(name)))
        for filename in files:
            if not filename.startswith('openfda/') or not filename.endswith('.json'): continue
            for row in json.loads(checked(filename))['results']:
                names=row.get('openfda',{}).get('generic_name',[])
                components=sorted({canonical(name) for name in names if name})
                # Ambiguous multi-ingredient generic strings are not split on '/'
                # or guessed from substrings; unsupported combinations stay unmatched.
                sections={key:row[key] for key in ('boxed_warning','contraindications','drug_interactions','warnings_and_cautions','warnings','do_not_use','ask_doctor','stop_use') if row.get(key)}
                db.execute('INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?)',(row['id'],dumps(components),dumps(names),dumps(sections),row.get('effective_time',''),row.get('set_id',''),dumps(row.get('openfda',{}).get('route',[]))))
                for name in names: db.execute('INSERT OR REPLACE INTO drug_names VALUES (?,?)',(norm(name),canonical(name)))
        for name,component in ALIASES.items(): db.execute('INSERT OR REPLACE INTO drug_names VALUES (?,?)',(norm(name),canonical(component)))
        counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('products','labels','ddi')}
        info=dict(schema=VERSION,built_at=datetime.now(timezone.utc).isoformat(),source_retrieved_at=manifest['retrieved_at'],counts=dict(counts,tfda_source_rows=len(products)),files=used,coverage=dict(tfda_region='TW',openfda='5 种通用名查询样本；不是完整药库',ddinter='A 类相关药物对子集；不是全库'),licenses=dict(TFDA='政府資料開放授權條款第1版',openFDA='CC0 原则及第三方内容例外',DDInter='CC BY-NC-SA 4.0；非商业研究用途'))
        db.execute('INSERT INTO metadata VALUES (?,?)',('info',dumps(info)))
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('药品索引完整性检查失败')
    except BaseException:
        db.close();temporary.unlink(missing_ok=True);raise
    db.close();os.replace(temporary,target)
    return info

if __name__=='__main__': print(dumps(build()))
