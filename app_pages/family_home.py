import streamlit as st
from agents import family as store
from agents.household_agents import tools as household
from auth_ui import auth_panel,recovery_card

personal=st.session_state.get('personal_token')
if not personal:
    auth_panel()
else:
    profile=store.identity_profile(personal)
    families=store.my_families(personal)
    st.caption('医知协作 / 家庭健康空间')
    heading,account=st.columns([3,1],vertical_alignment='bottom')
    with heading:
        st.title('我的家庭',icon=':material/family_restroom:')
        st.write('你好，'+profile['display']+'。让家人的近况有处可看，让日常关怀准时到达。')
    with account:
        st.page_link('app_pages/account.py',label='我的账户' if profile.get('username') else '升级为登录账号',icon=':material/account_circle:')
    if not profile.get('username'):
        st.info('已恢复旧身份。到“我的账户”绑定用户名和密码，就能直接登录并保留这些家庭。')
    success=st.session_state.pop('auth_success',None)
    if success: st.success(success)
    recovery_card()
    stats=st.columns(3)
    stats[0].metric('我的家庭',len(families),border=True)
    stats[1].metric('我创建的家庭',sum(x['role']=='owner' for x in families),border=True)
    stats[2].metric('我加入的家庭',sum(x['role']!='owner' for x in families),border=True)
    st.subheader('在这里，连接彼此')
    if families:
        columns=st.columns(2)
        for index,item in enumerate(families):
            with columns[index%2].container(border=True,height='stretch'):
                st.badge('我创建的家庭' if item['role']=='owner' else '我加入的家庭',icon=':material/home:',color='green' if item['role']=='owner' else 'blue')
                st.subheader(item['name'])
                st.caption(str(item['member_count'])+' 位成员 · 我的称呼：'+item['member_name'])
                st.write('共享近况、互相留言，安排家人的每日关怀。')
                if st.button('进入家庭',key='open_'+item['member_id'],icon=':material/arrow_forward:',width='stretch'):
                    st.session_state.family_token=personal+'.'+item['member_id']
                    st.session_state.preferred_family=item['member_id']
                    st.switch_page('app_pages/agent_family.py')
    else:
        with st.container(border=True):
            content,picture=st.columns([1.4,1],vertical_alignment='center')
            with content:
                st.subheader('从一个家庭开始',icon=':material/add_home:')
                st.write('为你的家创建一个共同空间，邀请父母、伴侣或子女加入。已有家庭邀请码？也可以直接加入。')
                st.caption('健康记录由本人决定共享，加入家庭不会自动开放私人数据。')
            with picture: st.image('assets/wellness-orbit.svg',width='stretch',alt='连接家庭、健康资料与日常关怀的绿色轨道')
    st.space('small')
    operation,tips=st.columns([1.5,1],gap='large')
    with operation:
        with st.container(border=True):
            st.subheader('拓展你的家庭空间',icon=':material/group_add:')
            action=st.segmented_control('家庭操作',['创建家庭','加入家庭','找回旧家庭'],default='创建家庭',width='stretch')
            with st.form('family_membership',clear_on_submit=True):
                if action=='创建家庭':
                    name=st.text_input('家庭名称',placeholder='例如：我们温暖的小家',max_chars=80)
                    display=st.text_input('在家庭中的称呼',value=profile['display'],max_chars=40)
                elif action=='加入家庭':
                    invite=st.text_input('家庭邀请码',type='password',placeholder='向家庭创建人获取')
                    display=st.text_input('在家庭中的称呼',value=profile['display'],max_chars=40)
                else:
                    legacy=st.text_input('原成员访问密钥',type='password')
                    st.caption('关联旧版成员记录；原有的共享授权、提醒和留言都会保留。')
                submit=st.form_submit_button(action,type='primary',width='stretch')
            if submit:
                try:
                    if action=='找回旧家庭': member_token=store.import_membership(personal,legacy)
                    else:
                        result=household.create_family(name,display,identity_token=personal) if action=='创建家庭' else household.join_family(invite,display,identity_token=personal)
                        member_token=result['token']
                        st.session_state.new_family_credentials=dict(invite=result.get('invite')) if result.get('invite') else {}
                    st.session_state.family_token=member_token
                    st.session_state.preferred_family=member_token.split('.')[-1]
                    st.rerun()
                except (ValueError,PermissionError) as exc: st.error(str(exc))
    with tips:
        st.subheader('每一步关怀，都很简单')
        for icon,title,text in [('person_add','邀请家人','创建后分享邀请码，家人用各自账号加入。'),('lock','按需共享','本人授权后，家人才能查看记录或管理提醒。'),('favorite','保持联系','留一句话、请求报平安，让关心有回应。')]:
            with st.container(border=True):
                st.markdown(':material/'+icon+': **'+title+'**')
                st.caption(text)
