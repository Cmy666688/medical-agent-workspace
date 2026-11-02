"""Offline, fail-closed merge of two user stores; originals are never modified."""
import argparse
import hashlib
import gc
import json
import sqlite3
import uuid
import time
from datetime import datetime,timezone
from pathlib import Path
from contextlib import contextmanager,closing

DATABASES=('family.sqlite','conversations.sqlite','monitor.sqlite')


@contextmanager
def _open(path):
    db=sqlite3.connect(path)
    db.row_factory=sqlite3.Row
    try:
        with db:yield db
    finally:db.close()


def _tables(db):
    return {row['name']:row['sql'] for row in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _rows_equal(a,b):
    return dict(a)==dict(b)


def _merge(target,source,*,renames=None):
    counts={}
    for table,sql in _tables(source).items():
        if table=='worker_state':
            continue  # stale worker heartbeats are not migrated into live health state
        if table not in _tables(target):
            target.execute(sql)
        columns=[row['name'] for row in source.execute(f'PRAGMA table_info("{table}")')]
        dest_columns={row['name'] for row in target.execute(f'PRAGMA table_info("{table}")')}
        if not set(columns)<=dest_columns:
            raise ValueError('Incompatible schema: '+table)
        keys=[row['name'] for row in sorted(source.execute(f'PRAGMA table_info("{table}")'),key=lambda r:r['pk']) if row['pk']]
        inserted=0
        for raw in source.execute('SELECT * FROM "'+table+'"'):
            row=dict(raw)
            if table=='accounts' and renames:
                row['username']=renames.get(row['username'],row['username'])
            if table=='login_attempts' and renames:
                for old,new in renames.items():
                    for prefix in ('login:','recovery:'):
                        if row['username_hash']==hashlib.sha256((prefix+old).encode()).hexdigest():
                            row['username_hash']=hashlib.sha256((prefix+new).encode()).hexdigest()
            if keys:
                where=' AND '.join('"'+key+'"=?' for key in keys)
                existing=target.execute(f'SELECT * FROM "{table}" WHERE '+where,[row[k] for k in keys]).fetchone()
                if existing:
                    if all(existing[k]==row[k] for k in columns):
                        continue
                    raise ValueError('Different records share an ID in table '+table+'; migration stopped')
            names=','.join('"'+c+'"' for c in columns)
            try:
                target.execute(f'INSERT INTO "{table}" ({names}) VALUES ({",".join("?" for _ in columns)})',[row[c] for c in columns])
            except sqlite3.IntegrityError as exc:
                raise ValueError('Unique value conflict in table '+table+'; explicit resolution required') from exc
            inserted+=1
        counts[table]=inserted
    return counts


def _snapshot(source,destination):
    if not source.is_file():
        raise ValueError('Missing source database: '+str(source))
    # backup() includes committed WAL data; never copy a live SQLite file directly.
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as origin,closing(sqlite3.connect(destination)) as out:
        origin.backup(out)


def build_merge(local,public,target,*,rename_public=None,backup_root=None):
    local=Path(local).resolve();public=Path(public).resolve();target=Path(target).resolve()
    if target.exists():
        raise ValueError('Target already exists; refusing to overwrite shared data')
    if target in (local,public) or local in target.parents and target.name!='shared':
        raise ValueError('Use a new, separate shared target directory')
    renames=rename_public or {}
    from agents.accounts import _username
    for old,new in renames.items():
        if _username(old)!=old or _username(new)!=new:
            raise ValueError('Rename usernames must be canonical lowercase usernames')
    backup_root=Path(backup_root or target.parent/'backups'/('user_merge_'+uuid.uuid4().hex[:12])).resolve()
    backup_root.mkdir(parents=True,exist_ok=False)
    stage=target.with_name(target.name+'.staging-'+uuid.uuid4().hex[:10])
    stage.mkdir(parents=True,exist_ok=False)
    report=dict(created_at=datetime.now(timezone.utc).isoformat(),rename_public=renames,databases={})
    for name in DATABASES:
        local_copy=backup_root/('local-'+name)
        public_copy=backup_root/('public-'+name)
        _snapshot(local/name,local_copy);_snapshot(public/name,public_copy)
        _snapshot(local_copy,stage/name)
        with _open(stage/name) as destination,_open(public_copy) as incoming:
            inserted=_merge(destination,incoming,renames=renames)
            if name=='family.sqlite':
                destination.execute('DELETE FROM worker_state')
            if destination.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('SQLite integrity check failed: '+name)
            report['databases'][name]=dict(inserted=inserted,totals={t:destination.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in _tables(destination)})
    # Verify cross-database owner links without exposing any record contents.
    with _open(stage/'family.sqlite') as family,_open(stage/'conversations.sqlite') as conversations:
        owners={r[0] for r in family.execute('SELECT identity FROM accounts')}
        if any(row[0] not in owners for row in conversations.execute('SELECT DISTINCT owner FROM conversations')):
            raise ValueError('A conversation owner is missing; migration stopped')
        report['administrator_count']=family.execute("SELECT COUNT(*) FROM account_controls WHERE role='admin' AND enabled=1").fetchone()[0]
    (stage/'migration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (backup_root/'migration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Windows scanners can briefly retain a handle after SQLite closes. Never
    # overwrite a destination or fall back to deleting/copying a live directory.
    for attempt in range(8):
        try:
            stage.rename(target)
            break
        except PermissionError:
            if attempt==7:raise
            gc.collect()
            time.sleep(min(.2*(attempt+1),1))
    return report


def inspect(local,public):
    names=[]
    identities=[]
    for root in (Path(local),Path(public)):
        with closing(sqlite3.connect((root/'family.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as db:
            names.append(dict(db.execute('SELECT username,identity FROM accounts')))
            identities.append(len(names[-1]))
    return dict(account_counts=identities,username_conflicts=[name for name in names[0].keys() & names[1].keys() if names[0][name]!=names[1][name]])


def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local',type=Path,default=root/'runtime')
    parser.add_argument('--public',type=Path,default=root/'runtime/public')
    parser.add_argument('--target',type=Path,default=root/'runtime/shared')
    parser.add_argument('--rename-public',action='append',default=[],metavar='OLD=NEW')
    parser.add_argument('--apply',action='store_true',help='Only after both web services and workers have stopped')
    args=parser.parse_args()
    if not args.apply:
        print(json.dumps(inspect(args.local,args.public),ensure_ascii=False));return
    config=root/'config/storage.local.toml'
    if config.exists():
        raise ValueError('Storage is already configured; refusing to overwrite its activation settings')
    renames=dict(value.split('=',1) for value in args.rename_public)
    report=build_merge(args.local,args.public,args.target,rename_public=renames)
    print(json.dumps(report,ensure_ascii=False))
    # Activation is a separate atomic step after validation; custom targets are explicit.
    temporary=config.with_suffix('.tmp')
    temporary.write_text('[storage]\nuser_data_dir = '+json.dumps(str(args.target.resolve()).replace('\\','/'))+'\n',encoding='utf-8')
    temporary.replace(config)
    print('Shared account/family/conversation store activated. Restart both web services and workers.')


if __name__=='__main__':main()
