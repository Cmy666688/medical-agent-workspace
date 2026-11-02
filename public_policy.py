"""Deployment controls; local workstation behavior is unchanged."""
import os

def public_mode():
    return os.getenv('MEDICAL_PUBLIC_MODE')=='1'


def is_project_admin():
    import streamlit as st
    from agents.family import identity_profile
    token=st.session_state.get('personal_token')
    try:return bool(token) and identity_profile(token).get('role')=='admin'
    except PermissionError:return False


def require_project_admin():
    import streamlit as st
    if not is_project_admin():
        st.error('仅管理员可访问项目管理，请使用管理员账号登录。')
        st.stop()

def management_notice():
    import streamlit as st
    st.title('此功能由服务管理者维护')
    st.info('问诊、资料查询与家庭协作可在工作台使用。服务配置与用户管理仅向相应管理员开放。')

def reserve_public(db,session,tokens):
    """Shared daily limits cannot be reset by starting a new conversation."""
    from datetime import datetime,timezone,timedelta
    day=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    identity=db.execute('SELECT user_id FROM users WHERE session=?',(session,)).fetchone()
    owner=identity[0] if identity else session
    db.execute('CREATE TABLE IF NOT EXISTS public_quota (day TEXT, owner TEXT, tokens INTEGER)')
    total=db.execute('SELECT COALESCE(SUM(tokens),0) FROM public_quota WHERE day=?',(day,)).fetchone()[0]
    personal=db.execute('SELECT COALESCE(SUM(tokens),0) FROM public_quota WHERE day=? AND owner=?',(day,owner)).fetchone()[0]
    if total+tokens>int(os.getenv('MEDICAL_PUBLIC_DAILY_TOKENS','2000000')) or personal+tokens>int(os.getenv('MEDICAL_PUBLIC_USER_TOKENS','200000')):
        from agents.llm import LLMError
        raise LLMError('public_daily_budget')
    db.execute('INSERT INTO public_quota VALUES (?,?,?)',(day,owner,tokens))
