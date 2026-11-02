import json
import streamlit as st
from agents.telemetry import record
from execution_timeline import render_timeline
from ui import llm_config, evidence_cards
from consultation_run_ui import submit_consultation

st.caption('健康助手 / 问诊')
heading, mode=st.columns([3,1])
heading.title('问诊 Agent',icon=':material/clinical_notes:')
heading.write('把你的情况说清楚。其余的整理、检索与核对，交给协作助手。')
with mode:
    st.badge('在线模型已配置' if llm_config().api_key else '本地资料模式',icon=':material/check_circle:',color='green')
    st.caption('对话自动保存到当前账号的历史记录')
from result_ui import render_output,debug_output,friendly_error
from vision_ui import vision_panel
vision_panel("consultation")
from conversation_ui import restore_context,conversation_header
conversation_header()
restore_context()
with st.expander('个人情况 · 补充后可减少重复追问',icon=':material/person:'):
    cols=st.columns(3)
    age=cols[0].number_input('年龄（0 表示未提供）',0,120,key='consultation_context_age')
    allergies=cols[1].text_input('药物过敏史',placeholder='例如：无已知过敏 / 不清楚',key='consultation_context_allergies')
    medications=cols[2].text_input('当前用药',placeholder='例如：未用药 / 药物名称',key='consultation_context_medications')
from agents import conversations as conversation_store
conversation_context=dict(age=age,allergies=allergies,medications=medications)
conversation_store.context(st.session_state.personal_token,st.session_state.conversation_id,conversation_context)
from consultation_card_ui import card_panel
from agents.consultation_card import context_from_card
checked_card=card_panel()
conversation_context=context_from_card(checked_card['fields'],conversation_context)
failure_notice=st.session_state.pop('consultation_failure_notice',None)
if failure_notice: st.error(failure_notice)
if st.session_state.get('consultation_failed_timeline'):
    render_timeline(st.session_state.consultation_failed_timeline)
for turn in st.session_state.turns:
    with st.chat_message('user'): st.write(turn['question'])
    with st.chat_message('assistant'):
        st.markdown(turn['answer'])
        if turn['conflicts']: st.warning('；'.join(turn['conflicts']))
        if turn.get('trace'):
            if turn is st.session_state.turns[-1]: render_timeline(turn['trace'])
            else:
                with st.expander('查看本轮执行时间轴',icon=':material/timeline:'):
                    render_timeline(turn['trace'])
        with st.expander(f"协作记录 · {len(turn['trace'])} 个步骤 · {len(turn['evidences'])} 条证据",icon=':material/account_tree:'):
            for x in turn['trace']:
                st.markdown(f"**{x['agent']}**　{x['status']}　·　{x['duration_ms']:.0f} ms")
                if x['error']: st.caption(friendly_error(x['error']))
                with st.expander('查看 '+x['agent']+' 的结果'): render_output(x['agent'],x['output'])
            debug_output(turn)
            evidence_cards(turn['evidences'])
        rating=st.feedback('thumbs',key='feedback_'+turn['request'])
        if st.session_state.get('saved_'+turn['request'])!=rating:
            record(st.session_state.session_id,turn['request'],'feedback',positive=(rating==1) if rating is not None else None)
            st.session_state['saved_'+turn['request']]=rating
        st.download_button('导出本次结果',json.dumps(turn,ensure_ascii=False,indent=2),file_name='consultation.json',key='export_'+turn['request'])
if not st.session_state.turns:
    st.space('small')
    st.subheader('今天，想了解哪些健康问题？')
    for col,(icon,title,text) in zip(st.columns(3),[('pulmonology','描述不舒服的地方','例如：我咳嗽三天了，还伴有发热，想了解相关资料。'),('menu_book','查一种疾病','例如：想查过敏性鼻炎的症状和疾病介绍。'),('chat','继续补充情况','对话中可以补充持续时间、过敏史和当前用药。')]):
        with col.container(border=True,height='stretch'):
            st.markdown(f":material/{icon}: **{title}**")
            st.caption(text)
    with st.expander('了解问诊协作流程',icon=':material/account_tree:'):
        st.markdown('**信息整理　→　危险信号检查　→　资料检索与用药信息核对　→　证据汇总**')
        st.caption('危险信号优先处理。没有足够证据时，系统会提示补充信息。')
st.caption('教学原型 · 不提供诊断或处方。风险检查基于演示规则，无法代替医疗评估。')
handoff=st.session_state.get('vision_handoff')
if handoff: st.info('已接收图片观察摘要；下一条问诊将附带这份未经核实的观察信息。')
question=st.chat_input('描述症状、持续时间或想查阅的疾病资料',max_chars=1000)
if question:
    submit_consultation(question, conversation_context)
