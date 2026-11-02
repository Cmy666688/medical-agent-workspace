import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from .sqlite_store import database

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.getenv('MEDICAL_RUNTIME_DIR',str(ROOT / 'runtime'))) / 'monitor.sqlite'

def _initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS events (time TEXT, session TEXT, request TEXT, kind TEXT, data TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS users (session TEXT PRIMARY KEY, user_id TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS quota (session TEXT, time REAL, tokens INTEGER)')
    db.execute('CREATE INDEX IF NOT EXISTS events_time ON events(time DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS events_kind_time ON events(kind,time DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS quota_session_time ON quota(session,time)')

@contextmanager
def connect():
    with database(DB,_initialize,'telemetry-2') as db:
        yield db

def record(session, request, kind, **data):
    with connect() as db:
        row=db.execute('SELECT user_id FROM users WHERE session=?',(session,)).fetchone()
        data.setdefault('user_id',row[0] if row else 'unknown')
        db.execute('INSERT INTO events VALUES (?,?,?,?,?)', (datetime.now(timezone.utc).isoformat(), session, request, kind, json.dumps(data, ensure_ascii=False)))

def bind_user(session, user_id):
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO users VALUES (?,?)',(session,user_id))

def feedback_stats(rows):
    requests={r['request'] for r in rows if r['kind']=='request'}
    latest={}
    for r in rows:  # events() 为时间倒序；取消反馈同样覆盖旧值。
        if r['kind']=='feedback' and r['request'] in requests:
            value=r.get('positive')
            latest.setdefault(r['request'],bool(value) if value in (True,False) else None)
    values=[v for v in latest.values() if v is not None]
    return dict(count=len(values),positive=sum(v is True for v in values),negative=sum(v is False for v in values),coverage=len(values)/len(requests) if requests else 0)

def events(limit=5000,kind=None,exclude_session=None,user_id=None):
    conditions=[]; params=[]
    if kind is not None: conditions.append('kind=?'); params.append(kind)
    if exclude_session is not None: conditions.append('session!=?'); params.append(exclude_session)
    if user_id is not None: conditions.append("json_extract(data,'$.user_id')=?"); params.append(user_id)
    where=' WHERE '+' AND '.join(conditions) if conditions else ''
    with connect() as db:
        rows = db.execute('SELECT * FROM events'+where+' ORDER BY time DESC LIMIT ?',[*params,min(max(int(limit),1),5000)]).fetchall()
    return [dict(time=r[0], session=r[1], request=r[2], kind=r[3], **json.loads(r[4])) for r in rows]


def personal_events(token,limit=4,kind='request'):
    from .family import identity_profile
    owner=identity_profile(token)
    return events(limit=limit,kind=kind,user_id='member_'+owner['id'])
