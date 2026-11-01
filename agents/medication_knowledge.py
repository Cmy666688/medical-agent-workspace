"""Deterministic, read-only product lookup and source-bounded interaction checks."""
import itertools,json,os,re,sqlite3
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
from .drug_data import DEFAULT_DB,VERSION,norm,canonical,dumps,TFDA_URL,DDI_URL,FDA_URL

LEVELS={'Major':'较高等级（Major）','Moderate':'中等等级（Moderate）','Minor':'较低等级（Minor）','Unknown':'等级未知（Unknown）'}
NO_MEDICATION={'无','未用药','没有用药','目前未用药','none','no medications'}

def product(row):
    item=dict(row)
    for key in ('components','attachments','appearance'): item[key]=json.loads(item[key])
    if item['cancelled']: status='已标注销或停止；仅供历史资料核查'
    else:
        try:
            end=datetime.strptime(item['valid_until'],'%Y/%m/%d').date()
            today=datetime.now(timezone(timedelta(hours=8))).date()
            status='记录有效期已过' if end<today else '未标注销，记录在有效期内'
        except ValueError: status='有效期未知'
    item.update(registry_status=status,source=TFDA_URL,region='台湾 TFDA，非大陆批准记录')
    return item

class DrugKnowledge:
    def __init__(self,path=None): self.path=Path(path or os.getenv('MEDICAL_DRUG_DB',str(DEFAULT_DB)))
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        db.row_factory=sqlite3.Row
        try: yield db
        finally: db.close()
    def info(self):
        if not self.path.exists(): return dict(ready=False,reason='not_installed')
        try:
            with self.connect() as db: info=json.loads(db.execute("SELECT value FROM metadata WHERE key='info'").fetchone()[0])
            return dict(info,ready=info.get('schema')==VERSION)
        except (sqlite3.Error,TypeError,ValueError): return dict(ready=False,reason='unavailable')

    def _resolve(self,db,text):
        key=norm(text)
        direct=db.execute('SELECT p.* FROM products p JOIN terms t ON t.product=p.id WHERE t.term=? GROUP BY p.id LIMIT 40',(key,)).fetchall()
        if direct:
            all_components=db.execute('SELECT DISTINCT p.components FROM products p JOIN terms t ON t.product=p.id WHERE t.term=?',(key,)).fetchall()
            groups={tuple(json.loads(row[0])) for row in all_components}
            if len(groups)!=1 or not next(iter(groups)):
                return dict(input=text,status='ambiguous',components=[],products=[product(row) for row in direct[:5]],suggestions=[row['id'] for row in direct[:8]])
            return dict(input=text,status='product',components=list(next(iter(groups))),products=[product(row) for row in direct[:5]],suggestions=[],more_products=len(direct)>5)
        name=db.execute('SELECT canonical FROM drug_names WHERE term=?',(key,)).fetchone()
        if name:
            component=name[0]
            rows=db.execute('SELECT p.* FROM products p JOIN component_products c ON c.product=p.id WHERE c.component=? ORDER BY (p.cancelled != ""),p.valid_until DESC,p.id LIMIT 5',(component,)).fetchall()
            return dict(input=text,status='ingredient',components=[component],products=[product(row) for row in rows],suggestions=[],note='仅匹配通用名/成分；列出含该成分的 TFDA 候选，可能包含复方，不能据此确认你服用的剂型、规格或具体产品。')
        escaped=key.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        suggestions=db.execute("SELECT DISTINCT p.id,p.name_zh FROM terms t JOIN products p ON p.id=t.product WHERE t.term LIKE ? ESCAPE '\\' LIMIT 8",('%'+escaped+'%',)).fetchall() if len(key)>=2 else []
        return dict(input=text,status='not_found',components=[],products=[],suggestions=[row['id'] for row in suggestions],suggestion_names=[row['name_zh'] for row in suggestions])

    def check(self,text,allergies=''):
        info=self.info()
        base=dict(current_medications=text,allergies=allergies,missing=[label for value,label in ((text,'当前用药'),(allergies,'过敏史')) if not value.strip()],knowledge_status='ready' if info['ready'] else 'not_installed',knowledge_info=info,mode='TFDA + openFDA + DDInter 本地可追溯核对',items=[],interactions=[],duplicates=[],drug_evidences=[])
        base['recommendation']='完成已识别药名的资料匹配。覆盖范围有限，未命中不代表安全；过敏及交叉过敏仍需核实，不生成处方、剂量或停药建议。'
        if not info['ready']:
            base['recommendation']='药品资料索引尚未就绪，已保留你提供的用药和过敏信息；当前无法执行资料及相互作用匹配。'
            return base
        if not text.strip(): return base
        if norm(text) in {norm(value) for value in NO_MEDICATION}:
            base['no_medications_reported']=True
            return base
        names=list(dict.fromkeys(value.strip() for value in re.split(r'[\n;；,，、]+',text) if value.strip()))
        if len(names)>8:
            base['input_error']='每次最多核对 8 种药物，请分批填写。'
            return base
        with self.connect() as db:
            items=[self._resolve(db,name) for name in names]
            for item in items:
                item['labels']=[]
                if not item['components']: continue
                rows=db.execute('SELECT * FROM labels WHERE ingredient_key=? ORDER BY effective DESC LIMIT 3',(dumps(sorted(item['components'])),)).fetchall()
                for row in rows:
                    label=dict(row)
                    for key in ('names','sections','routes'): label[key]=json.loads(label[key])
                    label['sections']={key:['\n'.join(paragraphs)[:1800]] for key,paragraphs in label['sections'].items()}
                    label['source']='https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid='+label['set_id'] if label['set_id'] else FDA_URL
                    item['labels'].append(label)
                    for section,paragraphs in label['sections'].items():
                        base['drug_evidences'].append(dict(doc_id='openfda:'+label['id']+':'+section,name='openFDA '+','.join(label['names'])+' / '+section,content='\n'.join(paragraphs),source=label['source'],effective=label['effective']))
            base['items']=items
            for first,second in itertools.combinations(items,2):
                if not first['components'] or not second['components']:
                    base['interactions'].append(dict(drugs=[first['input'],second['input']],status='unresolved',records=[],uncovered=0));continue
                shared=set(first['components'])&set(second['components'])
                if shared: base['duplicates'].append(dict(drugs=[first['input'],second['input']],components=sorted(shared)))
                records=[]; uncovered=0
                for a,b in itertools.product(first['components'],second['components']):
                    if a==b: continue
                    a,b=sorted((a,b))
                    found=db.execute('SELECT * FROM ddi WHERE a=? AND b=?',(a,b)).fetchall()
                    if not found: uncovered+=1
                    for row in found:
                        value=dict(row); value.update(level_label=LEVELS.get(row['level'],'未识别等级：'+row['level']),source=DDI_URL)
                        if value not in records: records.append(value)
                for record in records:
                    base['drug_evidences'].append(dict(doc_id='ddinter:'+record['id_a']+':'+record['id_b']+':'+record['level'],name='DDInter 药物对记录',content=record['name_a']+' / '+record['name_b']+'；原始记录等级：'+record['level']+'。此 CSV 不含机制或处置建议，未命中不等于安全。',source=DDI_URL))
                base['interactions'].append(dict(drugs=[first['input'],second['input']],status='matched' if records else ('duplicate_only' if shared and not uncovered else 'not_covered'),records=records,uncovered=uncovered))
        # Do not copy every full label into prompts/history; keep short exact excerpts.
        ordered=sorted(base['drug_evidences'],key=lambda row:not row['doc_id'].startswith('ddinter:'))
        base['drug_evidences']=[dict(item,content=item['content'][:1800]) for item in ordered[:12]]
        return base
