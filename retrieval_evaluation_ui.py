"""Honest aggregate and per-query before/after retrieval comparisons."""
import json
import streamlit as st


def render_retrieval_comparison(data,audit=None):
    st.caption('固定留出问句的向量检索对比。Recall 越高越好，目标排名越小越好。当前线上混合检索与可选重排属于另一条流水线。')
    st.dataframe([dict(阶段=label,**data[key]) for label,key in [('微调前','before'),('微调后','after')]],hide_index=True)
    for col,key in zip(st.columns(3),('Recall@1','Recall@5','Recall@10')):
        old=data['before'][key];new=data['after'][key]
        col.metric(key,f'{new:.1%}',delta=f'{(new-old)*100:+.2f} 个百分点',border=True)
    a=data['selected_before'];b=data['selected_after']
    st.write('保留的原始示例：'+b['query'])
    cols=st.columns(2)
    cols[0].metric('微调前目标排名',a['rank'],help='排名越小越好；不是风险评分。')
    delta=b['rank']-a['rank']
    cols[1].metric('微调后目标排名',b['rank'],delta=delta,delta_color='inverse',help='正数表示目标位置后移，即此例退步。')
    if delta>0:st.warning(f"这个示例从第 {a['rank']} 名降到第 {b['rank']} 名，退步 {delta} 位。整体召回率提升，并不保证每条问题都提升；这里保留该退步案例。")
    elif delta<0:st.success(f'此示例目标排名提升 {-delta} 位。')
    else:st.info('此示例目标排名没有变化。')
    st.caption('相近疾病的语义容易混淆，少量训练样本和负样本构造可能影响单例；当前结果不足以单独证明具体原因。不同模型的相似度分数也不能直接当作概率比较。')
    for col,key,label in zip(cols,['selected_before','selected_after'],['微调前 Top 10','微调后 Top 10']):
        with col:
            st.markdown('**'+label+'**')
            st.dataframe(data[key]['top10'],hide_index=True)
    if audit:
        st.subheader('全部留出问题逐题核对')
        changes=[row['after_rank']-row['before_rank'] for row in audit['rows']]
        st.caption(f"{len(changes)} 条问题：提升 {sum(x<0 for x in changes)} 条 · 退步 {sum(x>0 for x in changes)} 条 · 持平 {sum(x==0 for x in changes)} 条")
        if not audit.get('matches_saved_metrics',False):st.warning('本次重算与原保存指标不完全一致，请按本次方法单独比较；未覆盖原结果。')
        chosen=st.selectbox('逐题查看范围',['全部','退步','提升','持平'])
        rows=[]
        for row in audit['rows']:
            diff=row['after_rank']-row['before_rank']
            status='退步' if diff>0 else '提升' if diff<0 else '持平'
            if chosen=='全部' or chosen==status:
                rows.append(dict(问题=row['query'],目标资料=row['target_name'],微调前排名=row['before_rank'],微调后排名=row['after_rank'],变化=status,名次变化=diff))
        st.dataframe(rows,hide_index=True)
        st.download_button('下载逐题核对结果',json.dumps(audit,ensure_ascii=False,indent=2),file_name='retrieval_comparison.json',mime='application/json')
