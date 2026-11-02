import uuid
import streamlit as st
from agents import family as store
from agents import accounts
from langchain_core.chat_history import InMemoryChatMessageHistory

_storage=st.components.v2.component('medical_identity_storage',html='<span></span>',js='''
export default function(component) {
  const {data, setStateValue} = component;
  try {
    const key = 'medical_auth_session_v2';
    const legacy = 'medical_personal_identity_v1';
    if (data.command?.action === 'save') {
      localStorage.setItem(key, data.command.token); localStorage.removeItem(legacy);
    }
    if (data.command?.action === 'clear') { localStorage.removeItem(key); localStorage.removeItem(legacy); }
    const saved = localStorage.getItem(key) || localStorage.getItem(legacy);
    if (!data.current && data.command?.action !== 'clear' && saved) setStateValue('token', saved);
  } catch (_) { }
}
''')

def connect_identity(token,remember=False):
    profile=store.identity_profile(token)
    families=store.my_families(token)
    if st.session_state.get('conversation_id'):
        from conversation_ui import persist_current
        try: persist_current()
        except PermissionError: pass
    st.session_state.clear()
    st.session_state.personal_token=token
    st.session_state.user_id='member_'+profile['id']
    st.session_state.session_id=uuid.uuid4().hex[:12]
    st.session_state.history=InMemoryChatMessageHistory()
    st.session_state.turns=[]
    for key in ['agent_tests','vision_result','vision_hash','vision_handoff']:
        st.session_state.pop(key,None)
    st.session_state.family_token=token+'.'+families[0]['member_id'] if families else ''
    st.session_state.identity_browser_command=dict(action='save',token=token) if remember else dict(action='clear')

def _restore():
    state=st.session_state.get('identity_storage',{})
    token=state.get('token') if isinstance(state,dict) else getattr(state,'token',None)
    if token and not st.session_state.get('personal_token'):
        try: connect_identity(token,remember=True)
        except PermissionError: st.session_state.identity_browser_command=dict(action='clear')

def bootstrap_identity():
    current=st.session_state.get('personal_token')
    profile=None
    if current:
        try: profile=store.identity_profile(current)
        except PermissionError:
            st.session_state.clear()
            st.session_state.identity_browser_command=dict(action='clear')
            st.session_state.auth_notice='登录已过期、已撤销或账号已停用，请重新登录或联系管理员。'
            st.rerun()
    _storage(key='identity_storage',data=dict(current=bool(st.session_state.get('personal_token')),command=st.session_state.get('identity_browser_command',{})),default={'token':None},on_token_change=_restore,height=0)
    return profile

def disconnect_identity():
    from conversation_ui import persist_current
    try: persist_current()
    except PermissionError: pass
    accounts.logout(st.session_state.get('personal_token'))
    st.session_state.clear()
    st.session_state.identity_browser_command=dict(action='clear')
    st.session_state.pop('identity_storage',None)
    st.session_state.user_id='guest_'+uuid.uuid4().hex[:12]
    st.rerun()

def family_switcher():
    token=st.session_state.get('personal_token')
    if not token: return
    try:
        profile=store.identity_profile(token); families=store.my_families(token)
    except PermissionError: return
    st.caption(('已登录 · ' if profile.get('username') else '旧身份 · ')+profile['display'])
    if families:
        ids=[x['member_id'] for x in families]; names={x['member_id']:x['name'] for x in families}
        current=st.session_state.get('family_token','').split('.')[-1]
        preferred=st.session_state.pop('preferred_family',None)
        if preferred in ids: st.session_state['family_selection_'+profile['id']]=preferred
        selected=st.selectbox('当前家庭',ids,index=ids.index(current) if current in ids else 0,format_func=lambda mid:names[mid],key='family_selection_'+profile['id'])
        st.session_state.family_token=token+'.'+selected
