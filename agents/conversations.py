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
    CREATE TABLE IF NOT EXISTS consultation_card_versions(
        conversation TEXT, version INTEGER, created TEXT, reason TEXT, payload TEXT,
        PRIMARY KEY(conversation,version));
    CREATE TABLE IF NOT EXISTS consultation_card_inputs(
        conversation TEXT, request TEXT, original TEXT,
        PRIMARY KEY(conversation,request));
    CREATE TABLE IF NOT EXISTS conversation_preferences(owner TEXT PRIMARY KEY,active TEXT);
    CREATE TABLE IF NOT EXISTS conversation_continuations(conversation TEXT PRIMARY KEY,source TEXT);
    ''')

def _connect(): return database(DB,_initialize,'conversations-3')
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


def active(token):
    owner=_owner(token)
    with _connect() as db:
        row=db.execute('SELECT c.id FROM conversation_preferences p JOIN conversations c ON c.id=p.active AND c.owner=p.owner WHERE p.owner=?',(owner,)).fetchone()
        return row['id'] if row else None


def select_active(token,key):
    owner=_owner(token)
    with _connect() as db:
        _owned(db,owner,key)
        db.execute('INSERT INTO conversation_preferences VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET active=excluded.active',(owner,key))


def continue_from(token,key):
    """Copy an owned snapshot to a fresh conversation; never reset daily quotas."""
    owner=_owner(token); new_key=uuid.uuid4().hex; stamp=_now()
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE'); row=_owned(db,owner,key)
        db.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,1)',
                   (new_key,owner,('续聊 · '+row['title'])[:80],stamp,stamp,row['context']))
        db.execute('INSERT INTO turns SELECT ?,request,payload,position FROM turns WHERE conversation=?',(new_key,key))
        card=_card(db,key)
        if card['version']:
            db.execute('INSERT INTO consultation_card_versions VALUES (?,?,?,?,?)',
                       (new_key,1,stamp,'从原对话保留上下文续聊',json.dumps(card['fields'],ensure_ascii=False,sort_keys=True)))
        db.execute('INSERT INTO consultation_card_inputs SELECT ?,request,original FROM consultation_card_inputs WHERE conversation=?',(new_key,key))
        db.execute('INSERT INTO conversation_continuations VALUES (?,?)',(new_key,key))
    return new_key

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
        db.execute('DELETE FROM consultation_card_versions WHERE conversation=?',(key,))
        db.execute('DELETE FROM consultation_card_inputs WHERE conversation=?',(key,))
        db.execute('DELETE FROM conversation_preferences WHERE owner=? AND active=?',(owner,key))
        db.execute('DELETE FROM conversation_continuations WHERE conversation=?',(key,))
        db.execute('DELETE FROM conversations WHERE id=?',(key,))


class CardConflict(ValueError):
    """The displayed version was changed by another page/session."""


def _card(db, key):
    from .consultation_card import empty_card
    row = db.execute('SELECT * FROM consultation_card_versions WHERE conversation=? ORDER BY version DESC LIMIT 1', (key,)).fetchone()
    return dict(version=row['version'], created=row['created'], fields=json.loads(row['payload'])) if row else dict(version=0, created='', fields=empty_card())


def _write_card(db, key, previous, fields, reason):
    if fields == previous['fields']: return previous
    version = previous['version'] + 1
    stamp = _now()
    db.execute('INSERT INTO consultation_card_versions VALUES(?,?,?,?,?)',
               (key, version, stamp, reason, json.dumps(fields, ensure_ascii=False, sort_keys=True)))
    return dict(version=version, created=stamp, fields=fields)


def load_card(token, key):
    owner = _owner(token)
    with _connect() as db:
        _owned(db, owner, key)
        return _card(db, key)


def ingest_card(token, key, request, original):
    """Atomic extraction/receipt; retries never replay an older input over a newer edit."""
    from .consultation_card import extract, merge
    owner = _owner(token)
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _owned(db, owner, key)
        previous = _card(db, key)
        receipt = db.execute('SELECT original FROM consultation_card_inputs WHERE conversation=? AND request=?', (key, request)).fetchone()
        if receipt:
            if receipt['original'] != original: raise ValueError('来源请求编号已对应其他原话')
            return previous
        fields = merge(previous['fields'], extract(original, request))
        db.execute('INSERT INTO consultation_card_inputs VALUES(?,?,?)', (key, request, original))
        return _write_card(db, key, previous, fields, '用户输入提取')


def save_card(token, key, edits, expected_version):
    from .consultation_card import confirm, same_decisions
    owner = _owner(token)
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _owned(db, owner, key)
        previous = _card(db, key)
        if same_decisions(previous['fields'], edits): return previous
        if previous['version'] != expected_version:
            raise CardConflict('核对卡已在其他页面更新，请重新载入后核对。')
        fields = confirm(previous['fields'], edits, 'card-edit-' + uuid.uuid4().hex[:12])
        return _write_card(db, key, previous, fields, '用户确认保存')


def card_versions(token, key):
    owner = _owner(token)
    with _connect() as db:
        _owned(db, owner, key)
        return [dict(version=row['version'], created=row['created'], reason=row['reason'], fields=json.loads(row['payload']))
                for row in db.execute('SELECT * FROM consultation_card_versions WHERE conversation=? ORDER BY version DESC', (key,))]

def markdown(record):
    lines=['# '+record['title'],'']
    for turn in record['turns']:
        lines+=['## 我',turn['question'],'','## 问诊助手',turn['answer'],'']
    return '\n'.join(lines)
