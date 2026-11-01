import streamlit as st

ERRORS={'vision_not_configured':'请先配置支持图片输入的模型。','timeout':'模型响应超时，请稍后重试。','rate_limit':'模型服务繁忙，请稍后重试。','local_rate_limit':'本分钟请求较多，请稍后再试。','budget_overflow':'本次内容超过调用预算，请减少内容或调整设置。','session_budget_overflow':'当前会话额度已用完。','parse_failure':'模型回复格式不完整，已保留本地结果。','invalid_citation':'回复包含未检索到的来源，已拦截。'}
def friendly_error(value): return ERRORS.get(value,'本次处理没有完成，请检查配置后重试。')

def bullet(items):
    for item in items or []: st.write('• '+str(item))

def render_output(agent,output):
    if 'chief_complaint' in output:
        st.markdown('**你的描述**'); st.write(output['chief_complaint'])
        st.markdown('**整理出的症状**')
        if output.get('symptoms'): bullet(output['symptoms'])
        else: st.caption('目前还没有提取到明确症状，请继续描述。')
        if output.get('followup'):
            st.markdown('**请补充这些信息**'); bullet(output['followup'])
    elif 'red_flags' in output:
        if output['red_flags']:
            st.warning(output['recommendation']); st.write('触发提示的描述：'+'、'.join(output['red_flags']))
        else: st.info(output.get('recommendation','需要更多信息才能评估。'))
        st.caption('这是演示规则提示，不是临床风险评分。')
    elif 'current_medications' in output:
        st.write('当前用药：'+(output['current_medications'] or '尚未提供'))
        st.write('药物过敏史：'+(output.get('allergies') or '尚未提供'))
        if output.get('missing'): st.warning('请补充：'+'、'.join(output['missing']))
        st.info(output.get('recommendation','用药信息需要进一步核实。'))
    elif 'evidences' in output:
        from ui import evidence_cards
        st.write(f"找到 {len(output['evidences'])} 条资料")
        evidence_cards(output['evidences'])
    elif 'points' in output:
        st.write(output.get('summary','资料整理完成。'))
        for item in output['points']:
            with st.container(border=True):
                st.markdown('**'+item['name']+'**'); st.write(item['excerpt'])
                st.caption('来源记录：'+item['doc_id'])
    elif output.get('summary'):
        st.write(output['summary']); bullet(output.get('followup')); bullet(output.get('limitations'))
    elif output.get('reason'): st.caption(output['reason'])
    else: st.caption('处理已完成，可在对应功能页面查看结果。')

def debug_output(value,key=None):
    if st.session_state.get('developer_mode',False):
        with st.expander('开发调试数据'): st.json(value)
