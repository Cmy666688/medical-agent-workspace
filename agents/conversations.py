"""Account-owned durable conversations; authorization is checked on every operation."""
import json,os,uuid
from pathlib import Path
from datetime import datetime,timezone
from .family import identity_profile
from .sqlite_store import database

DB=Path(os.getenv('MEDICAL_RUNTIME_DIR',str(Path(__file__).resolve().parents[1]/'runtime')))/'conversations.sqlite'

def _initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,owner TEXT,title TEXT,created TEXT,updated TEXT,context TEXT,renamed INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS turns(conversation TEXT,request TEXT,payload TEXT,position INTEGER,PRIMARY KEY(conversation,request));
    CREATE INDEX IF NOT EXISTS conversations_owner_updated ON conversations(owner,updated DESC);
    CREATE INDEX IF NOT EXISTS turns_position ON turns(conversation,position);
    ''')

def _connect(): return database(DB,_initialize,'conversations-1')
def _owner(token):
    profile=identity_profile(token)
    if not profile.get('username'): raise PermissionError('请先登录账号')
    return profile['id']
def _owned(db,owner,key):
    row=db.execute('SELECT * FROM conversations WHERE id=? AND owner=?',(key,owner)).fetchone()
    if not row: raise PermissionError('对话不存在或无权访问')
    return row
def _now(): return datetime.now(timezone.utc).isoformat()

def create(token,key=None):
    owner=_owner(token); key=key or uuid.uuid4().hex; stamp=_now()
    with _connect() as db:
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,0)',(key,owner,'新对话',stamp,stamp,'{}'))
    return key

def listing(token,query=''):
    owner=_owner(token)
    with _connect() as db:
        return [dict(row) for row in db.execute('SELECT c.id,c.title,c.created,c.updated,(SELECT COUNT(*) FROM turns WHERE conversation=c.id) AS turn_count FROM conversations c WHERE owner=? AND title LIKE ? ORDER BY updated DESC LIMIT 100',(owner,'%'+query.strip()+'%'))]

def load(token,key):
    owner=_owner(token)
    with _connect() as db:
        row=_owned(db,owner,key)
        result=dict(row); result.pop('owner',None)
        result['context']=json.loads(result['context'])
        result['turns']=[json.loads(item['payload']) for item in db.execute('SELECT payload FROM turns WHERE conversation=? ORDER BY position',(key,))]
        return result

def exists(token,key):
    owner=_owner(token)
    with _connect() as db: return db.execute('SELECT 1 FROM conversations WHERE id=? AND owner=?',(key,owner)).fetchone() is not None

def get_context(token,key):
    owner=_owner(token)
    with _connect() as db: return json.loads(_owned(db,owner,key)['context'])

def append(token,key,turn,context=None):
    owner=_owner(token)
    if not isinstance(turn,dict) or not all(field in turn for field in ('request','question','answer','trace','evidences','conflicts')): raise ValueError('对话记录不完整')
    payload=json.dumps(turn,ensure_ascii=False)
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE'); row=_owned(db,owner,key)
        position=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM turns WHERE conversation=?',(key,)).fetchone()[0]
        inserted=db.execute('INSERT OR IGNORE INTO turns VALUES(?,?,?,?)',(key,turn['request'],payload,position)).rowcount
        if inserted:
            title=row['title']
            if not row['renamed'] and position==1: title=' '.join(turn['question'].split())[:40] or '新对话'
            db.execute('UPDATE conversations SET title=?,updated=? WHERE id=?',(title,_now(),key))
        if context is not None: db.execute('UPDATE conversations SET context=? WHERE id=?',(json.dumps(context,ensure_ascii=False),key))

def context(token,key,values):
    owner=_owner(token); payload=json.dumps(values,ensure_ascii=False,sort_keys=True)
    with _connect() as db:
        row=_owned(db,owner,key)
        if json.loads(row['context'])!=values: db.execute('UPDATE conversations SET context=? WHERE id=?',(payload,key))

def rename(token,key,title):
    owner=_owner(token); title=title.strip()
    if not title or len(title)>80: raise ValueError('对话名称需为 1～80 字')
    with _connect() as db:
        _owned(db,owner,key)
        db.execute('UPDATE conversations SET title=?,renamed=1,updated=? WHERE id=?',(title,_now(),key))

def delete(token,key):
    owner=_owner(token)
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE'); _owned(db,owner,key)
        db.execute('DELETE FROM turns WHERE conversation=?',(key,))
        db.execute('DELETE FROM conversations WHERE id=?',(key,))

def markdown(record):
    lines=['# '+record['title'],'']
    for turn in record['turns']:
        lines+=['## 我',turn['question'],'','## 问诊助手',turn['answer'],'']
    return '\n'.join(lines)
