"""Replay the actual saved workflow; navigation never executes an Agent."""
import streamlit as st

from execution_timeline import duration_label, render_timeline
from result_ui import friendly_error, render_output
from ui import evidence_cards


def workflow_overview(turn):
    trace = turn.get('trace', [])
    risk = next((item.get('output', {}) for item in trace
                 if item.get('agent') == '风险评估 Agent'), {})
    return dict(
        duration=duration_label(turn.get('duration_ms')),
        completed=sum(item.get('status') == '完成' for item in trace),
        total=len(trace),
        failed=sum(item.get('status') == '失败' for item in trace),
        risk='有危险信号' if risk.get('red_flags') else '尚不能确定' if risk else '未获得结果',
        alerts=len(turn.get('conflicts', [])),
    )


def render_workflow(turn):
    info = workflow_overview(turn)
    st.subheader('本次协作总览', icon=':material/account_tree:')
    st.caption('请求编号：' + turn['request'])
    with st.container(horizontal=True):
        st.metric('整轮耗时', info['duration'], border=True)
        st.metric('完成步骤', f"{info['completed']} / {info['total']}", border=True)
        st.metric('危险信号检查', info['risk'], border=True)
        st.metric('协调提醒', str(info['alerts']) + ' 条', border=True)
    if info['failed']:
        st.warning(f"有 {info['failed']} 个步骤未完成，下方保留已得到的结果。")
    for notice in turn.get('conflicts', []):
        st.warning(notice)
    with st.expander('本轮输入', expanded=False):
        st.text(turn['question'])
    render_timeline(turn.get('trace', []))
    st.subheader('协作汇总', icon=':material/summarize:')
    st.markdown(turn['answer'])
    st.subheader('各 Agent 输出详情', icon=':material/view_list:')
    for index, item in enumerate(turn.get('trace', [])):
        with st.expander(f"{index + 1}. {item['agent']} · {item['status']} · {duration_label(item.get('duration_ms'))}"):
            if item.get('error'):
                st.warning(friendly_error(item['error']))
            if item.get('output'):
                render_output(item['agent'], item['output'])
    if turn.get('evidences'):
        with st.expander(f"参考资料与来源 · {len(turn['evidences'])} 条"):
            evidence_cards(turn['evidences'])
