"""Account administration. Never exposes passwords, tokens or medical records."""
import secrets
import uuid

from . import accounts, family


def _admin(db, token):
    person = family.identity_actor(db, token)
    if person.get('role') != 'admin' or not person.get('username'):
        raise PermissionError('仅管理员可管理用户。')
    return person


def _audit(db, actor, target, action):
    db.execute('INSERT INTO account_audit VALUES (?,?,?,?,?)',
               (uuid.uuid4().hex, actor, target, action, family.now().isoformat()))


def listing(token, query=''):
    with family.connect() as db:
        _admin(db, token)
        # Explicit fields: no password/recovery hashes, sessions or medical data.
        return [dict(row) for row in db.execute('''
            SELECT a.identity,a.username,i.display,a.created,
                   COALESCE(c.role,'user') AS role,COALESCE(c.enabled,1) AS enabled,
                   (SELECT COUNT(*) FROM login_sessions s WHERE s.identity=a.identity AND s.expires>?) AS sessions
            FROM accounts a JOIN identities i ON i.id=a.identity
            LEFT JOIN account_controls c ON c.identity=a.identity
            WHERE a.username LIKE ? OR i.display LIKE ?
            ORDER BY a.created DESC LIMIT 200
        ''', (family.now().isoformat(), '%'+query.strip()+'%', '%'+query.strip()+'%'))]


def update(token, identity, *, display, role, enabled):
    if not isinstance(display,str) or not 1 <= len(display.strip()) <= 40:
        raise ValueError('称呼需为 1～40 字。')
    if role not in ('user', 'admin') or not isinstance(enabled, bool):
        raise ValueError('用户角色或状态无效。')
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        person = _admin(db, token)
        row = db.execute('SELECT identity FROM accounts WHERE identity=?', (identity,)).fetchone()
        if not row:
            raise ValueError('用户不存在。')
        if person['id'] == identity and (role != 'admin' or not enabled):
            raise ValueError('不能停用自己或移除自己的管理员权限。')
        before = db.execute('SELECT role,enabled FROM account_controls WHERE identity=?', (identity,)).fetchone()
        old_role, old_enabled = (before['role'],bool(before['enabled'])) if before else ('user',True)
        previous_display = db.execute('SELECT display FROM identities WHERE id=?',(identity,)).fetchone()[0]
        if (previous_display,old_role,old_enabled) == (display.strip(),role,enabled):
            return
        db.execute('UPDATE identities SET display=? WHERE id=?',(display.strip(),identity))
        db.execute('INSERT INTO account_controls VALUES (?,?,?) ON CONFLICT(identity) DO UPDATE SET role=excluded.role,enabled=excluded.enabled',
                   (identity,role,int(enabled)))
        if not enabled or role != old_role:
            db.execute('DELETE FROM login_sessions WHERE identity=?',(identity,))
        _audit(db,person['id'],identity,f'account.update role={role} enabled={int(enabled)}')


def revoke_sessions(token, identity):
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        person = _admin(db, token)
        if person['id'] == identity:
            raise ValueError('请在“我的账户”退出当前账号。')
        if not db.execute('SELECT 1 FROM accounts WHERE identity=?',(identity,)).fetchone():
            raise ValueError('用户不存在。')
        db.execute('DELETE FROM login_sessions WHERE identity=?',(identity,))
        _audit(db,person['id'],identity,'account.revoke_sessions')


def create(token, username, password, display):
    username=accounts._username(username)
    accounts._password(password)
    if not isinstance(display,str) or not 1 <= len(display.strip()) <= 40:
        raise ValueError('称呼需为 1～40 字。')
    salt=secrets.token_bytes(16)
    password_hash=accounts._hash(password,salt)
    recovery=secrets.token_urlsafe(32)
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        person=_admin(db,token)
        if db.execute('SELECT 1 FROM accounts WHERE username=?',(username,)).fetchone():
            raise ValueError('此用户名已被使用。')
        identity=uuid.uuid4().hex
        db.execute('INSERT INTO identities VALUES (?,?,?)',(identity,display.strip(),family.digest(secrets.token_urlsafe(32))))
        db.execute('INSERT INTO accounts VALUES (?,?,?,?,?,?)',(identity,username,salt.hex(),password_hash,family.digest(recovery),family.now().isoformat()))
        _audit(db,person['id'],identity,'account.create')
    return recovery


def audit_log(token):
    with family.connect() as db:
        _admin(db,token)
        return [dict(row) for row in db.execute('''
            SELECT e.time,a.username AS actor,t.username AS target,e.action
            FROM account_audit e LEFT JOIN accounts a ON a.identity=e.actor
            LEFT JOIN accounts t ON t.identity=e.target ORDER BY e.time DESC LIMIT 100
        ''')]


def bootstrap_admin(username):
    """Trusted local CLI only: never called by a registration form or web route."""
    username=accounts._username(username)
    with family.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT identity FROM accounts WHERE username=?',(username,)).fetchone()
        if not row:
            raise ValueError('该服务中不存在这个用户名，请先注册。')
        before=db.execute('SELECT role,enabled FROM account_controls WHERE identity=?',(row['identity'],)).fetchone()
        if before and before['role']=='admin' and before['enabled']:
            return
        db.execute("INSERT INTO account_controls VALUES (?,'admin',1) ON CONFLICT(identity) DO UPDATE SET role='admin',enabled=1",(row['identity'],))
        _audit(db,'local-cli',row['identity'],'account.bootstrap_admin')
