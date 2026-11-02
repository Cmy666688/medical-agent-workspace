import uuid
import streamlit as st
from langchain_core.chat_history import InMemoryChatMessageHistory
from agents import conversations as store
from agents.family import identity_profile

def _clear_context():
    st.session_state.history=InMemoryChatMessageHistory()
    st.session_state.turns=[]
    st.session_state.agent_tests={}
    for key in list(st.session_state):
        if key.startswith(('embedded_vision_','feedback_','saved_','consultation_context_','check_card_','coordinator_question_','coordinator_turn_')) or key in ('vision_result','vision_hash','vision_handoff','card_saved_notice','consultation_failure_notice','consultation_failed_timeline'):
            st.session_state.pop(key,None)

def _context():
    return {name:st.session_state.get('consultation_context_'+name,default) for name,default in [('age',0),('allergies',''),('medications','')]}

def persist_current():
    token=st.session_state.get('personal_token'); key=st.session_state.get('conversation_id')
    if not token or not key: return
    if st.session_state.get('conversation_owner') != identity_profile(token)['id']: return
    if not store.exists(token,key): return
    saved=st.session_state.get('persisted_requests',set())
    for turn in st.session_state.get('turns',[]):
        if turn['request'] not in saved:
            store.append(token,key,turn)
            saved.add(turn['request'])
    st.session_state.persisted_requests=saved
    # Widget state may be absent after navigating away; do not overwrite saved details with blanks.
    if any(key.startswith('consultation_context_') for key in st.session_state): store.context(token,key,_context())

def _restore(key):
    record=store.load(st.session_state.personal_token,key)
    _clear_context()
    st.session_state.conversation_id=key; st.session_state.session_id=key
    st.session_state.conversation_owner=identity_profile(st.session_state.personal_token)['id']
    store.select_active(st.session_state.personal_token,key)
    st.session_state.turns=record['turns']
    st.session_state.persisted_requests={turn['request'] for turn in record['turns']}
    for turn in record['turns'][-6:]:
        st.session_state.history.add_user_message(turn['question']); st.session_state.history.add_ai_message(turn['answer'])
    for name,value in record['context'].items(): st.session_state['consultation_context_'+name]=value

def ensure_conversation():
    owner=identity_profile(st.session_state.personal_token)['id']
    cached_owner=st.session_state.get('conversation_owner')
    if cached_owner is not None and cached_owner!=owner:
        _clear_context(); st.session_state.pop('conversation_id',None)
        for key in ('family_token','preferred_family','family_invites','new_family_credentials','family_membership_notice','account_recovery'):
            st.session_state.pop(key,None)
    current=st.session_state.get('conversation_id')
    if current:
        if store.exists(st.session_state.personal_token,current):
            if cached_owner==owner: return
            _restore(current); return
        _clear_context(); st.session_state.pop('conversation_id',None)
    token=st.session_state.personal_token
    old=st.session_state.get('turns',[])
    if old and cached_owner==owner:
        key=store.create(token)
        for turn in old: store.append(token,key,turn)
        store.context(token,key,_context())
    else:
        records=store.listing(token)
        key=store.active(token) or (records[0]['id'] if records else store.create(token))
    _restore(key)

def new_conversation():
    persist_current()
    key=store.create(st.session_state.personal_token)
    _restore(key)
    st.session_state.open_new_consultation=True

def switch_conversation(key):
    # Authorize the target before changing or persisting any in-memory state.
    store.load(st.session_state.personal_token,key)
    persist_current(); _restore(key)
    st.session_state.open_new_consultation=True


def continue_conversation():
    persist_current()
    key=store.continue_from(st.session_state.personal_token,st.session_state.conversation_id)
    _restore(key)
    st.session_state.open_new_consultation=True


def conversation_header():
    from agents.llm import quota_usage
    from ui import llm_config
    token=st.session_state.personal_token; key=st.session_state.conversation_id
    conversation=store.load(token,key)
    profile=identity_profile(token)
    with st.container(border=True):
        st.text('当前对话：'+conversation['title'])
        st.caption(f"账号：{profile['username']} · 已保存 {len(conversation['turns'])} 轮 · 直接在下方输入可继续本段对话")
        config=llm_config()
        if config.api_key:
            remaining=max(0,config.session_tokens-quota_usage(key))
            if remaining<config.budget_tokens:
                st.warning('本段模型调用预留额度已较少，可保留记录、已确认信息和近期上下文开启续聊。')
                st.button('保留上下文开启续聊',on_click=continue_conversation,
                          icon=':material/forum:',key='continue_with_context')
                st.caption('原对话保持不变。续聊不会重置账号当日总额度。')

def recent_conversations():
    records=store.listing(st.session_state.personal_token)
    with st.expander('最近对话',expanded=True,icon=':material/history:'):
        for item in records[:4]:
            label=('当前 · ' if item['id']==st.session_state.conversation_id else '')+item['title']
            st.button(label,key='recent_chat_'+item['id'],on_click=switch_conversation,args=(item['id'],),width='stretch')

def restore_context():
    values=store.get_context(st.session_state.personal_token,st.session_state.conversation_id)
    for name,value in values.items():
        key='consultation_context_'+name
        if key not in st.session_state: st.session_state[key]=value
