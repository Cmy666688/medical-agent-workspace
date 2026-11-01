import streamlit as st
from agents.household_agents import tools as store

def require_member():
    token=st.session_state.get('family_token','')
    try: return store.profile(token)
    except PermissionError:
        st.info('请先登录账号，再在“我的家庭”创建或加入家庭。')
        st.page_link('app_pages/family_home.py',label='查看我的家庭',icon=':material/family_restroom:')
        st.stop()

def target_picker(permission='can_read'):
    choices=[x for x in store.members(st.session_state.family_token) if x[permission]]
    if not choices:
        st.info('暂无成员授予这项权限。'); st.stop()
    preferred=st.session_state.pop('preferred_target_'+permission,None)
    key='target_'+permission+'_'+store.profile(st.session_state.family_token)['id']
    if preferred:
        match=next((r for r in choices if r['id']==preferred),None)
        if match: st.session_state[key]=match
    return st.selectbox('选择成员',choices,format_func=lambda x:x['name'],key=key)

@st.fragment(run_every='20s')
def inbox():
    try:
        profile=store.profile(st.session_state.family_token)
        store.poll_reminders()
        rows=store.notices(st.session_state.family_token,profile['id'])
        pending=[x for x in rows if x['status']=='pending']
        st.subheader(f'我的待办 · {len(pending)} 项')
        if not pending: st.caption('当前没有待确认的提醒。页面每 20 秒更新一次。')
        for item in pending:
            with st.container(border=True):
                st.write(item['title'])
                st.caption('计划时间：'+item['due'][:16].replace('T',' ')+'（北京时间）')
                if st.button('确认完成',key='done_'+item['id']):
                    store.complete_notice(st.session_state.family_token,item['id']); st.rerun(scope='fragment')
    except PermissionError: st.info('成员连接已失效，请重新连接。')

@st.fragment(run_every='20s')
def shared_status(target):
    token=st.session_state.family_token
    try:
        records=store.health_records(token,target['id'])
        st.subheader(target['name']+'的最近记录')
        if records:
            st.caption('最近录入时间：'+records[0]['time'][:16].replace('T',' '))
            for record in records[:10]:
                with st.container(border=True):
                    st.caption(record['time'][:16].replace('T',' ')+' · '+record['kind'])
                    values=record['values']
                    if record['kind']=='血压':
                        st.metric('记录的血压',str(values['收缩压'])+'/'+str(values['舒张压'])+' mmHg')
                        if values.get('备注'): st.write(values['备注'])
                    else: st.write(values.get('说明',''))
        else: st.caption('暂无录入记录；缺少记录不代表健康状况正常。')
        st.subheader('提醒完成情况')
        st.dataframe([dict(计划时间=n['due'][:16],事项=n['title'],状态={'pending':'待确认','done':'已确认完成','cancelled':'已取消'}.get(n['status'],n['status']),完成时间=n['done_at']) for n in store.notices(token,target['id'])],hide_index=True)
        st.caption('每 20 秒更新；数据来自成员录入和本人确认。')
    except PermissionError: st.info('共享权限已变更，当前不能查看此成员记录。')

@st.fragment(run_every='10s')
def message_board():
    try:
        for message in store.messages(st.session_state.family_token):
            with st.container(border=True):
                audience='私信 → '+message['recipient_name'] if message['recipient'] else '家庭公开'
                st.caption(message['name']+' · '+audience+' · '+message['time'][:16].replace('T',' ')); st.text(message['body'])
    except PermissionError: st.info('请重新连接家庭。')

@st.fragment(run_every='20s')
def global_reminder():
    try:
        token=st.session_state.family_token; person=store.profile(token); store.poll_reminders()
        pending=[x for x in store.notices(token,person['id']) if x['status']=='pending']
        st.caption(person['family']+' · '+person['name'])
        st.write(f':material/alarm: 待确认提醒：{len(pending)}')
        seen=st.session_state.get('seen_notices',set())
        if any(x['id'] not in seen for x in pending): st.toast('有新的家庭关怀提醒，请查看待办并确认。',icon=':material/alarm:')
        st.session_state.seen_notices=seen|{x['id'] for x in pending}
        st.page_link('app_pages/agent_schedule.py',label='查看我的待办')
    except PermissionError: st.caption('家庭连接已失效，请重新连接。')
