import streamlit as st
from agents.household_agents import tools as store
from family_ui import require_member,target_picker,inbox,shared_status

st.caption('医知协作 / 家庭组')
st.title('家属照护',icon=':material/diversity_1:')
st.write('记录自己的健康状况，查看已授权家人的记录，远程请求报平安或管理提醒。')
person=require_member(); token=st.session_state.family_token
st.info('当前展示成员手动录入和待办确认信息，不是实时生命体征监测。没有接入血压计、穿戴设备或远程桌面。')
st.subheader('家庭成员与共享状态')
for member in store.members(token):
    with st.container(border=True):
        st.markdown('**'+member['name']+('（我）' if member['id']==person['id'] else '')+'**')
        st.caption(('已允许查看健康记录' if member['can_read'] else '尚未授权查看')+' · '+('已允许管理提醒' if member['can_manage'] else '尚未授权管理提醒'))
        if not member['can_read']:
            st.caption('请让该成员在“家庭成员与留言 → 我的共享授权”中选择你。')
            if st.button('向'+member['name']+'请求共享',key='ask_share_'+member['id']):
                store.send_message(token,'我希望在家庭组查看你的健康记录。若你同意，请在“我的共享授权”中允许我查看。',member['id'])
                st.success('共享请求已发到对方的家庭私信，权限仍由对方决定。')
with st.expander('录入我的健康状况'):
    with st.form('health_record'):
        kind=st.selectbox('记录类型',['血压','状态'])
        sbp=st.number_input('收缩压 mmHg',30,300,120)
        dbp=st.number_input('舒张压 mmHg',20,250,80)
        note=st.text_area('状态说明或备注',max_chars=1000)
        if st.form_submit_button('保存我的记录'):
            try:
                content={'收缩压':sbp,'舒张压':dbp,'备注':note} if kind=='血压' else {'说明':note}
                store.add_measurement(token,kind,content); st.success('记录已保存')
            except ValueError as exc: st.error(str(exc))
inbox()
target=target_picker('can_read')
if st.button('刷新成员状况'): st.rerun()
shared_status(target)
if target['can_manage']:
    st.subheader('远程关怀操作 · '+target['name'])
    with st.form('remote_checkin'):
        text=st.text_input('远程报平安 / 测量请求',value='请方便时测量并记录血压，然后在待办中确认。',max_chars=150)
        if st.form_submit_button('发送站内请求'):
            try: store.request_checkin(token,target['id'],text); st.success('已进入对方站内待办')
            except (ValueError,PermissionError) as exc: st.error(str(exc))
    st.page_link('app_pages/agent_schedule.py',label='管理获授权的提醒',icon=':material/alarm:')
    if st.button('为'+target['name']+'设置提醒'):
        st.session_state['preferred_target_can_manage']=target['id']
        st.switch_page('app_pages/agent_schedule.py')
    with st.expander('远程暂停或恢复提醒计划'):
        plans=store.schedules(token,target['id'])
        if not plans: st.caption('该成员暂无提醒计划。')
        for plan in plans:
            st.write(plan['title']+' · '+('启用中' if plan['active'] else '已暂停'))
            if st.button('暂停此提醒' if plan['active'] else '恢复此提醒',key='remote_toggle_'+plan['id']):
                store.toggle_schedule(token,plan['id'],not plan['active']); st.rerun()
else: st.caption('对方只共享了查看权限。如需管理提醒，请让对方单独授权。')
with st.expander('谁访问过我的记录或修改过我的提醒'):
    st.dataframe(store.audit_log(token),hide_index=True)
