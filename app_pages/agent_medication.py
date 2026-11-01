import asyncio
import streamlit as st
from agents.coordinator import MedicationAgent
from agent_ui import agent_header,save_test,test_result

agent_header('medication')
from vision_ui import vision_panel
vision_panel('medication')
with st.form('medication_test'):
    allergy=st.text_input('药物过敏史',placeholder='未提供时会提示补充')
    medication=st.text_input('当前用药',placeholder='例如：未用药 / 具体药物名称')
    submitted=st.form_submit_button('运行用药 Agent',type='primary')
if submitted:
    result=asyncio.run(MedicationAgent().run(dict(context=dict(allergies=allergy,medications=medication))))
    save_test('medication',vars(result))
test_result('medication')
