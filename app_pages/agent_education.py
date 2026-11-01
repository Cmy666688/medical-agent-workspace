import asyncio
import hashlib
import streamlit as st
from agents.coordinator import EducationAgent
from agent_ui import agent_header,save_test,test_result

agent_header('education')
workspace,guide=st.columns([1.8,1],gap='medium')
with workspace:
    with st.container(border=True):
        st.subheader('读懂你的资料',icon=':material/description:')
        source=st.segmented_control('资料来源',['最近问诊证据','粘贴资料'],default='最近问诊证据',width='stretch')
        turns=st.session_state.get('turns',[])
        evidences=turns[-1].get('evidences',[]) if turns else []
        if source=='粘贴资料':
            name=st.text_input('资料名称',value='我提供的资料')
            text=st.text_area('资料正文',max_chars=10000,height=220,placeholder='粘贴你想整理的医疗资料原文…')
            evidences=[dict(name=name,content=text,doc_id='user_'+hashlib.sha256(text.encode()).hexdigest()[:12])] if text.strip() else []
            st.caption('将整理原文摘录与来源；你提供的资料尚未核实。')
        else:
            if evidences:
                st.badge(f'已接收 {len(evidences)} 条问诊证据',icon=':material/check_circle:',color='green')
                for item in evidences: st.write(':material/article: '+item.get('name','问诊资料'))
            else:
                st.space('small')
                st.markdown('**还没有待解读的问诊资料**')
                st.caption('完成一次问诊后，相关原文会出现在这里。也可以切换到“粘贴资料”，直接添加正文。')
                st.space('small')
        if st.button('整理资料与来源',type='primary',disabled=not evidences,width='stretch',icon=':material/auto_stories:'):
            save_test('education',vars(asyncio.run(EducationAgent().run(evidences))))
with guide:
    st.caption('从原文，到清楚的记录')
    for number,title,text in [('01','选择一份资料','使用最近问诊证据，或粘贴你已有的正文。'),('02','整理关键信息','保留原文摘录，减少反复翻找。'),('03','随时核对来源','每条整理结果附带来源记录，方便回查。')]:
        with st.container(border=True):
            st.markdown('**:green['+number+']　'+title+'**')
            st.caption(text)
    st.caption('本地功能整理原文，不新增诊断结论。在线模型解读在完整问诊流程中执行。')
test_result('education')
