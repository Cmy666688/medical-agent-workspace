import streamlit as st

from agents import conversations as store
from agents.consultation_card import context_from_card
from consultation_run_ui import submit_consultation
from conversation_ui import restore_context
from coordinator_ui import render_workflow
from execution_timeline import render_timeline
from ui import llm_config

st.caption('工作台 / 多智能体协作')
st.title('多智能体协调器', icon=':material/account_tree:')
st.write('统一调度问诊、风险检查、资料检索与用药核对，查看整轮协作的执行过程。')
st.badge('在线模型已配置' if llm_config().api_key else '本地资料模式',
         icon=':material/check_circle:', color='green')
with st.container(border=True):
    st.markdown('**信息整理 → 危险信号检查 → 资料检索与用药核对（并行）→ 资料解读与汇总**')
    st.caption('配置模型后可执行问诊增强、来源重排及风险 / 用药复核。危险信号优先提示，参考资料随后继续加载。')

restore_context()
context = store.get_context(st.session_state.personal_token, st.session_state.conversation_id)
with st.expander('个人情况 · 与当前问诊共用', icon=':material/person:'):
    cols = st.columns(3)
    context = dict(
        age=cols[0].number_input('年龄（0 表示未提供）', 0, 120, key='consultation_context_age'),
        allergies=cols[1].text_input('药物过敏史', key='consultation_context_allergies'),
        medications=cols[2].text_input('当前用药', key='consultation_context_medications'))
store.context(st.session_state.personal_token, st.session_state.conversation_id, context)
card = store.load_card(st.session_state.personal_token, st.session_state.conversation_id)
context = context_from_card(card['fields'], context)

with st.form('coordinator_run_' + st.session_state.conversation_id):
    question = st.text_area('本次问诊描述', max_chars=1000, height=130,
                            placeholder='例如：我咳嗽3天了，伴有咽痛，无已知药物过敏，现在没吃药。',
                            key='coordinator_question_' + st.session_state.conversation_id)
    st.caption('提交后会保存到当前对话；切回问诊 Agent 可编辑信息核对卡、继续补充情况。')
    submitted = st.form_submit_button('运行协作流程', icon=':material/play_arrow:',
                                     type='primary', width='stretch')
if st.session_state.get('vision_handoff'):
    st.info('已接收图片观察摘要；提交时会附带这份未经核实的观察信息。')
if submitted:
    submit_consultation(question, context)

notice = st.session_state.pop('consultation_failure_notice', None)
if notice:
    st.error(notice)
if st.session_state.get('consultation_failed_timeline'):
    render_timeline(st.session_state.consultation_failed_timeline)
turns = st.session_state.turns
if turns:
    labels = {turn['request']: f"第 {index + 1} 轮 · {turn.get('card_original', turn['question'])[:30]}"
              for index, turn in enumerate(turns)}
    selected = st.selectbox('查看本对话的协作记录', list(labels), index=len(turns) - 1,
                            format_func=labels.get,
                            key='coordinator_turn_' + st.session_state.conversation_id)
    render_workflow(next(turn for turn in turns if turn['request'] == selected))
else:
    st.info('提交一段描述后，这里会展示协作总览、执行时间轴及各 Agent 的结果。')
st.page_link('app_pages/agent_consultation.py', label='前往问诊 Agent · 核对信息与继续对话',
             icon=':material/clinical_notes:')
st.caption('教学原型 · 不提供诊断、临床风险评分或处方。')
