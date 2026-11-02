"""Per-user local accounts, password hashing and revocable expiring sessions."""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from datetime import timedelta
from . import family

ITERATIONS=600_000
_DUMMY_SALT=b'medical-dummy-v1!'

def _username(value):
    value=value.strip().lower()
    if not re.fullmatch(r'[a-z0-9_]{3,32}',value):
        raise ValueError('用户名需为 3～32 位英文字母、数字或下划线。')
    return value

def _password(value):
    if not isinstance(value,str) or not 8<=len(value)<=128:
        raise ValueError('密码长度需为 8～128 位。')

def _hash(password,salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,ITERATIONS).hex()

def _session(db,identity,remember=False):
    control=db.execute('SELECT enabled FROM account_controls WHERE identity=?',(identity,)).fetchone()
    if control and not control['enabled']: raise PermissionError('账号已停用，请联系管理员。')
    token='session_'+secrets.token_urlsafe(32)
    expires=family.now()+timedelta(days=30 if remember else 1)
    db.execute('DELETE FROM login_sessions WHERE expires<=?',(family.now().isoformat(),))
    db.execute('INSERT INTO login_sessions VALUES (?,?,?)',(family.digest(token),identity,expires.isoformat()))
    return token

def register(username,password,display,*,legacy_token=None,remember=False):
    username=_username(username); _password(password)
    if not display.strip() or len(display.strip())>40: raise ValueError('请填写 1～40 字的称呼。')
    salt=secrets.token_bytes(16); encoded=_hash(password,salt)
    recovery=secrets.token_urlsafe(32)
    try:
        with family.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if legacy_token:
                if legacy_token.startswith('session_'): raise ValueError('当前身份已经注册过账号。')
                identity=family.identity_actor(db,legacy_token)['id']
            else:
                identity=uuid.uuid4().hex
                db.execute('INSERT INTO identities VALUES (?,?,?)',(identity,display.strip(),family.digest(secrets.token_urlsafe(32))))
            db.execute('INSERT INTO accounts VALUES (?,?,?,?,?,?)',(identity,username,salt.hex(),encoded,family.digest(recovery),family.now().isoformat()))
            db.execute('UPDATE identities SET display=? WHERE id=?',(display.strip(),identity))
            if legacy_token:
                for member in db.execute('SELECT member FROM identity_members WHERE identity=?',(identity,)).fetchall():
                    db.execute('UPDATE members SET secret_hash=? WHERE id=?',(family.digest(secrets.token_urlsafe(32)),member['member']))
            token=_session(db,identity,remember)
        return dict(token=token,recovery=recovery)
    except sqlite3.IntegrityError as exc:
        raise ValueError('此用户名已被使用，请换一个。') from exc

def _limited(db,key):
    stamp=time.time()
    db.execute('DELETE FROM login_attempts WHERE time<?',(stamp-900,))
    count=db.execute('SELECT COUNT(*) FROM login_attempts WHERE username_hash=? AND time>?',(key,stamp-900)).fetchone()[0]
    if count>=5: raise PermissionError('尝试次数较多，请 15 分钟后再试。')

def login(username,password,remember=False):
    username=_username(username)
    if not isinstance(password,str) or len(password)>128: raise PermissionError('用户名或密码不正确。')
    key=family.digest('login:'+username)
    # Reserve an attempt before expensive hashing; simultaneous requests share the limit.
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE'); _limited(db,key)
        db.execute('INSERT INTO login_attempts VALUES (?,?)',(key,time.time()))
        row=db.execute('SELECT * FROM accounts WHERE username=?',(username,)).fetchone()
    supplied=_hash(password,bytes.fromhex(row['salt']) if row else _DUMMY_SALT)
    if not row or not hmac.compare_digest(supplied,row['password_hash']):
        raise PermissionError('用户名或密码不正确。')
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT password_hash FROM accounts WHERE identity=?',(row['identity'],)).fetchone()
        if not current or not hmac.compare_digest(current['password_hash'],supplied): raise PermissionError('用户名或密码不正确。')
        db.execute('DELETE FROM login_attempts WHERE username_hash=?',(key,))
        return _session(db,row['identity'],remember)

def logout(token):
    if token and token.startswith('session_'):
        with family.connect() as db: db.execute('DELETE FROM login_sessions WHERE secret_hash=?',(family.digest(token),))


def update_display(token,display):
    if not isinstance(display,str) or not display.strip() or len(display.strip())>40:
        raise ValueError('称呼需为 1～40 字。')
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        person=family.identity_actor(db,token)
        db.execute('UPDATE identities SET display=? WHERE id=?',(display.strip(),person['id']))

def change_password(token,current_password,new_password,remember=False):
    _password(new_password)
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        person=family.identity_actor(db,token)
        row=db.execute('SELECT * FROM accounts WHERE identity=?',(person['id'],)).fetchone()
        if not row: raise PermissionError('请先将旧身份升级为账号。')
        key=family.digest('change:'+person['id'])
        _limited(db,key)
        db.execute('INSERT INTO login_attempts VALUES (?,?)',(key,time.time()))
    if not isinstance(current_password,str) or len(current_password)>128 or not hmac.compare_digest(_hash(current_password,bytes.fromhex(row['salt'])),row['password_hash']):
        raise PermissionError('当前密码不正确。')
    salt=secrets.token_bytes(16); encoded=_hash(new_password,salt)
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE'); family.identity_actor(db,token)
        latest=db.execute('SELECT password_hash FROM accounts WHERE identity=?',(person['id'],)).fetchone()
        if latest['password_hash']!=row['password_hash']: raise PermissionError('密码已变更，请重新登录。')
        db.execute('UPDATE accounts SET salt=?,password_hash=? WHERE identity=?',(salt.hex(),encoded,person['id']))
        db.execute('DELETE FROM login_sessions WHERE identity=?',(person['id'],))
        db.execute('DELETE FROM login_attempts WHERE username_hash=?',(key,))
        return _session(db,person['id'],remember)

def recover(username,recovery,new_password,remember=False):
    username=_username(username); _password(new_password)
    if not recovery or len(recovery)>256: raise PermissionError('用户名或恢复码不正确。')
    key=family.digest('recovery:'+username)
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE'); _limited(db,key)
        db.execute('INSERT INTO login_attempts VALUES (?,?)',(key,time.time()))
        row=db.execute('SELECT * FROM accounts WHERE username=?',(username,)).fetchone()
    if not row or not hmac.compare_digest(family.digest(recovery.strip()),row['recovery_hash']):
        raise PermissionError('用户名或恢复码不正确。')
    salt=secrets.token_bytes(16); encoded=_hash(new_password,salt); next_recovery=secrets.token_urlsafe(32)
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT recovery_hash FROM accounts WHERE identity=?',(row['identity'],)).fetchone()
        if not current or not hmac.compare_digest(current['recovery_hash'],row['recovery_hash']): raise PermissionError('恢复码已更新，请使用最新恢复码。')
        db.execute('UPDATE accounts SET salt=?,password_hash=?,recovery_hash=? WHERE identity=?',(salt.hex(),encoded,family.digest(next_recovery),row['identity']))
        db.execute('DELETE FROM login_sessions WHERE identity=?',(row['identity'],))
        db.execute('DELETE FROM login_attempts WHERE username_hash IN (?,?)',(key,family.digest('login:'+username)))
        token=_session(db,row['identity'],remember)
    return dict(token=token,recovery=next_recovery)
