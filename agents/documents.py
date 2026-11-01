"""Persistent supplemental chunks and restartable asynchronous indexing jobs."""
import hashlib,json,os,threading,time,uuid
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from .sqlite_store import database
from .lexical import KeywordIndex

ROOT=Path(__file__).resolve().parents[1]

def split_text(text,size=600,overlap=100):
    if size<1 or not 0<=overlap<size: raise ValueError('切片与重叠长度不正确')
    text=text.strip()
    return [text[start:start+size] for start in range(0,len(text),size-overlap) if text[start:start+size].strip()]

def read_upload(raw,name):
    if not raw or len(raw)>5*1024*1024: raise ValueError('文件需为 1 字节～5 MB')
    if Path(name).suffix.lower() not in ('.txt','.md','.pdf'): raise ValueError('仅支持 TXT、Markdown 和 PDF')
    if Path(name).suffix.lower()=='.pdf':
        import io
        try: from pypdf import PdfReader
        except ImportError: raise ValueError('PDF 支持需要安装 requirements.txt 中的 pypdf')
        reader=PdfReader(io.BytesIO(raw))
        if len(reader.pages)>300: raise ValueError('PDF 最多支持 300 页')
        pages=[(index+1,page.extract_text() or '') for index,page in enumerate(reader.pages)]
    else:
        try: pages=[(None,raw.decode('utf-8-sig'))]
        except UnicodeDecodeError: raise ValueError('文本文件请保存为 UTF-8 编码')
    if not any(text.strip() for _,text in pages): raise ValueError('未提取到文字，扫描版 PDF 需先进行 OCR')
    if sum(len(text) for _,text in pages)>300000: raise ValueError('文字过多，请分成多个文件上传')
    return pages

def _initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS sources(name TEXT PRIMARY KEY,digest TEXT,updated TEXT);
    CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,source TEXT,page INTEGER,content TEXT,vector BLOB);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,source TEXT,pages TEXT,digest TEXT,status TEXT,progress INTEGER,total INTEGER,error TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS revision(id INTEGER PRIMARY KEY,value INTEGER);
    INSERT OR IGNORE INTO revision VALUES(1,0);
    CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source);
    ''')

class DocumentStore:
    def __init__(self,path=None):
        self.path=Path(path or Path(os.getenv('MEDICAL_RUNTIME_DIR',str(ROOT/'runtime')))/'documents.sqlite')
        self.lock=threading.RLock(); self.version=-1; self.snapshot=[]; self.matrix=None
        self.keyword=None
    def connect(self): return database(self.path,_initialize,'documents-1')
    def revision(self):
        with self.connect() as db: return db.execute('SELECT value FROM revision WHERE id=1').fetchone()[0]
    def publish(self,name,digest,chunks,vectors):
        if len(chunks)!=len(vectors) or not chunks: raise ValueError('文档切片与向量不匹配')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT COUNT(*) FROM chunks WHERE source!=?',(name,)).fetchone()[0]
            if existing+len(chunks)>10000: raise ValueError('补充参考库最多支持 10000 个切片，请减少资料规模')
            db.execute('DELETE FROM chunks WHERE source=?',(name,))
            for index,((page,text),vector) in enumerate(zip(chunks,vectors)):
                key=hashlib.sha256((name+digest+str(index)).encode()).hexdigest()
                array=np.asarray(vector,dtype=np.float32)
                norm=float(np.linalg.norm(array))
                if array.ndim!=1 or not np.isfinite(array).all() or norm<=0: raise ValueError('向量数据无效')
                db.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(key,name,page,text,(array/norm).tobytes()))
            db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?)',(name,digest,datetime.now(timezone.utc).isoformat()))
            db.execute('UPDATE revision SET value=value+1 WHERE id=1')
    def info(self):
        with self.connect() as db:
            return dict(chunks=db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0],sources=[dict(row) for row in db.execute('SELECT name,updated FROM sources ORDER BY updated DESC')])
    def search(self,vector,k,threshold):
        with self.lock:
            version=self.revision()
            if version!=self.version:
                with self.connect() as db: rows=db.execute('SELECT * FROM chunks').fetchall()
                self.snapshot=[dict(row) for row in rows]
                self.matrix=np.vstack([np.frombuffer(row['vector'],dtype=np.float32) for row in rows]) if rows else None
                self.keyword=KeywordIndex([{'_id':{'$oid':row['id']},'name':row['source'],'desc':row['content']} for row in rows]) if rows else None
                self.version=version
            if self.matrix is None: return []
            query=np.asarray(vector,dtype=np.float32)
            if self.matrix.shape[1]!=len(query): raise ValueError('补充文档向量维度与模型不同，请重新索引资料')
            scores=self.matrix@query
            results=[]
            for index in np.argsort(-scores)[:k]:
                row=self.snapshot[index]; score=float(scores[index])
                if score<threshold: continue
                source=row['source']+(f" · 第 {row['page']} 页" if row['page'] else '')
                results.append(dict(doc_id=row['id'],name=row['source'],content=row['content'],source=source,page=row['page'],score=score,symptoms=[]))
            return results
    def keyword_ids(self,query,k=20):
        with self.lock: return self.keyword.search(query,k) if self.keyword else []

class IndexJobs:
    def __init__(self,get_service,store=None):
        self.store=store or DocumentStore(); self.get_service=get_service
        with self.store.connect() as db: db.execute("UPDATE jobs SET status='queued' WHERE status='running'")
        self.wake=threading.Event()
        threading.Thread(target=self._work,daemon=True,name='document-indexer').start()
    def submit(self,name,pages):
        name=Path(name).name[:150]
        if not name: raise ValueError('请提供资料名称')
        payload=json.dumps(pages,ensure_ascii=False); digest=hashlib.sha256(payload.encode()).hexdigest()
        chunks=sum(len(split_text(text)) for _,text in pages)
        if not chunks or chunks>1000: raise ValueError('单份资料需为 1～1000 个切片')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute("SELECT id FROM jobs WHERE source=? AND digest=? AND status IN ('queued','running','completed') ORDER BY created DESC LIMIT 1",(name,digest)).fetchone()
            source=db.execute('SELECT digest FROM sources WHERE name=?',(name,)).fetchone()
            if existing and (source and source['digest']==digest or db.execute("SELECT status FROM jobs WHERE id=?",(existing['id'],)).fetchone()[0]!='completed'): return existing['id']
            key=uuid.uuid4().hex
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(key,name,payload,digest,'queued',0,chunks,'',datetime.now(timezone.utc).isoformat()))
        self.wake.set(); return key
    def jobs(self):
        with self.store.connect() as db: return [dict(row) for row in db.execute('SELECT id,source,status,progress,total,error FROM jobs ORDER BY created DESC LIMIT 20')]
    def _work(self):
        while True:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                job=db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if job: db.execute("UPDATE jobs SET status='running' WHERE id=?",(job['id'],))
            if not job:
                self.wake.wait(2); self.wake.clear(); continue
            try:
                chunks=[(page,chunk) for page,text in json.loads(job['pages']) for chunk in split_text(text)]
                service=self.get_service(); vectors=[]
                for start in range(0,len(chunks),16):
                    vectors.extend(service.embed_texts([text for _,text in chunks[start:start+16]]))
                    with self.store.connect() as db: db.execute('UPDATE jobs SET progress=? WHERE id=?',(len(vectors),job['id']))
                self.store.publish(job['source'],job['digest'],chunks,vectors)
                with self.store.connect() as db: db.execute("UPDATE jobs SET status='completed',pages='[]' WHERE id=?",(job['id'],))
            except Exception as exc:
                with self.store.connect() as db: db.execute("UPDATE jobs SET status='failed',error=? WHERE id=?",(type(exc).__name__,job['id']))
