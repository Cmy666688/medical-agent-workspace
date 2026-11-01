"""Chinese presentation and readable exports for genuine RAG evaluation results."""
import csv
import io
import json
from datetime import datetime,timedelta,timezone
import streamlit as st
from result_ui import debug_output,friendly_error

STATUS={'evaluated':'已完成评审','skipped_no_key':'未配置密钥，已跳过','failed':'模型调用失败'}

def percent(value):
    return f'{value:.1%}' if isinstance(value,(float,int)) else '未评估'

def details(report):
    result=[]
    for index,row in enumerate(report.get('rows',[]),1):
        judgment=row.get('judgment') or {}
        rank=row.get('rank')
        result.append({'序号':index,'评估问题':row.get('query',''),'目标资料排名':f'第 {rank} 名' if rank is not None else '前 10 条未命中',
                       '生成评估':STATUS.get(row.get('generation_status'),'未评估'),
                       '忠实性':'通过' if judgment.get('faithful') is True else '存在未支持结论' if judgment.get('faithful') is False else '未评估',
                       '切题度':percent(judgment.get('relevance')),'参考一致性':percent(judgment.get('reference_alignment'))})
    return result

def report_markdown(report):
    count=report.get('sample_count',0); recall=report.get('recall',{})
    evaluated=report.get('generation_evaluated',0); failed=report.get('generation_failed',0)
    lines=['# 检索与生成评估报告','',f'评估问句：{count} 条',
           *[f'- 前 {k} 条命中率：{percent(recall.get("Recall@"+str(k)))}' for k in (1,5,10)],
           f'- 完成生成评审：{evaluated} 条；调用失败：{failed} 条；跳过或未评估：{max(0,count-evaluated-failed)} 条。','',
           '命中率指目标资料出现在前若干条检索结果中的样本比例，不代表诊断准确率。']
    metrics=report.get('generation_metrics')
    if metrics:
        lines+=['',f'忠实性通过率：{percent(metrics.get("faithful"))}',f'平均切题度：{percent(metrics.get("relevance"))}',f'平均参考一致性：{percent(metrics.get("reference_alignment"))}']
    else: lines+=['','本次没有可用的生成质量分数。未配置密钥的问句仅评估检索，不进行生成和质量评审。']
    lines+=['','分数仅覆盖评审成功的样本，由同一模型配置评审，存在自评偏差，不代表临床准确率或独立人工验收。']
    for item in details(report):
        lines+=['',f'## 第 {item["序号"]} 题',item['评估问题'],f'目标资料排名：{item["目标资料排名"]}',f'生成评估：{item["生成评估"]}',f'忠实性：{item["忠实性"]}；切题度：{item["切题度"]}；参考一致性：{item["参考一致性"]}']
    for index,row in enumerate(report.get('rows',[]),1):
        if row.get('error'): lines+=['',f'第 {index} 题失败说明：'+friendly_error(row['error'])]
        for claim in (row.get('judgment') or {}).get('unsupported_claims',[]): lines.append(f'第 {index} 题需核对的表述：{claim}')
    return '\n'.join(lines)+'\n'

def render_quality_report(report):
    count=report.get('sample_count',0); recall=report.get('recall',{})
    evaluated=report.get('generation_evaluated',0); failed=report.get('generation_failed',0)
    rows=report.get('rows',[]); skipped=sum(row.get('generation_status')=='skipped_no_key' for row in rows)
    st.subheader('本次评估结果',icon=':material/analytics:')
    stamp=report.get('created_at')
    if stamp:
        try: st.caption('完成时间：'+datetime.fromisoformat(stamp).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')+'（北京时间）')
        except (ValueError,TypeError): pass
    cols=st.columns(4)
    cols[0].metric('评估问句',f'{count} 条',border=True)
    for col,k in zip(cols[1:],(1,5,10)):
        col.metric(f'前 {k} 条命中率',percent(recall.get('Recall@'+str(k))),border=True)
    st.caption('命中率：目标资料出现在前若干条检索结果中的问句比例。仅反映本次固定样本的检索表现，不代表诊断准确率。')
    if count and evaluated==count:
        st.success(f'{count} 条问句已完成检索、生成与质量评审。')
    elif not evaluated:
        reason=f'{skipped} 条问句因未配置模型 API 密钥跳过生成和质量评审。' if skipped else '没有问句成功完成生成质量评审。'
        st.warning('本次仅有检索评估结果。'+reason+' 生成质量分数暂不可用。')
    else:
        st.info(f'已完成检索评估；生成质量评审完成 {evaluated}/{count} 条，失败 {failed} 条，其余跳过或未评估。')
    if skipped: st.caption('要评估生成质量，请在上方切换到“模型接口”，配置接口地址、模型名称与 API 密钥，再重新运行评估。')
    if count and count<24: st.caption(f'本次仅使用 {count} 条留出问句，样本较少；可选择 24 条进行更完整的固定样本评估。')
    metrics=report.get('generation_metrics')
    if evaluated and metrics:
        st.markdown('**生成质量 · 仅统计评审成功的样本**')
        cols=st.columns(3)
        for col,label,key in zip(cols,['忠实性通过率','平均切题度','平均参考一致性'],['faithful','relevance','reference_alignment']):
            col.metric(label,percent(metrics.get(key)),border=True)
        st.caption(f'分数覆盖 {evaluated}/{count} 条问句。忠实性表示评审判定答案是否有证据支持；切题度、参考一致性采用模型给出的 0～1 分，显示为百分比。')
    st.markdown('**逐题结果**')
    table=details(report)
    st.dataframe(table,hide_index=True,width='stretch',alt='每道评估问题的检索排名与生成质量评审状态')
    for index,row in enumerate(rows,1):
        claims=(row.get('judgment') or {}).get('unsupported_claims',[])
        if row.get('error') or claims:
            with st.expander(f'第 {index} 题 · 需要核对'):
                st.text(row.get('query',''))
                if row.get('error'): st.warning(friendly_error(row['error']))
                for claim in claims: st.text('需核对的表述：'+claim)
    with st.expander('评估方式与适用范围'):
        st.write('使用固定留出问句，以原始疾病简介为参考文本。生成质量由同一模型配置评审，分数仅覆盖评审成功的样本，存在自评偏差；不代表临床准确率或独立人工验收。')
    with st.container(horizontal=True):
        st.download_button('下载中文评估报告',report_markdown(report),file_name='检索与生成评估报告.md',mime='text/markdown',icon=':material/download:')
        if table:
            buffer=io.StringIO(); writer=csv.DictWriter(buffer,fieldnames=list(table[0])); writer.writeheader(); writer.writerows(table)
            st.download_button('下载逐题明细',buffer.getvalue().encode('utf-8-sig'),file_name='评估逐题明细.csv',mime='text/csv')
    debug_output(report)
    if st.session_state.get('developer_mode'):
        st.download_button('下载原始 JSON',json.dumps(report,ensure_ascii=False,indent=2),file_name='rag_quality.json',mime='application/json')
