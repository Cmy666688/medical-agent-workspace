"""家庭成员、共享授权和站内协作。访问密钥只保存摘要。"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
import uuid
import threading
import time
from .sqlite_store import database
from .storage_paths import user_data_root

ROOT=Path(__file__).resolve().parents[1]
DB=user_data_root()/'family.sqlite'
TZ=timezone(timedelta(hours=8))
def now(): return datetime.now(TZ)
def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def _initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS households(id TEXT PRIMARY KEY,name TEXT,invite_hash TEXT,expires TEXT);
    CREATE TABLE IF NOT EXISTS members(id TEXT PRIMARY KEY,group_id TEXT,name TEXT,secret_hash TEXT UNIQUE,role TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS grants(target TEXT,viewer TEXT,can_read INTEGER,can_manage INTEGER,PRIMARY KEY(target,viewer));
    CREATE TABLE IF NOT EXISTS measurements(id TEXT PRIMARY KEY,member TEXT,time TEXT,kind TEXT,content TEXT);
    CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,group_id TEXT,member TEXT,time TEXT,body TEXT);
    CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY,member TEXT,creator TEXT,title TEXT,kind TEXT,clock TEXT,created TEXT,active INTEGER);
    CREATE TABLE IF NOT EXISTS notices(id TEXT PRIMARY KEY,member TEXT,creator TEXT,schedule TEXT,due TEXT,title TEXT,status TEXT,done_at TEXT,UNIQUE(schedule,due));
    CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,actor TEXT,target TEXT,action TEXT,time TEXT);
    CREATE TABLE IF NOT EXISTS worker_state(id INTEGER PRIMARY KEY,time TEXT);
    CREATE TABLE IF NOT EXISTS identities(id TEXT PRIMARY KEY,display TEXT,secret_hash TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS identity_members(identity TEXT,member TEXT UNIQUE,PRIMARY KEY(identity,member));
    CREATE TABLE IF NOT EXISTS accounts(identity TEXT PRIMARY KEY,username TEXT UNIQUE,salt TEXT,password_hash TEXT,recovery_hash TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS login_sessions(secret_hash TEXT PRIMARY KEY,identity TEXT,expires TEXT);
    CREATE TABLE IF NOT EXISTS login_attempts(username_hash TEXT,time REAL);
    CREATE INDEX IF NOT EXISTS login_attempts_user_time ON login_attempts(username_hash,time);
    CREATE INDEX IF NOT EXISTS login_sessions_identity ON login_sessions(identity);
    CREATE TABLE IF NOT EXISTS account_controls(identity TEXT PRIMARY KEY,role TEXT NOT NULL DEFAULT 'user',enabled INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS account_audit(id TEXT PRIMARY KEY,actor TEXT,target TEXT,action TEXT,time TEXT);
    ''')
    for table,column in [('messages','recipient'),('schedules','settings')]:
        if column not in {r['name'] for r in db.execute('PRAGMA table_info('+table+')')}:
            try: db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' TEXT')
            except sqlite3.OperationalError as exc:
                if 'duplicate column' not in str(exc).lower(): raise
    db.executescript('''
    CREATE INDEX IF NOT EXISTS members_group ON members(group_id);
    CREATE INDEX IF NOT EXISTS measurements_member_time ON measurements(member,time DESC);
    CREATE INDEX IF NOT EXISTS messages_group_time ON messages(group_id,time DESC);
    CREATE INDEX IF NOT EXISTS schedules_member ON schedules(member);
    CREATE INDEX IF NOT EXISTS notices_member_due ON notices(member,due DESC);
    CREATE INDEX IF NOT EXISTS audit_target_time ON audit(target,time DESC);
    ''')


@contextmanager
def connect():
    with database(DB,_initialize,'family-accounts-2') as db:
        yield db

def actor(db,token):
    if '.' in token:
        account,member=token.split('.',1)
        identity=identity_actor(db,account)
        row=db.execute('SELECT m.* FROM members m JOIN identity_members l ON l.member=m.id WHERE l.identity=? AND m.id=?',(identity['id'],member)).fetchone()
        if not row: raise PermissionError('当前身份未加入这个家庭')
        return dict(row)
    row=db.execute('SELECT * FROM members WHERE secret_hash=?',(digest(token),)).fetchone()
    if not row: raise PermissionError('成员访问密钥无效，请重新连接')
    linked=db.execute('SELECT c.enabled FROM identity_members l JOIN account_controls c ON c.identity=l.identity WHERE l.member=?',(row['id'],)).fetchone()
    if linked and not linked['enabled']: raise PermissionError('账号已停用，请联系管理员')
    return dict(row)

def authorize(db,token,target,permission='can_read'):
    person=actor(db,token)
    member=db.execute('SELECT * FROM members WHERE id=? AND group_id=?',(target,person['group_id'])).fetchone()
    if not member: raise PermissionError('该成员不在你的家庭组中')
    if person['id']!=target:
        grant=db.execute('SELECT * FROM grants WHERE target=? AND viewer=?',(target,person['id'])).fetchone()
        if not grant or not grant[permission]: raise PermissionError('对方尚未授予此项权限')
    return person

def audit(db,person,target,action):
    db.execute('INSERT INTO audit VALUES (?,?,?,?,?)',(uuid.uuid4().hex,person['id'],target,action,now().isoformat()))

def create_family(name,display,identity_token=None):
    if not name.strip() or not display.strip(): raise ValueError('请填写家庭名称和成员称呼')
    token=secrets.token_urlsafe(32); invitation=secrets.token_urlsafe(24); gid=uuid.uuid4().hex; mid=uuid.uuid4().hex
    with connect() as db:
        db.execute('INSERT INTO households VALUES (?,?,?,?)',(gid,name.strip()[:80],digest(invitation),(now()+timedelta(days=7)).isoformat()))
        db.execute('INSERT INTO members VALUES (?,?,?,?,?,?)',(mid,gid,display.strip()[:40],digest(token),'owner',now().isoformat()))
        if identity_token:
            identity=identity_actor(db,identity_token)
            db.execute('INSERT INTO identity_members VALUES (?,?)',(identity['id'],mid))
            token=identity_token+'.'+mid
    return dict(token=token,invite=invitation)

def join_family(invitation,display,identity_token=None):
    if not display.strip(): raise ValueError('请填写成员称呼')
    token=secrets.token_urlsafe(32)
    if not isinstance(invitation,str) or len(invitation)>512: raise ValueError('请复制完整的家庭邀请码')
    invitation=invitation.strip().strip('\u200b\ufeff').strip()
    if not invitation: raise ValueError('请先填写家庭邀请码')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        identity=identity_actor(db,identity_token) if identity_token else None
        group=db.execute('SELECT * FROM households WHERE invite_hash=?',(digest(invitation),)).fetchone()
        if not group: raise PermissionError('邀请码无效或已过期。请复制创建者最新分享的完整邀请码；刷新后旧码会失效。')
        if datetime.fromisoformat(group['expires'])<=now(): raise PermissionError('邀请码已过期，请让家庭创建者生成新的邀请码。')
        mid=uuid.uuid4().hex
        if identity_token:
            existing=db.execute('SELECT m.id FROM members m JOIN identity_members l ON l.member=m.id WHERE l.identity=? AND m.group_id=?',(identity['id'],group['id'])).fetchone()
            if existing:
                count=db.execute('SELECT COUNT(*) FROM members WHERE group_id=?',(group['id'],)).fetchone()[0]
                return dict(token=identity_token+'.'+existing['id'],already_member=True,family_name=group['name'],member_count=count)
        db.execute('INSERT INTO members VALUES (?,?,?,?,?,?)',(mid,group['id'],display.strip()[:40],digest(token),'member',now().isoformat()))
        if identity_token:
            db.execute('INSERT INTO identity_members VALUES (?,?)',(identity['id'],mid))
            token=identity_token+'.'+mid
        audit(db,dict(id=mid),group['id'],'join_family')
        count=db.execute('SELECT COUNT(*) FROM members WHERE group_id=?',(group['id'],)).fetchone()[0]
    return dict(token=token,already_member=False,family_name=group['name'],member_count=count)

def profile(token):
    with connect() as db:
        person=actor(db,token); group=db.execute('SELECT name FROM households WHERE id=?',(person['group_id'],)).fetchone()
        return dict(**{k:v for k,v in person.items() if k!='secret_hash'},family=group['name'])

def members(token):
    with connect() as db:
        person=actor(db,token)
        rows=db.execute('SELECT m.id,m.name,m.role,a.username FROM members m LEFT JOIN identity_members l ON l.member=m.id LEFT JOIN accounts a ON a.identity=l.identity WHERE m.group_id=?',(person['group_id'],)).fetchall()
        result=[]
        for row in rows:
            item=dict(row); grant=db.execute('SELECT * FROM grants WHERE target=? AND viewer=?',(row['id'],person['id'])).fetchone()
            item.update(can_read=row['id']==person['id'] or bool(grant and grant['can_read']),can_manage=row['id']==person['id'] or bool(grant and grant['can_manage']))
            result.append(item)
        return result

def set_grant(token,viewer,read,manage):
    with connect() as db:
        person=actor(db,token)
        if not db.execute('SELECT id FROM members WHERE id=? AND group_id=?',(viewer,person['group_id'])).fetchone(): raise PermissionError('成员不在家庭组中')
        db.execute('INSERT OR REPLACE INTO grants VALUES (?,?,?,?)',(person['id'],viewer,int(read),int(manage)))
        audit(db,person,viewer,'update_sharing')

def grants_given(token):
    with connect() as db:
        person=actor(db,token)
        return [dict(x) for x in db.execute('SELECT viewer,can_read,can_manage FROM grants WHERE target=?',(person['id'],))]

def rotate_invite(token):
    invitation=secrets.token_urlsafe(24)
    with connect() as db:
        person=actor(db,token)
        if person['role']!='owner': raise PermissionError('仅家庭创建者可刷新邀请码')
        db.execute('UPDATE households SET invite_hash=?,expires=? WHERE id=?',(digest(invitation),(now()+timedelta(days=7)).isoformat(),person['group_id']))
        audit(db,person,person['group_id'],'rotate_invite')
    return invitation


def invitation_info(token,candidate=None):
    with connect() as db:
        person=actor(db,token)
        if person['role']!='owner': raise PermissionError('仅家庭创建者可查看邀请信息')
        row=db.execute('SELECT expires,invite_hash FROM households WHERE id=?',(person['group_id'],)).fetchone()
        return dict(group_id=person['group_id'],expires=row['expires'],expired=datetime.fromisoformat(row['expires'])<=now(),
                    matches=isinstance(candidate,str) and hmac.compare_digest(row['invite_hash'],digest(candidate)))

def add_measurement(token,kind,content):
    if kind=='血压':
        sbp=float(content['收缩压']); dbp=float(content['舒张压'])
        if not (30<=dbp<sbp<=300): raise ValueError('请核对血压录入值及单位 mmHg')
    if kind=='状态' and not content.get('说明','').strip(): raise ValueError('请填写状态说明')
    with connect() as db:
        person=actor(db,token)
        db.execute('INSERT INTO measurements VALUES (?,?,?,?,?)',(uuid.uuid4().hex,person['id'],now().isoformat(),kind,json.dumps(content,ensure_ascii=False)))
        audit(db,person,person['id'],'add_measurement')

def health_records(token,target):
    with connect() as db:
        person=authorize(db,token,target)
        rows=[dict(x) for x in db.execute('SELECT id,time,kind,content FROM measurements WHERE member=? ORDER BY time DESC LIMIT 100',(target,))]
        audit(db,person,target,'view_health_records')
        return [dict(**r,values=json.loads(r['content'])) for r in rows]

def send_message(token,text,recipient=None):
    if not text.strip() or len(text)>1000: raise ValueError('留言长度应为 1～1000 字')
    if recipient is not None and (not isinstance(recipient,str) or not recipient.strip()): raise ValueError('请选择有效的收件成员')
    with connect() as db:
        person=actor(db,token)
        if recipient and not db.execute('SELECT id FROM members WHERE id=? AND group_id=?',(recipient,person['group_id'])).fetchone(): raise PermissionError('收件人不在你的家庭组中')
        db.execute('INSERT INTO messages(id,group_id,member,time,body,recipient) VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,person['group_id'],person['id'],now().isoformat(),text.strip(),recipient))

def messages(token):
    with connect() as db:
        person=actor(db,token)
        return [dict(x) for x in db.execute('SELECT m.time,m.body,u.name,m.recipient,r.name AS recipient_name,m.member AS sender FROM messages m JOIN members u ON u.id=m.member LEFT JOIN members r ON r.id=m.recipient WHERE m.group_id=? AND (m.recipient IS NULL OR m.member=? OR m.recipient=?) ORDER BY m.time DESC LIMIT 100',(person['group_id'],person['id'],person['id']))]

REMINDER_TYPES=('服药','测量血压','测量血糖','测量体温','饮水','用餐','运动','康复训练','休息','睡眠','复诊','护理','其他')

def add_schedule(token,target,title,kind,clock,*,start_date=None,end_date=None,repeat='daily',end_clock=None,interval_minutes=60,weekdays=None):
    datetime.strptime(clock,'%H:%M')
    if not title.strip() or len(title)>150: raise ValueError('提醒标题长度应为 1～150 字')
    if kind not in REMINDER_TYPES: raise ValueError('不支持的提醒类型')
    begin=datetime.fromisoformat(str(start_date or now().date())).date()
    end=datetime.fromisoformat(str(end_date)).date() if end_date else None
    if end and end<begin: raise ValueError('结束日期不能早于开始日期')
    if repeat not in ('daily','once','weekly','interval'): raise ValueError('不支持的重复方式')
    if repeat=='interval':
        if not end_clock: raise ValueError('请填写时间段的结束时间')
        datetime.strptime(end_clock,'%H:%M')
        if not isinstance(interval_minutes,int) or not 5<=interval_minutes<=1440: raise ValueError('间隔应为 5～1440 分钟')
    if repeat=='once' and datetime.combine(begin,datetime.strptime(clock,'%H:%M').time(),TZ)<now().replace(second=0,microsecond=0): raise ValueError('单次提醒不能设置在过去')
    if repeat=='weekly' and (not weekdays or any(x not in range(7) for x in weekdays)): raise ValueError('请至少选择一个有效星期')
    settings=dict(start_date=begin.isoformat(),end_date=end.isoformat() if end else None,repeat=repeat,end_clock=end_clock,interval_minutes=interval_minutes,weekdays=weekdays or [])
    with connect() as db:
        person=authorize(db,token,target,'can_manage')
        sid=uuid.uuid4().hex
        db.execute('INSERT INTO schedules(id,member,creator,title,kind,clock,created,active,settings) VALUES (?,?,?,?,?,?,?,1,?)',(sid,target,person['id'],title.strip(),kind,clock,now().isoformat(),json.dumps(settings)))
        audit(db,person,target,'create_schedule')
    return sid

def schedules(token,target):
    with connect() as db:
        authorize(db,token,target,'can_manage')
        return [dict(x) for x in db.execute('SELECT * FROM schedules WHERE member=? ORDER BY created DESC',(target,))]

def toggle_schedule(token,sid,active):
    with connect() as db:
        row=db.execute('SELECT * FROM schedules WHERE id=?',(sid,)).fetchone()
        if not row: raise ValueError('任务不存在')
        person=authorize(db,token,row['member'],'can_manage')
        db.execute('UPDATE schedules SET active=? WHERE id=?',(int(active),sid))
        if not active: db.execute("UPDATE notices SET status='cancelled' WHERE schedule=? AND status='pending'",(sid,))
        audit(db,person,row['member'],'resume_schedule' if active else 'pause_schedule')

def tick(at=None):
    at=(at or now()).astimezone(TZ)
    with connect() as db:
        # worker 与页面可同时调用；唯一键保证重复轮询不重复投递。
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute('SELECT * FROM schedules WHERE active=1').fetchall():
            due=latest_due(row,at)
            if due:
                db.execute('INSERT OR IGNORE INTO notices VALUES (?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,row['member'],row['creator'],row['id'],due.isoformat(),row['title'],'pending',None))

def latest_due(row,at):
    settings=json.loads(row['settings'] or '{}')
    created=datetime.fromisoformat(row['created']).replace(second=0,microsecond=0)
    start=settings.get('start_date',created.date().isoformat()); end=settings.get('end_date')
    mode=settings.get('repeat','daily'); candidates=[]
    for anchor in [at.date()-timedelta(days=1),at.date()]:
        if anchor.isoformat()<start or (end and anchor.isoformat()>end): continue
        if mode=='once' and anchor.isoformat()!=start: continue
        if mode=='weekly' and anchor.weekday() not in settings.get('weekdays',[]): continue
        h,m=map(int,row['clock'].split(':')); first=datetime.combine(anchor,datetime.min.time(),TZ).replace(hour=h,minute=m)
        if mode=='interval':
            h,m=map(int,settings['end_clock'].split(':')); last=first.replace(hour=h,minute=m)
            if last<first: last+=timedelta(days=1)
            if at.replace(second=0,microsecond=0)>last: continue
            step=timedelta(minutes=settings['interval_minutes'])
            if first>at: continue
            index=int((min(at,last)-first)//step); due=first+index*step
        else: due=first
        # 仅补当天最近一档；不在进程恢复时集中补发往日/已错过的全部提醒。
        if due.date()==at.date() and created<=due<=at: candidates.append(due)
    return max(candidates) if candidates else None

def notices(token,target):
    with connect() as db:
        authorize(db,token,target)
        return [dict(x) for x in db.execute('SELECT * FROM notices WHERE member=? ORDER BY due DESC LIMIT 100',(target,))]

def complete_notice(token,nid):
    with connect() as db:
        person=actor(db,token)
        row=db.execute('SELECT * FROM notices WHERE id=? AND member=?',(nid,person['id'])).fetchone()
        if not row: raise PermissionError('只能确认自己的待办')
        db.execute("UPDATE notices SET status='done',done_at=? WHERE id=? AND status='pending'",(now().isoformat(),nid))
        audit(db,person,person['id'],'complete_notice')

def request_checkin(token,target,text):
    if not text.strip() or len(text)>150: raise ValueError('请填写 1～150 字的请求')
    with connect() as db:
        person=authorize(db,token,target,'can_manage')
        db.execute('INSERT INTO notices VALUES (?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,target,person['id'],None,now().isoformat(),text.strip(),'pending',None))
        audit(db,person,target,'request_checkin')

def audit_log(token):
    with connect() as db:
        person=actor(db,token)
        return [dict(x) for x in db.execute('SELECT a.time,a.action,u.name AS actor FROM audit a JOIN members u ON a.actor=u.id WHERE a.target=? ORDER BY a.time DESC LIMIT 100',(person['id'],))]

def worker_heartbeat():
    with connect() as db: db.execute('INSERT OR REPLACE INTO worker_state VALUES (1,?)',(now().isoformat(),))

def worker_status():
    with connect() as db:
        row=db.execute('SELECT time FROM worker_state WHERE id=1').fetchone()
        return row['time'] if row else None


_poll_lock=threading.Lock()
_last_poll={}

def poll_reminders():
    """The worker schedules tasks; the UI only provides a throttled fallback."""
    key=str(DB.resolve())
    with _poll_lock:
        stamp=time.monotonic()
        if stamp-_last_poll.get(key,float('-inf'))<15: return
        heartbeat=worker_status()
        if not heartbeat or (now()-datetime.fromisoformat(heartbeat)).total_seconds()>60:
            tick()
        _last_poll[key]=stamp

def identity_actor(db,token):
    if token.startswith('session_'):
        row=db.execute('SELECT i.id,i.display,a.username FROM identities i JOIN accounts a ON a.identity=i.id JOIN login_sessions s ON s.identity=i.id WHERE s.secret_hash=? AND s.expires>?',(digest(token),now().isoformat())).fetchone()
    else:
        row=db.execute('SELECT i.id,i.display FROM identities i LEFT JOIN accounts a ON a.identity=i.id WHERE i.secret_hash=? AND a.identity IS NULL',(digest(token),)).fetchone()
    if not row: raise PermissionError('个人身份凭证无效')
    control=db.execute('SELECT role,enabled FROM account_controls WHERE identity=?',(row['id'],)).fetchone()
    if control and not control['enabled']: raise PermissionError('账号已停用，请联系管理员')
    return dict(row,role=control['role'] if control else 'user')

def create_identity(display):
    if not display.strip(): raise ValueError('请填写你的称呼')
    token=secrets.token_urlsafe(32)
    with connect() as db:
        db.execute('INSERT INTO identities VALUES (?,?,?)',(uuid.uuid4().hex,display.strip()[:40],digest(token)))
    return token

def identity_profile(token):
    with connect() as db: return identity_actor(db,token)

def my_families(token):
    with connect() as db:
        identity=identity_actor(db,token)
        return [dict(x) for x in db.execute('SELECT h.id,h.name,m.id AS member_id,m.name AS member_name,m.role,(SELECT COUNT(*) FROM members WHERE group_id=h.id) AS member_count FROM households h JOIN members m ON m.group_id=h.id JOIN identity_members l ON l.member=m.id WHERE l.identity=? ORDER BY m.created',(identity['id'],))]

def import_membership(identity_token,legacy_token):
    with connect() as db:
        identity=identity_actor(db,identity_token); member=actor(db,legacy_token.strip())
        linked=db.execute('SELECT identity FROM identity_members WHERE member=?',(member['id'],)).fetchone()
        if linked and linked['identity']!=identity['id']: raise PermissionError('此成员已关联其他身份，不能重复认领')
        db.execute('INSERT OR IGNORE INTO identity_members VALUES (?,?)',(identity['id'],member['id']))
        return identity_token+'.'+member['id']
