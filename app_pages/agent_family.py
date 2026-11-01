import streamlit as st
from agents.household_agents import tools as store

st.caption('医知协作 / 家庭组')
st.title('家庭成员与留言',icon=':material/family_restroom:')
st.write('创建家庭、邀请亲属、共享指定健康记录，在家庭留言板沟通。')
token=st.session_state.get('family_token','')
try: person=store.profile(token)
except PermissionError: person=None
if not person:
    st.info('请先登录账号，再在“我的家庭”创建或加入家庭。')
    st.page_link('app_pages/family_home.py',label='进入我的家庭',icon=':material/family_restroom:')

else:
    st.success(person['family']+' · '+person['name'])
    creds=st.session_state.get('new_family_credentials',{})
    if creds:
        with st.expander('家庭邀请信息',expanded=True):
            st.caption('家庭邀请码有效 7 天，创建者可随时刷新。家人使用各自账号和此邀请码加入。')
            if creds.get('token'): st.code(creds['token'])
            if creds.get('invite'): st.write('家庭邀请码'); st.code(creds['invite'])
            if st.button('我已保存，隐藏凭据'): st.session_state.new_family_credentials={}; st.rerun()
    with st.container(horizontal=True):
        if person['role']=='owner' and st.button('刷新家庭邀请码'):
            st.session_state.new_family_credentials=dict(invite=store.rotate_invite(token)); st.rerun()
        st.page_link('app_pages/family_home.py',label='查看或切换其他家庭',icon=':material/family_restroom:')
    roster=store.members(token)
    st.subheader('家庭成员')
    st.dataframe([dict(称呼=r['name'],身份='创建者' if r['role']=='owner' else '成员',允许我查看=r['can_read'],允许我管理提醒=r['can_manage']) for r in roster],hide_index=True)
    st.subheader('我的共享授权')
    st.caption('只有你能授权自己的健康记录。家庭创建者不会自动获得他人的健康查看或提醒管理权限。取消勾选并保存即可撤回。')
    others=[x for x in roster if x['id']!=person['id']]
    grants={x['viewer']:x for x in store.grants_given(token)}
    for item in others:
        grant=grants.get(item['id'],{})
        with st.form('grant_'+item['id']):
            st.write(item['name'])
            read=st.checkbox('允许查看我的健康记录和待办',value=bool(grant.get('can_read')),key='read_'+item['id'])
            manage=st.checkbox('允许管理我的提醒和发起报平安请求',value=bool(grant.get('can_manage')),key='manage_'+item['id'])
            if st.form_submit_button('保存授权'):
                store.set_grant(token,item['id'],read,manage); st.success('授权已更新')
    st.subheader('家庭留言板')
    st.caption('发给全体成员的留言在组内公开；指定成员留言仅发送者与收件人可见，创建者也不会额外获得查看权限。')
    mode=st.segmented_control('发送范围',['全体家庭成员','指定成员私信'],default='全体家庭成员',key='message_mode_'+person['id'])
    private=mode=='指定成员私信'
    if private and not others: st.info('当前家庭还没有其他成员。请让对方注册账号并通过邀请码加入当前家庭，加入后即可选择收件人。')
    labels={item['id']:item['name']+' · '+('@'+item['username'] if item.get('username') else '成员 '+item['id'][-4:]) for item in others}
    recipient=st.selectbox('选择收件成员',list(labels),format_func=lambda value:labels[value],key='message_recipient_'+person['id'],index=None,placeholder='选择当前家庭中的成员') if private and others else None
    with st.form('family_message',clear_on_submit=True):
        body=st.text_area('给家人的留言',max_chars=1000)
        if st.form_submit_button('发送留言',disabled=mode not in ('全体家庭成员','指定成员私信') or (private and not recipient)):
            try:
                if mode not in ('全体家庭成员','指定成员私信'): raise ValueError('请选择留言发送范围')
                if private and recipient not in labels: raise ValueError('请选择当前家庭的收件成员')
                store.send_message(token,body,recipient if private else None)
                st.success('已私信发送给 '+labels[recipient] if private else '已发送给全体家庭成员')
            except (ValueError,PermissionError) as exc: st.error(str(exc))
    if st.button('刷新家庭留言'): st.rerun()
    from family_ui import message_board
    message_board()
