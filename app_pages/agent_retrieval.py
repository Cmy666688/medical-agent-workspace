import streamlit as st
from agent_ui import agent_header, save_test, test_result
from ui import retrieval,evidence_cards

agent_header('retrieval')
with st.form('retrieval_test'):
    question=st.text_input('检索问题',value='想查过敏性鼻炎的症状与疾病介绍',max_chars=1000)
    k=st.slider('返回条数',1,10,5)
    submitted=st.form_submit_button('运行检索 Agent',type='primary')
if submitted:
    if not question.strip(): st.warning('请填写检索问题。')
    else:
        try:
            with st.spinner('正在执行真实向量检索…'): result=retrieval().search(question,k)
            save_test('retrieval',dict(status='完成',**result))
        except Exception as exc: save_test('retrieval',dict(status='失败',error=str(exc)))
value=st.session_state.get('agent_tests',{}).get('retrieval')
if value and value.get('status')=='完成':
    st.caption(f"检索耗时 {value['latency_ms']:.1f} ms · 缓存{'命中' if value['cache_hit'] else '未命中'}")
    if not value['evidences']: st.info('未找到达到阈值的资料。')
    evidence_cards(value['evidences'])
test_result('retrieval')
