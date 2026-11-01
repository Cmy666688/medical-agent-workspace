import streamlit as st
from datetime import datetime
from ui import retrieval, evidence_cards,index_info
import uuid
from agents.telemetry import record

st.caption('KNOWLEDGE / RETRIEVAL')
st.title('医疗知识库')
st.write('从 8,808 条疾病记录中寻找相关资料，查看原文与记录 ID。')
try:
    info=index_info()
    if info:
        cols=st.columns(3)
        cols[0].metric('疾病记录',f"{info['records']:,}")
        cols[1].metric('向量维度',info['dimension'])
        cols[2].metric('索引集合',info['collection'])
        st.caption('索引更新时间：'+(datetime.fromisoformat(info['indexed_at']).astimezone().strftime('%Y-%m-%d %H:%M') if info['indexed_at'] else '历史索引未记录'))
    else: st.caption('当前索引未发布元数据，实际检索时检查知识库。')
    with st.form('search'):
        q=st.text_input('问题或疾病名称',placeholder='例如：右上腹不适，想查胆囊炎资料')
        k=st.slider('返回条数',1,10,5)
        threshold=st.slider('最低相关性',0.0,1.0,0.35,0.05)
        submit=st.form_submit_button('检索资料',type='primary')
    if submit and q.strip():
        with st.spinner('正在查询，首次检索需加载本地模型…'): value=retrieval().search(q,k,threshold)
        request=uuid.uuid4().hex[:12]
        record(st.session_state.session_id,request,'retrieval',latency_ms=value['latency_ms'],no_hit=not value['evidences'],cache_hit=value['cache_hit'],origin='knowledge')
        record(st.session_state.session_id,request,'agent',agent='检索 Agent',status='完成',latency_ms=value['latency_ms'],origin='knowledge')
        record(st.session_state.session_id,request,'request',latency_ms=value['latency_ms'],mode='knowledge')
        st.caption(f"耗时 {value['latency_ms']:.1f} ms · 缓存{'命中' if value['cache_hit'] else '未命中'} · 相似度不代表患病概率")
        if not value['evidences']: st.info('没有达到当前相关性阈值的结果。')
        evidence_cards(value['evidences'])
except Exception as exc: st.error('知识库未就绪：'+str(exc))
from document_ui import document_panel
document_panel()
