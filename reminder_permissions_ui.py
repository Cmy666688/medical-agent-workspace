"""Visible, member-owned delegation and request/approval for care reminders."""
import hashlib
import streamlit as st
from agents.household_agents import tools


def permissions_panel(person):
    token=st.session_state.family_token
    incoming=tools.reminder_requests(token)
    others=[row for row in tools.members(token) if row['id']!=person['id']]
    labels={row['id']:row['name']+(' · @'+row['username'] if row.get('username') else ' · 成员 '+row['id'][-4:]) for row in others}
    with st.expander('谁可以帮我设置提醒 / 处理授权申请',expanded=bool(incoming),icon=':material/verified_user:'):
        st.caption('在这里由你决定谁能代设、暂停或恢复你的提醒。健康记录查看权限另行设置。')
        notice=st.session_state.pop('reminder_permission_notice',None)
        if notice and notice.get('member')==person['id']:st.success(notice['text'])
        for item in incoming:
            with st.container(border=True):
                st.write(labels.get(item['requester'],item['name'])+' 申请帮你管理提醒')
                a,b=st.columns(2)
                for col,approved,text in [(a,True,'同意代设提醒'),(b,False,'暂不同意')]:
                    if col.button(text,key='respond_reminder_'+item['id']+'_'+str(approved)):
                        try:
                            tools.respond_reminder_access(token,item['id'],approved)
                            st.session_state.reminder_permission_notice=dict(member=person['id'],text='已同意这位家人代设提醒。' if approved else '已拒绝本次申请。')
                            st.rerun()
                        except (ValueError,PermissionError) as exc:st.error(str(exc))
        if not others:
            st.info('当前家庭只有你一位成员，邀请家人加入后即可设置代设权限。')
            st.page_link('app_pages/family_home.py',label='邀请家人加入家庭',icon=':material/group_add:')
            return
        granted=sorted(row['viewer'] for row in tools.grants_given(token) if row['can_manage'] and row['viewer'] in labels)
        revision=hashlib.sha256(','.join(granted).encode()).hexdigest()[:10]
        with st.form('reminder_delegates_'+person['id']+'_'+revision):
            selected=st.multiselect('允许代设我提醒的家人',list(labels),default=granted,format_func=labels.get)
            st.caption('取消已选成员并保存，可撤回其代设权限。')
            if st.form_submit_button('保存代设权限'):
                try:
                    tools.set_reminder_delegates(token,selected)
                    st.session_state.reminder_permission_notice=dict(member=person['id'],text='代设权限已保存。')
                    st.rerun()
                except (ValueError,PermissionError) as exc:st.error(str(exc))


def request_access(target):
    token=st.session_state.family_token
    st.info(target['name']+' 尚未授权你代设提醒。可先发送申请，由对方在本页同意。')
    status=tools.reminder_request_status(token,target['id'])
    if status=='pending':
        st.caption('申请已发送，正在等待对方确认。')
    elif status in ('declined','revoked'):
        st.caption('上次申请未获同意或权限已撤回，可以与对方确认后再次申请。')
    if st.button('申请代设提醒',disabled=status=='pending',key='request_reminder_'+target['id']):
        try:tools.request_reminder_access(token,target['id']);st.rerun()
        except (ValueError,PermissionError) as exc:st.error(str(exc))
    if st.button('刷新授权状态',key='refresh_reminder_'+target['id']):st.rerun()
