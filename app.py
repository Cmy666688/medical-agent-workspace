import uuid
import streamlit as st
from agent_catalog import AGENTS
from identity_ui import bootstrap_identity,family_switcher
from agents.telemetry import bind_user
from public_policy import public_mode,management_notice
from langchain_core.chat_history import InMemoryChatMessageHistory

st.set_page_config(page_title='医知协作 · 健康工作台', page_icon=':material/health_and_safety:', layout='wide',initial_sidebar_state='auto' if st.session_state.get('personal_token') else 'collapsed')
st.logo('assets/brand-wordmark.svg',size='large',icon_image='assets/brand-mark.svg')
if 'session_id' not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:12]
    st.session_state.history = InMemoryChatMessageHistory()
    st.session_state.turns = []
if 'user_id' not in st.session_state: st.session_state.user_id='guest_'+uuid.uuid4().hex[:12]
profile=bootstrap_identity()
if not profile or not profile.get('username'):
    def locked_page():
        from auth_ui import auth_panel,account_panel
        if profile: account_panel()
        else: auth_panel()
    # Known feature URLs render the login view without loading protected page scripts.
    routes=['home','coordinator','conversations','knowledge','agent_consultation','agent_retrieval','agent_medication','agent_risk','agent_education','family_home','agent_family','agent_care','agent_schedule','monitor','evaluation']
    public=[st.Page(locked_page,title='登录 / 注册',url_path='sign-in',default=True),st.Page('app_pages/account.py',title='登录 / 注册')]
    public.extend(st.Page(locked_page,title='登录 / 注册',url_path=route) for route in routes)
    page=st.navigation(public,position='hidden')
    page.run()
    st.stop()
from conversation_ui import ensure_conversation,recent_conversations
ensure_conversation()
with st.sidebar:
    family_switcher()
    if not public_mode():
        with st.popover('显示选项'):
            st.toggle('显示开发调试数据',key='developer_mode',value=False)
    from conversation_ui import new_conversation
    st.button('开始新对话', icon=':material/add:', width='stretch',type='primary',on_click=new_conversation)
    recent_conversations()
identity=(st.session_state.session_id,st.session_state.user_id)
if st.session_state.get('_bound_identity')!=identity:
    bind_user(*identity)
    st.session_state._bound_identity=identity
def workspace_redirect():
    st.switch_page('app_pages/home.py')

navigation={
    '账户': [st.Page('app_pages/account.py',title='我的账户',icon=':material/account_circle:'),st.Page(workspace_redirect,title='工作台',url_path='sign-in',visibility='hidden')],
    '工作台': [st.Page('app_pages/home.py',title='工作台概览',icon=':material/space_dashboard:',default=True),st.Page('app_pages/coordinator.py',title='多智能体协调器',icon=':material/account_tree:'),st.Page('app_pages/conversations.py',title='历史对话',icon=':material/history:'),st.Page('app_pages/knowledge.py',title='医疗知识库',icon=':material/menu_book:')],
    'Agent 中心': [st.Page('app_pages/'+meta['page']+'.py',title=meta['name'],icon=':material/'+meta['icon']+':') for key,meta in AGENTS.items() if key not in ('vision','family','schedule','care')],
    '家庭组': [st.Page('app_pages/family_home.py',title='我的家庭',icon=':material/family_restroom:'),st.Page('app_pages/agent_family.py',title='家庭成员与留言',icon=':material/groups:'),st.Page('app_pages/agent_care.py',title='家属照护',icon=':material/diversity_1:'),st.Page('app_pages/agent_schedule.py',title='关怀提醒',icon=':material/alarm:')],
    '项目管理': [st.Page('app_pages/monitor.py',title='运行监控',icon=':material/monitoring:'),st.Page('app_pages/evaluation.py',title='评估与设置',icon=':material/tune:')]
}
if public_mode():
    navigation.pop('项目管理')
    navigation['账户'].extend(st.Page(management_notice,title='服务管理',url_path=route,visibility='hidden') for route in ('monitor','evaluation'))
    st.session_state.developer_mode=False
page=st.navigation(navigation)
if st.session_state.pop('open_new_consultation',False): st.switch_page('app_pages/agent_consultation.py')
if st.session_state.get('family_token'):
    from family_ui import global_reminder
    with st.sidebar: global_reminder()
page.run()
