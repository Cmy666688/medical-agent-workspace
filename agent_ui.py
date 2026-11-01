"""Agent 的公开说明与会话执行状态；不生成模拟执行结果。"""
import streamlit as st
import uuid
from agents.telemetry import record

from agent_catalog import AGENTS
from result_ui import render_output,debug_output,friendly_error


def latest(name):
    turns=st.session_state.get('turns',[])
    if not turns: return None
    return next((x for x in reversed(turns[-1]['trace']) if x['agent']==name),None)

def agent_overview():
    st.subheader('选择你的健康助手')
    values=[meta for key,meta in AGENTS.items() if key not in ('family','care','schedule','vision')]
    for i,meta in enumerate(values):
        if i%3==0: cols=st.columns(3)
        col=cols[i%3]
        item=latest(meta['name'])
        with col.container(border=True,height='stretch'):
            st.subheader(meta['name'],icon=f":material/{meta['icon']}:")
            status=item['status'] if item else '待调用'
            st.badge(status,color={'完成':'green','失败':'red','跳过':'orange'}.get(status,'gray'))
            st.caption(meta['role'])
            if item: st.caption(f"最近一轮 · {item['duration_ms']:.0f} ms")
            st.space('stretch')
            st.page_link('app_pages/'+meta['page']+'.py',label='打开功能',icon=':material/arrow_forward:',width='stretch')
    st.caption('问诊协作状态来自当前会话；家庭任务与共享权限在对应页面查看。')

def agent_header(key,show_recent=True):
    meta=AGENTS.get(key)
    if meta is None:
        st.error("Agent 配置未加载，请刷新页面或重启服务。")
        st.stop()
    st.caption('健康助手 / '+meta['name'])
    item=latest(meta['name'])
    if not show_recent: item=st.session_state.get('agent_tests',{}).get(key)
    title,status=st.columns([4,1],vertical_alignment='center')
    title.title(meta['name'],icon=f":material/{meta['icon']}:")
    partial=bool(item and item.get('output',{}).get('online_status')=='failed')
    with status: st.badge('本地完成' if partial else (item['status'] if item else '准备就绪'),color='orange' if partial else ('green' if not item or item['status']=='完成' else 'gray'))
    st.write(meta['role'])
    with st.expander('功能说明与使用范围',icon=':material/info:'):
        st.markdown('**你需要提供**　'+meta['input'])
        st.markdown('**你会得到**　'+meta['output'])
        st.caption(meta['scope'])
    if show_recent:
        with st.expander('最近一次协作结果',expanded=False,icon=':material/history:'):
            if item:
                st.write(f"状态：{item['status']} · 耗时：{item['duration_ms']:.0f} ms")
                if item['error']: st.warning(friendly_error(item['error']))
                render_output(meta['name'],item['output'])
                debug_output(item)
            else: st.caption('当前会话还没有此 Agent 的调用结果。可以使用下面的功能，或前往问诊 Agent 发起完整问诊。')
    st.page_link('app_pages/agent_consultation.py',label='需要完整问诊？前往问诊 Agent',icon=':material/arrow_forward:')

def save_test(key, result):
    st.session_state.setdefault('agent_tests',{})[key]=result
    request=uuid.uuid4().hex[:12]
    name=AGENTS[key]['name']
    duration=result.get('duration_ms',result.get('latency_ms',0))
    record(st.session_state.session_id,request,'agent',agent=name,status=result.get('status','完成'),latency_ms=duration,error=result.get('error',''),origin='independent')
    record(st.session_state.session_id,request,'request',latency_ms=duration,mode='independent')
    if key=='retrieval' and result.get('status')!='失败':
        record(st.session_state.session_id,request,'retrieval',latency_ms=duration,no_hit=not result.get('evidences'),cache_hit=result.get('cache_hit',False),status=result.get('status','完成'))

def test_result(key):
    value=st.session_state.get('agent_tests',{}).get(key)
    if value is not None:
        st.subheader('处理结果')
        if value.get('status')=='失败': st.warning(friendly_error(value.get('error')))
        else: render_output(AGENTS[key]['name'],value.get('output',value))
        debug_output(value)
