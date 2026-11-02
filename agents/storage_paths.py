"""Resolve one user store independently from each web service's cache/log directory."""
import os
import tomllib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def user_data_root():
    runtime=Path(os.getenv('MEDICAL_RUNTIME_DIR',str(ROOT/'runtime'))).resolve()
    override=os.getenv('MEDICAL_USER_DATA_DIR')
    if override:
        return Path(override).resolve()
    # Isolated tests, demos and custom installations retain their own stores.
    explicit=os.getenv('MEDICAL_STORAGE_CONFIG')
    if not explicit and runtime not in ((ROOT/'runtime').resolve(),(ROOT/'runtime/public').resolve()):
        return runtime
    config=Path(explicit) if explicit else ROOT/'config/storage.local.toml'
    if not config.exists():
        return runtime
    data=tomllib.loads(config.read_text(encoding='utf-8-sig'))
    value=data.get('storage',{}).get('user_data_dir')
    if not isinstance(value,str) or not value.strip():
        raise RuntimeError('共享用户存储配置无效，请检查 storage.user_data_dir')
    target=Path(value)
    target=(target if target.is_absolute() else ROOT/target).resolve()
    if not all((target/name).is_file() for name in ('family.sqlite','conversations.sqlite','monitor.sqlite')):
        raise RuntimeError('共享用户数据尚未完成迁移，拒绝创建空账号库。')
    return target
