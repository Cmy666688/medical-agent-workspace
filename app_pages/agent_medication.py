import asyncio
import streamlit as st
from agents.coordinator import MedicationAgent
from agent_ui import agent_header,save_test,test_result
from agents.medication_knowledge import DrugKnowledge
from conversation_ui import restore_context

agent_header('medication')
info=DrugKnowledge().info()
if info['ready']:
    cols=st.columns(3)
    cols[0].metric('TFDA 许可证',f"{info['counts']['products']:,}")
    cols[1].metric('openFDA 标签样本',info['counts']['labels'])
    cols[2].metric('DDInter 子集记录',f"{info['counts']['ddi']:,}")
    st.caption('按药名或许可证核对来源资料；支持简体、繁体及英文。当前覆盖有限，不能替代医生或药师的完整用药审查。')
else: st.info('药品资料尚未加载，请联系服务管理者。你仍可填写并记录用药背景。')
from vision_ui import vision_panel
vision_panel('medication')
restore_context()
with st.form('medication_test'):
    allergy=st.text_input('药物过敏史',value=st.session_state.get('consultation_context_allergies',''),placeholder='未提供时会提示补充',max_chars=300)
    medication=st.text_area('当前用药',value=st.session_state.get('consultation_context_medications',''),placeholder='每行一种药名，最多 8 种；也可输入准确许可证号。未用药请填“未用药”。',max_chars=1000)
    st.caption('先只填写准确药名，不附带剂量或服药时间。复方药请使用完整商品名/许可证号，确认实际成分。')
    submitted=st.form_submit_button('运行用药 Agent',type='primary')
if submitted:
    with st.spinner('正在核对药名、标签来源和相互作用记录…'):
        result=asyncio.run(MedicationAgent().run(dict(context=dict(allergies=allergy,medications=medication))))
    save_test('medication',vars(result))
    st.rerun()
test_result('medication')
