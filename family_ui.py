import streamlit as st
from agents.household_agents import tools as store


def open_membership(token,action,already_member=False):
    """Select the verified membership, then show a durable result on its page."""
    from agents import family
    owner=family.identity_profile(st.session_state.personal_token)
    person=family.profile(token)
    mine=family.my_families(st.session_state.personal_token)
    if person['id'] not in {item['member_id'] for item in mine}:
        raise PermissionError('当前账号无权切换到该家庭')
    st.session_state.family_token=token
    st.session_state.preferred_family=person['id']
    st.session_state.family_membership_notice=dict(owner=owner['id'],group_id=person['group_id'],
                                                  action=action,already_member=bool(already_member))


def membership_feedback(person):
    from agents import family
    notice=st.session_state.get('family_membership_notice')
    if not notice:return
    owner=family.identity_profile(st.session_state.personal_token)
    if notice.get('owner')!=owner['id']:
        st.session_state.pop('family_membership_notice',None)
        return
    if notice.get('group_id')!=person['group_id']:
        st.session_state.pop('family_membership_notice',None)
        return
    if notice.get('already_member'):
        st.info('你已是「'+person['family']+'」的成员，已为你打开该家庭。',icon=':material/info:')
    else:
        action={'创建家庭':'已创建','加入家庭':'已成功加入','找回旧家庭':'已找回'}.get(notice.get('action'),'已进入')
        st.success(action+'「'+person['family']+'」。',icon=':material/check_circle:')
    name='@'+owner['username'] if owner.get('username') else owner['display']
    st.caption('当前登录账号：'+name+' · 家庭中共有 '+str(len(store.members(st.session_state.family_token)))+' 位成员')
    if st.button('我知道了',key='membership_ack_'+person['group_id']):
        st.session_state.pop('family_membership_notice',None);st.rerun()

def require_member():
    token=st.session_state.get('family_token','')
    try: return store.profile(token)
    except PermissionError:
        st.info('请先登录账号，再在“我的家庭”创建或加入家庭。')
        st.page_link('app_pages/family_home.py',label='查看我的家庭',icon=':material/family_restroom:')
        st.stop()

def target_picker(permission='can_read',include_ungranted=False):
    person=store.profile(st.session_state.family_token)
    choices=[x for x in store.members(st.session_state.family_token) if include_ungranted or x[permission]]
    if not choices:
        st.info('暂无成员授予这项权限。'); st.stop()
    preferred=st.session_state.pop('preferred_target_'+permission,None)
    key='target_'+permission+'_'+person['id']
    ids=[row['id'] for row in choices]
    cached=st.session_state.get(key)
    if isinstance(cached,dict):st.session_state[key]=cached.get('id')
    if st.session_state.get(key) not in ids:st.session_state[key]=person['id'] if person['id'] in ids else ids[0]
    if preferred in ids:st.session_state[key]=preferred
    roster={row['id']:row for row in choices}
    def label(mid):
        row=roster[mid]
        name=row['name']+(' · @'+row['username'] if row.get('username') else '')
        if include_ungranted:name+='（我自己）' if mid==person['id'] else '（可代设）' if row[permission] else '（待授权）'
        return name
    selected=st.selectbox('选择成员',ids,format_func=label,key=key)
    return roster[selected]

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
        requests=store.reminder_requests(token)
        if requests:
            st.caption('待处理的代设提醒申请：'+str(len(requests)))
            st.page_link('app_pages/agent_schedule.py',label='处理提醒授权',icon=':material/verified_user:')
    except PermissionError: st.caption('家庭连接已失效，请重新连接。')
