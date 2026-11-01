import asyncio
import streamlit as st
from agents.coordinator import RiskAgent
from agent_ui import agent_header,save_test,test_result

agent_header('risk')
st.caption('规则未命中表示无法据此判断风险，不代表安全或低风险。')
with st.form('risk_test'):
    question=st.text_area('症状描述',value='鼻子痒，没有胸痛，无呼吸困难',max_chars=1000)
    submitted=st.form_submit_button('运行风险评估 Agent',type='primary')
if submitted:
    if not question.strip(): st.warning('请填写症状描述。')
    else:
        result=asyncio.run(RiskAgent().run(dict(query=question)))
        save_test('risk',vars(result))
value=st.session_state.get('agent_tests',{}).get('risk')
if value and value.get('output',{}).get('red_flags'):
    st.warning(value['output']['recommendation'])
test_result('risk')
