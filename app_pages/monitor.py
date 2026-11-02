import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime
from agents.telemetry import events,feedback_stats
from ui import index_info,llm_config
from agents.costs import cost_summary
from agents.llm import quota_usage
from public_policy import require_project_admin

require_project_admin()

st.caption('OBSERVABILITY / AGENTS')
st.title('运行监控')
st.write('显示服务最近 5,000 条运行事件。历史调试记录也可能包含在内，参考费用不代替供应商账单。')
st.caption(f'当前会话累计预留 token：{quota_usage(st.session_state.session_id):,}；预留值为保守上界，不等于供应商实测用量。')
with st.expander('索引规模与更新时间'):
    try:
        index=index_info()
        if index:
            st.write(f"记录 / chunks：{index['records']:,} · 向量：{index['dimension']} 维 · 集合：{index['collection']}")
            st.caption('最近索引时间：'+(datetime.fromisoformat(index['indexed_at']).astimezone().strftime('%Y-%m-%d %H:%M') if index['indexed_at'] else '历史索引未记录'))
        else: st.caption('当前索引未发布元数据。')
        from agents.documents import DocumentStore
        supplemental=DocumentStore().info()
        st.caption(f"补充参考库：{len(supplemental['sources'])} 份资料 · {supplemental['chunks']} 个切片")
        if supplemental['sources']: st.caption('最近补充索引时间：'+supplemental['sources'][0]['updated'])
    except Exception as exc: st.error('索引状态读取失败：'+str(exc))
st.button('刷新指标')
rows=events()
if not rows:
    st.info('暂无运行数据。通过问诊 Agent 完成一次问诊后，这里会展示耗时、缓存和执行情况。')
else:
    frame=pd.DataFrame(rows)
    scope=st.selectbox('会话范围',['全部会话',*sorted(frame.session.unique())])
    if scope!='全部会话': frame=frame[frame.session==scope]
    requests=frame[frame.kind=='request']; searches=frame[frame.kind=='retrieval']
    cols=st.columns(4)
    cols[0].metric('协作请求',len(requests))
    lat=searches.latency_ms.dropna().tolist() if 'latency_ms' in searches else []
    cols[1].metric('检索平均耗时',f'{np.mean(lat):.1f} ms' if lat else '—')
    cols[2].metric('检索 P99',f'{np.percentile(lat,99):.1f} ms' if lat else '—')
    cols[3].metric('无命中率',f"{searches.no_hit.mean():.0%}" if len(searches) else '—')
    if len(searches):
        st.caption(f"缓存命中率 {searches.cache_hit.mean():.0%}；无命中率不等于标注评估集的 Recall。")
        st.line_chart(searches[['time','latency_ms']].set_index('time'),y='latency_ms')
    calls=frame[frame.kind=='llm']; stats=feedback_stats(frame.to_dict('records'))
    cols=st.columns(3)
    cols[0].metric('LLM 调用记录',len(calls))
    pricing=cost_summary(calls.to_dict('records'),llm_config())
    totals=pricing['totals']
    amount=(next(iter(totals))+' '+f'{next(iter(totals.values())):.6f}') if len(totals)==1 else ('多币种，见明细' if totals else '暂无调用' if not len(calls) else '缺少计价信息')
    cols[1].metric('LLM 成本估算',amount)
    cols[2].metric('好评率',f"{stats['positive']/stats['count']:.0%}" if stats['count'] else '暂无反馈')
    cols=st.columns(3)
    cols[0].metric('差评率',f"{stats['negative']/stats['count']:.0%}" if stats['count'] else '暂无反馈')
    cols[1].metric('反馈覆盖率',f"{stats['coverage']:.0%}")
    cols[2].metric('有效反馈数',stats['count'])
    st.caption('正负反馈率分母为有效反馈数；覆盖率分母为当前范围全部请求数，取消反馈不计入有效反馈。')
    if len(calls):
        st.caption(f"已记录估算 {pricing['recorded']} 次 · 历史参考估算 {pricing['historical']} 次 · 缺少用量 {pricing['missing_usage']} 次 · 缺少适用单价 {pricing['missing_price']} 次")
        st.caption('仅汇总当前可计量的成功调用记录，失败等请求可能另有费用。历史参考估算按当前主模型和单价匹配，不改写日志或补造用量，不等同账单；不同币种分别汇总。')
        if llm_config().pricing_basis=='deepseek_peak_upper_bound':
            st.caption('当前 DeepSeek 参考口径为峰时、输入全部未命中的上限单价，未扣除缓存或非峰时优惠。')
            st.markdown('[核对供应商官方价格](https://api-docs.deepseek.com/quick_start/pricing/)')
        if pricing['missing_price']:
            st.info('部分调用没有适用单价，请在评估与设置的“模型接口”中填写对应模型单价及币种。')
        if pricing['missing_usage']:
            st.info('部分历史调用未记录 token 用量，无法可靠计算费用；不会按零费用处理。')
        calls=pd.DataFrame(pricing['rows'])
        group=st.selectbox('LLM 用量分组',['request','user_id','session','日期'])
        calls=calls.copy(); calls['user_id']=calls.get('user_id',pd.Series('unknown',index=calls.index)).fillna('unknown'); calls['日期']=pd.to_datetime(calls.time,utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y-%m-%d')
        st.caption('user_id 为服务端记录的身份标识；历史测试或未绑定事件可能为 unknown。')
        st.dataframe(calls.groupby([group,'币种','计价状态'],dropna=False).agg(调用数=('request','size')).reset_index(),hide_index=True)
        st.dataframe(calls.groupby([group,'币种'])[['input_tokens','output_tokens','估算成本']].sum(min_count=1).reset_index(),hide_index=True)
    failures=frame[(frame.kind=='failure') | ((frame.kind=='agent') & (frame.status=='失败'))] if 'status' in frame else frame[frame.kind=='failure']
    st.subheader('失败事件')
    explicit=frame[frame.kind=='failure'].copy()
    if len(explicit):
        mapping={'timeout':'超时','rate_limit':'供应商限流','local_rate_limit':'本地限流','parse_failure':'字段校验失败','output_truncated':'模型输出被截断','empty_response':'模型返回空答案','model_refusal':'模型未提供答案','budget_overflow':'单请求预算溢出','session_budget_overflow':'累计预算溢出'}
        explicit['失败类型']=explicit.error.map(mapping).fillna(explicit.error)
        st.dataframe(explicit.groupby('失败类型').size().rename('事件数').reset_index(),hide_index=True)
    st.dataframe(failures.dropna(axis=1,how='all'),hide_index=True)
    st.subheader('Agent 执行记录')
    st.dataframe(frame[frame.kind=='agent'].dropna(axis=1,how='all'),hide_index=True)
