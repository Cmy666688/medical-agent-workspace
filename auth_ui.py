"""Account forms shared by the account page and the family onboarding page."""
import streamlit as st
from agents import accounts,family
from identity_ui import connect_identity,disconnect_identity


def _connected(result,remember):
    connect_identity(result['token'],remember)
    st.session_state.account_recovery=result['recovery']
    st.session_state.auth_success='账号已准备好，欢迎加入医知协作。'
    st.rerun()


def auth_panel():
    with st.container(horizontal_alignment='center'):
        with st.container(width=1160,horizontal_alignment='left'):
            _auth_content()


def _auth_content():
    st.image('assets/brand-wordmark.svg',width=184,alt='医知协作品牌标识')
    st.space('small')
    user_agent=st.context.headers.get('User-Agent','').lower()
    mobile=any(value in user_agent for value in ('mobile','android','iphone','ipod'))
    if mobile:
        form=st.container()
        hero=st.container()
    else:
        hero,form=st.columns([1.25,1],gap='large',vertical_alignment='center')
    with hero:
        st.caption('HEALTH, TOGETHER')
        if mobile: st.subheader('健康有据，关怀有回应。')
        else: st.title('健康有据，关怀有回应。')
        st.write('让问诊准备更清楚，让家人的日常更安心。\n\n从一次咨询、一份资料，到每一次准时的关怀，在这里连接起来。')
        st.image('assets/wellness-orbit.svg',width='stretch',alt='墨绿色空间中的健康轨道，连接问诊资料、家庭和沟通')
        st.caption('问诊准备　 /　 医疗资料　 /　 家庭关怀')
    with form:
        with st.container(border=True,gap='small'):
            mode=st.segmented_control('账户操作',['登录','注册'],default='登录',width='stretch',key='auth_mode',label_visibility='collapsed')
            st.subheader('欢迎回来' if mode=='登录' else '创建你的账号')
            st.caption('登录后使用问诊、资料查询与家庭协作。' if mode=='登录' else '注册后即可使用系统功能，并创建或加入家庭。')
            notice=st.session_state.pop('auth_notice',None)
            if notice: st.info(notice)
            with st.form('account_auth',clear_on_submit=True,border=False):
                username=st.text_input('用户名',placeholder='3～32 位字母、数字或下划线',max_chars=32,icon=':material/person:')
                if mode=='注册': display=st.text_input('怎么称呼你',placeholder='例如：小陈',max_chars=40,icon=':material/badge:')
                password=st.text_input('密码',type='password',placeholder='至少 8 位',max_chars=128,icon=':material/lock:')
                if mode=='注册': confirm=st.text_input('确认密码',type='password',max_chars=128)
                remember=st.checkbox('在这台私人设备上保持登录',help='保存可撤销的登录令牌，最长 30 天；不会保存密码。')
                submit=st.form_submit_button('登录' if mode=='登录' else '注册并进入',type='primary',width='stretch')
            if submit:
                try:
                    if mode=='注册':
                        if password!=confirm: raise ValueError('两次输入的密码不一致。')
                        _connected(accounts.register(username,password,display,remember=remember),remember)
                    else:
                        token=accounts.login(username,password,remember)
                        connect_identity(token,remember); st.rerun()
                except (ValueError,PermissionError) as exc: st.error(str(exc))
            st.caption('在同一服务登录，继续连接自己的家庭。')
        with st.expander('忘记密码？'):
            st.caption('使用注册时保存的恢复码重设密码。重设后，其他设备会退出登录。')
            with st.form('account_recover',clear_on_submit=True):
                username=st.text_input('需要恢复的用户名')
                recovery=st.text_input('账号恢复码',type='password',max_chars=256)
                password=st.text_input('新密码',type='password',max_chars=128)
                confirm=st.text_input('再次输入新密码',type='password',max_chars=128)
                submitted=st.form_submit_button('重设密码')
            if submitted:
                try:
                    if password!=confirm: raise ValueError('两次输入的密码不一致。')
                    _connected(accounts.recover(username,recovery,password),False)
                except (ValueError,PermissionError) as exc: st.error(str(exc))
        with st.expander('以前用身份凭证创建过家庭？'):
            st.caption('先恢复旧身份，再绑定用户名和密码。家庭、成员和已有记录会保留。')
            with st.form('legacy_identity',clear_on_submit=True):
                token=st.text_input('原个人身份凭证',type='password',max_chars=256)
                submitted=st.form_submit_button('恢复旧身份')
            if submitted:
                try: connect_identity(token.strip()); st.rerun()
                except PermissionError: st.error('身份凭证无效，请核对原凭证。')


def recovery_card():
    recovery=st.session_state.get('account_recovery')
    if not recovery: return
    with st.container(border=True):
        st.subheader('保存你的账号恢复码',icon=':material/key:')
        st.write('忘记密码时可用它恢复账号。请保存在私人位置，不要发给家人或其他人。')
        with st.expander('查看恢复码'): st.code(recovery)
        with st.container(horizontal=True):
            st.download_button('下载恢复码',recovery,file_name='医知协作账号恢复码.txt',icon=':material/download:')
            if st.button('已保存，隐藏恢复码'):
                st.session_state.pop('account_recovery',None); st.rerun()


def account_panel():
    token=st.session_state.personal_token; profile=family.identity_profile(token)
    st.caption('个人空间 / 账户与安全')
    st.title('我的账户',icon=':material/account_circle:')
    st.write('你好，'+profile['display']+'。在这里管理登录和家庭访问。')
    if not profile.get('username'):
        st.info('当前是旧身份。绑定用户名和密码后，即可直接登录并找回原来的家庭。')
        with st.form('upgrade_account',clear_on_submit=True):
            username=st.text_input('设置用户名',max_chars=32)
            password=st.text_input('设置密码',type='password',max_chars=128)
            confirm=st.text_input('确认密码',type='password',max_chars=128)
            remember=st.checkbox('在这台私人设备上保持登录')
            submitted=st.form_submit_button('绑定账号，保留原有家庭',type='primary')
        if submitted:
            try:
                if password!=confirm: raise ValueError('两次输入的密码不一致。')
                _connected(accounts.register(username,password,profile['display'],legacy_token=token,remember=remember),remember)
            except (ValueError,PermissionError) as exc: st.error(str(exc))
    else:
        st.badge('@'+profile['username'],icon=':material/verified_user:',color='green')
        st.write('你的家庭关系与授权记录已关联到此账号。')
        recovery_card()
        st.badge('管理员' if profile.get('role')=='admin' else '普通用户',icon=':material/verified_user:')
        with st.expander('修改我的称呼'):
            with st.form('update_my_display'):
                display=st.text_input('我的称呼',value=profile['display'],max_chars=40)
                if st.form_submit_button('保存称呼'):
                    try: accounts.update_display(token,display); st.rerun()
                    except ValueError as exc: st.error(str(exc))
        st.page_link('app_pages/conversations.py',label='我的历史对话 · 选择并继续',icon=':material/history:')
        if profile.get('role')=='admin':
            st.page_link('app_pages/users.py',label='进入用户管理',icon=':material/manage_accounts:')
        with st.container(horizontal=True):
            st.page_link('app_pages/family_home.py',label='进入我的家庭',icon=':material/family_restroom:')
            if st.button('退出登录',icon=':material/logout:'): disconnect_identity()
        with st.expander('修改密码'):
            with st.form('change_password',clear_on_submit=True):
                current=st.text_input('当前密码',type='password',max_chars=128)
                password=st.text_input('新密码',type='password',max_chars=128)
                confirm=st.text_input('确认新密码',type='password',max_chars=128)
                submitted=st.form_submit_button('更新密码并退出其他设备')
            if submitted:
                try:
                    if password!=confirm: raise ValueError('两次输入的密码不一致。')
                    refreshed=accounts.change_password(token,current,password)
                    connect_identity(refreshed); st.session_state.auth_success='密码已修改，其他设备已退出。'; st.rerun()
                except (ValueError,PermissionError) as exc: st.error(str(exc))
    success=st.session_state.pop('auth_success',None)
    if success: st.success(success)
