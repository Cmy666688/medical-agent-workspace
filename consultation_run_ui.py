"""One submission path shared by the conversation and coordinator views."""
import asyncio
import uuid

import streamlit as st

from agents import conversations as store
from agents.consultation_card import context_from_card
from agents.coordinator import Coordinator
from execution_timeline import TimelineState, render_timeline
import ui


def submit_consultation(question, context):
    if not question.strip():
        st.warning('请填写问诊描述。')
        return
    active_conversation = st.session_state.conversation_id
    active_token = st.session_state.personal_token
    active_session = st.session_state.session_id
    st.session_state.pop('consultation_failed_timeline', None)
    timeline = TimelineState()
    request_id = uuid.uuid4().hex[:12]
    original_question = question
    # Authorization and the original source receipt precede any external request.
    card = store.ingest_card(active_token, active_conversation, request_id, question)
    context = context_from_card(card['fields'], context)
    if st.session_state.get('vision_handoff'):
        question += '\n' + st.session_state.pop('vision_handoff')
    try:
        risk_notice = st.empty()
        with st.status('正在整理问诊信息、检查危险信号并检索资料…', expanded=True, type='compact') as status:
            progress = st.empty()

            def show_progress(event):
                if event.get('output', {}).get('red_flags'):
                    risk_notice.warning(event['output']['recommendation'] + ' 相关资料将继续加载，请勿等待结果再就医。')
                timeline.update(event)
                with progress.container():
                    render_timeline(timeline.rows(), live=True)

            result = asyncio.run(Coordinator(ui.retrieval).run(
                question, context, st.session_state.history, active_session,
                ui.llm_config(), on_event=show_progress, request_id=request_id))
            failed = any(item['status'] == '失败' for item in result['trace'])
            status.update(label='协作结束，部分步骤未完成' if failed else '协作完成',
                          state='error' if failed else 'complete')
        turn = dict(question=question, card_original=original_question, **result)
        store.append(active_token, active_conversation, turn, context)
        if st.session_state.conversation_id == active_conversation:
            st.session_state.turns.append(turn)
            st.session_state.persisted_requests.add(turn['request'])
            st.session_state['coordinator_turn_' + active_conversation] = turn['request']
    except Exception as exc:
        timeline.fail_unfinished()
        st.session_state.consultation_failed_timeline = timeline.rows()
        st.session_state.consultation_failure_notice = '本次协作未完成：' + str(exc) + '。已保留核对卡中的本次信息。'
    st.rerun()
