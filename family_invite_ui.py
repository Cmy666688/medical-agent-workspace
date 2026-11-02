"""Only display the current household's latest, still-valid invitation."""
import streamlit as st
from agents import family
from agents.household_agents import tools


def remember_invite(token,invitation):
    if not invitation:return
    person=family.profile(token)
    value=dict(group_id=person['group_id'],invite=invitation)
    st.session_state.setdefault('family_invites',{})[person['group_id']]=value
    st.session_state.new_family_credentials=value


def invitation_panel(token):
    try:person=family.profile(token)
    except PermissionError:return
    if person['role']!='owner':return
    cached=st.session_state.get('family_invites',{}).get(person['group_id']) or st.session_state.get('new_family_credentials',{})
    candidate=cached.get('invite')
    info=family.invitation_info(token,candidate)
    with st.expander('邀请家人 · '+person['family'],expanded=bool(candidate and info['matches'])):
        st.caption('邀请码有效 7 天。刷新会使旧码失效，请分享最新的完整邀请码。')
        if candidate and info['matches'] and not info['expired']:
            st.code(candidate,language=None)
            st.caption('有效期至 '+info['expires'][:19].replace('T',' ')+'（北京时间）')
        else:
            st.caption('邀请码仅在生成时显示。请点击下方按钮获取当前家庭的新邀请码。')
        if st.button('刷新家庭邀请码',key='refresh_invite_'+person['group_id']):
            remember_invite(token,tools.rotate_invite(token));st.rerun()
