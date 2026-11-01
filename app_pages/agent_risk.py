import asyncio
import streamlit as st
from agents.risk_workflow import assess
from agent_ui import agent_header,save_test,test_result
from ui import llm_config

agent_header('risk',show_recent=False)
st.caption('规则未命中表示无法据此判断风险，不代表安全或低风险。')
with st.form('risk_test'):
    question=st.text_area('症状描述',value='鼻子痒，没有胸痛，无呼吸困难',max_chars=1000)
    submitted=st.form_submit_button('运行风险评估 Agent',type='primary')
if submitted:
    if not question.strip(): st.warning('请填写症状描述。')
    else:
        with st.spinner('正在检查危险信号并整理本次信息…'):
            result=asyncio.run(assess(question,llm_config(),st.session_state.session_id))
        save_test('risk',vars(result))
        st.rerun()
value=st.session_state.get('agent_tests',{}).get('risk')
if value:
    if value.get('output',{}).get('online_status')=='failed': st.warning('本地检查已完成；在线复核失败，具体原因见结果。')
    elif value.get('output',{}).get('online_status')=='completed': st.success('本地检查和在线复核均已完成，结果如下。')
    elif value['status']=='完成': st.success('本地检查已完成，结果如下。')
    else: st.error('本次检查未完成，请查看提示。')
    st.caption('下面显示上次提交的结果。修改描述后，请再次点击运行。')
test_result('risk')
