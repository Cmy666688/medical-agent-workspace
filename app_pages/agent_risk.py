import asyncio
import streamlit as st
from agents.risk_workflow import assess
from agent_ui import agent_header,save_test,test_result,latest
from ui import llm_config,retrieval
from result_ui import render_output

agent_header('risk',show_recent=False)
st.caption('规则未命中表示无法据此判断风险，不代表安全或低风险。')
turns=st.session_state.get('turns',[])
recent=latest('风险评估 Agent')
if recent:
    with st.expander('最近问诊的风险评估与相关资料',expanded=True,icon=':material/history:'):
        st.caption('来自当前对话的最近一次问诊；切换历史对话可查看该对话的记录。')
        linked=dict(recent.get('output',{}))
        linked.setdefault('evidences',turns[-1].get('evidences',[]))
        if linked: render_output('风险评估 Agent',linked)
        else: st.caption('该历史记录没有保存详细风险信息，请重新提交问诊。')
        if any(row['agent']=='检索 Agent' and row['status']=='跳过' for row in turns[-1]['trace']):
            st.info('这条历史问诊采用旧流程，当时跳过了资料检索。可在下方重新检查，或重新提交问诊以生成相关资料。')
st.subheader('单独检查症状')
from conversation_ui import restore_context
restore_context()
default_question=(recent.get('output',{}).get('input_snapshot') or turns[-1].get('question','')) if recent else '鼻子痒，没有胸痛，无呼吸困难'
with st.form('risk_test'):
    question=st.text_area('症状描述',value=default_question[:1000],max_chars=1000)
    include_references=st.checkbox('同时检索相关资料并核对用药信息',value=True,key='risk_include_references')
    with st.expander('用药背景（可选）'):
        medications=st.text_input('当前用药',value=st.session_state.get('consultation_context_medications',''),key='risk_medications')
        allergies=st.text_input('药物过敏史',value=st.session_state.get('consultation_context_allergies',''),key='risk_allergies')
    submitted=st.form_submit_button('运行风险评估 Agent',type='primary')
if submitted:
    if not question.strip(): st.warning('请填写症状描述。')
    else:
        alert=st.empty()
        def show_risk(event):
            if event.get('output',{}).get('red_flags'):
                alert.warning(event['output']['recommendation']+' 相关资料继续加载，请勿等待结果再就医。')
        context=dict(allergies=allergies,medications=medications)
        with st.spinner('正在检查危险信号、整理信息'+('并检索相关资料…' if include_references else '…')):
            result=asyncio.run(assess(question,llm_config(),st.session_state.session_id,retrieval=retrieval if include_references else None,context=context,on_event=show_risk))
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
