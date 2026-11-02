from datetime import datetime
import streamlit as st
from agents.family import identity_profile,my_families,now
from agents.telemetry import personal_events
from ui import llm_config,index_info
from agent_ui import agent_overview
from public_policy import public_mode

profile=identity_profile(st.session_state.personal_token)
families=my_families(st.session_state.personal_token)
cfg=llm_config(); index=index_info()
head,date=st.columns([4,1],vertical_alignment='center')
with head:
    st.caption('个人空间 / 工作台')
    st.title('你好，'+profile['display'])
with date:
    st.caption(now().strftime('%Y.%m.%d'))
    st.badge('在线模型已配置' if cfg.api_key else '本地资料模式',color='green')

with st.container(border=True):
    message,art=st.columns([1.35,1],gap='large',vertical_alignment='center')
    with message:
        st.caption('YOUR HEALTH, CONNECTED')
        st.subheader('让每一次关怀，都更有方向。')
        st.write('整理一次问诊，读懂一份资料，或为家人安排一份准时的关心。\n\n从你此刻需要的事情开始。')
        with st.container(horizontal=True):
            if st.button('开始问诊',type='primary',icon=':material/arrow_forward:'): st.switch_page('app_pages/agent_consultation.py')
            if st.button('进入我的家庭',icon=':material/family_restroom:'): st.switch_page('app_pages/family_home.py')
    with art: st.image('assets/wellness-orbit.svg',width='stretch',alt='连接医疗资料、沟通与家庭关怀的健康轨道')

cols=st.columns(4)
cols[0].metric('知识库资料',f"{index['records']:,}" if index else '—',border=True)
cols[1].metric('已关联家庭',len(families),border=True)
cols[2].metric('本次问诊',len(st.session_state.turns),border=True)
cols[3].metric('协作助手',5,border=True,help='问诊、检索、用药、风险评估和资料解读；家庭协作在独立家庭组中。')
agent_overview()
recent,guide=st.columns([1.2,1],gap='medium')
with recent:
    with st.container(border=True,height='stretch'):
        st.subheader('最近活动',icon=':material/history:')
        rows=personal_events(st.session_state.personal_token)
        labels={'family':'家庭协作','independent':'单项助手操作','knowledge':'医疗资料查询','local':'本地问诊','llm':'在线问诊'}
        if rows:
            for row in rows:
                stamp=datetime.fromisoformat(row['time']).astimezone().strftime('%m.%d %H:%M')
                st.write(labels.get(row.get('mode'),'服务操作')+'　·　'+stamp)
        else: st.caption('你的使用记录会显示在这里。从一次问诊或家庭关怀开始。')
        if not public_mode() and profile.get('role')=='admin': st.page_link('app_pages/monitor.py',label='查看运行记录',icon=':material/arrow_forward:')
with guide:
    with st.container(border=True,height='stretch'):
        st.subheader('一次更清楚的问诊',icon=':material/clinical_notes:')
        for text in ['描述不舒服的地方和持续时间','补充过敏史与当前用药情况','核对原文依据，并按提示继续补充']:
            st.write(':material/check: '+text)
        st.caption('教学原型，不能替代医疗评估。紧急情况请直接联系医疗机构。')
