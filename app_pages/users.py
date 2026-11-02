import streamlit as st

from agents import family, user_management as users

token=st.session_state.personal_token
profile=family.identity_profile(token)
if profile.get('role')!='admin':
    st.error('仅管理员可访问用户管理。')
    st.stop()

st.caption('服务管理 / 用户与权限')
st.title('用户管理',icon=':material/manage_accounts:')
st.write('管理本服务的注册账号、访问状态和登录会话。')
st.caption('此处只显示账号资料，不读取用户问诊、核对卡或家庭消息。账号停用后，已有数据仍会保留。')
notice=st.session_state.pop('user_admin_notice',None)
if notice: st.success(notice)
query=st.text_input('搜索用户',placeholder='输入用户名或称呼',max_chars=40)
rows=users.listing(token,query)
with st.container(horizontal=True):
    st.metric('匹配账号',len(rows),border=True)
    st.metric('已启用',sum(bool(row['enabled']) for row in rows),border=True)
    st.metric('管理员',sum(row['role']=='admin' for row in rows),border=True)
for row in rows:
    identity=row['identity']
    with st.expander(row['username']+' · '+row['display']+' · '+('已启用' if row['enabled'] else '已停用')):
        st.caption('注册时间：'+row['created'][:19].replace('T',' ')+'（北京时间）')
        st.caption('有效登录会话：'+str(row['sessions'])+' · '+('当前管理员' if identity==profile['id'] else '可撤销其全部会话'))
        with st.form('manage_user_'+identity):
            display=st.text_input('称呼',value=row['display'],max_chars=40)
            role=st.selectbox('账号角色',['user','admin'],index=0 if row['role']=='user' else 1,
                              format_func=lambda value:'普通用户' if value=='user' else '管理员')
            enabled=st.checkbox('允许此账号登录',value=bool(row['enabled']))
            submitted=st.form_submit_button('保存用户设置')
        if submitted:
            try:
                users.update(token,identity,display=display,role=role,enabled=enabled)
                st.session_state.user_admin_notice='用户设置已保存。权限或状态变更后，该用户需要重新登录。'
                st.rerun()
            except (ValueError,PermissionError) as exc: st.error(str(exc))
        if identity!=profile['id']:
            confirmed=st.checkbox('确认退出此用户的全部登录设备',key='revoke_confirm_'+identity)
            if st.button('撤销全部登录会话',key='revoke_user_'+identity,disabled=not confirmed):
                users.revoke_sessions(token,identity)
                st.session_state.user_admin_notice='该用户的登录会话已撤销，数据已保留。'
                st.rerun()

with st.expander('创建新用户',icon=':material/person_add:'):
    with st.form('admin_create_user',clear_on_submit=True):
        username=st.text_input('新用户名',max_chars=32)
        display=st.text_input('用户称呼',max_chars=40)
        password=st.text_input('初始密码',type='password',max_chars=128)
        confirm=st.text_input('确认初始密码',type='password',max_chars=128)
        submitted=st.form_submit_button('创建普通用户')
    if submitted:
        try:
            if password!=confirm: raise ValueError('两次输入的密码不一致。')
            recovery=users.create(token,username,password,display)
            st.success('普通用户已创建。请私下交付初始密码和恢复码，用户登录后可自行修改密码。')
            st.download_button('下载新账号恢复码',recovery,file_name='新账号恢复码.txt',mime='text/plain')
        except (ValueError,PermissionError) as exc: st.error(str(exc))
with st.expander('账号管理操作记录',icon=':material/history:'):
    events=users.audit_log(token)
    actions={'account.create':'创建账号','account.revoke_sessions':'撤销登录会话','account.bootstrap_admin':'本机配置管理员'}
    for item in events:
        action=actions.get(item['action'],'更新角色或启用状态')
        st.text(f"{item['time'][:19].replace('T',' ')} · {item['actor'] or '本机命令'} → {item['target']} · {action}")
    if not events: st.caption('暂无管理操作记录。')
