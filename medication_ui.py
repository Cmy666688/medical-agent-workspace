"""Human-readable views of source-matched medication information."""
import re
from urllib.parse import urlparse
import streamlit as st

SECTIONS={'boxed_warning':'黑框警告','contraindications':'禁忌','drug_interactions':'药物相互作用','warnings_and_cautions':'警告与注意事项','warnings':'警告','do_not_use':'不适用情形','ask_doctor':'需咨询医生的情形','stop_use':'停止使用并咨询的原文说明'}

def reference_links(attachments):
    for key,title in [('仿單圖檔連結','TFDA 说明书原件'),('外盒圖檔連結','TFDA 外盒资料')]:
        values=attachments.get(key,[])
        if isinstance(values,str): values=[values]
        for value in values[:2]:
            for url in re.findall(r'https?://[^\s<>\"\']+',value)[:2]:
                host=urlparse(url).hostname or ''
                if host=='fda.gov.tw' or host.endswith('.fda.gov.tw'):
                    st.link_button(title,url)

def medication_output(output):
    st.write('当前用药：'+(output.get('current_medications') or '尚未提供'))
    st.write('药物过敏史：'+(output.get('allergies') or '尚未提供'))
    if output.get('missing'): st.warning('请补充：'+'、'.join(output['missing']))
    st.info(output.get('recommendation','用药信息需要进一步核实。'))
    if output.get('input_error'): st.warning(output['input_error']);return
    if output.get('no_medications_reported'): st.caption('你填写了当前未用药，因此没有执行药物对匹配。')
    for item in output.get('items',[]):
        with st.container(border=True):
            st.markdown('**'+item['input']+'**')
            if item['status']=='not_found':
                st.warning('未识别到确定药名。请提供准确的通用名、完整商品名或许可证号；不要据此判断可否使用。')
            elif item['status']=='ambiguous': st.warning('同名候选的成分不同，尚未选择具体产品；请用许可证号重新核对。')
            else:
                st.write('匹配成分：'+'、'.join(item['components']))
                st.caption(item.get('note','以下是同名或许可证对应的 TFDA 记录；多个候选时仍需核对具体剂型与规格。'))
            if item.get('suggestions'):
                st.write('可进一步核对的许可证（请复制准确号码重新输入）：')
                for i,key in enumerate(item['suggestions']): st.text((item.get('suggestion_names',[])[i]+' · ' if i<len(item.get('suggestion_names',[])) else '')+key)
            for record in item.get('products',[]):
                with st.expander('TFDA · '+record['name_zh']+' · '+record['id']):
                    st.write('成分原文：'+(record['ingredient_text'] or '未记录'))
                    st.write('剂型：'+(record['form'] or '未记录'))
                    st.caption(record['region']+'；'+record['registry_status']+'；有效日期：'+(record['valid_until'] or '未知'))
                    reference_links(record['attachments'])
                    st.link_button('查看 TFDA 数据来源',record['source'])
            if item['components'] and not item.get('labels'): st.caption('本地 openFDA 标签未覆盖这一成分组合，不代表没有禁忌或相互作用。')
            for label in item.get('labels',[]):
                with st.expander('openFDA 标签参考 · '+' / '.join(label['names'])+' · '+label['effective']):
                    st.caption('同成分的美国标签参考，并非上方 TFDA 产品的说明书；剂型、途径和适应范围需要核对。下列为截取的原文，不是个体用药结论。')
                    st.caption('标签给药途径原文：'+'、'.join(label['routes']))
                    for section,paragraphs in label['sections'].items():
                        st.markdown('**'+SECTIONS.get(section,section)+'**')
                        st.text('\n'.join(paragraphs))
                    st.link_button('核对完整标签与版本',label['source'])
    if output.get('duplicates'):
        st.subheader('重复成分待核实')
        for item in output['duplicates']: st.warning(' / '.join(item['drugs'])+' 涉及相同成分：'+'、'.join(item['components'])+'。请核对是否为重复描述或实际重复用药。')
    if output.get('interactions'):
        st.subheader('药物相互作用资料匹配')
        for pair in output['interactions']:
            st.markdown('**'+' / '.join(pair['drugs'])+'**')
            if pair['records']:
                for record in pair['records']:
                    st.warning(record['name_a']+' / '+record['name_b']+'：'+record['level_label']+'。这是数据库记录等级，不是个体临床风险评分。')
                st.link_button('DDInter 来源与覆盖说明',pair['records'][0]['source'])
                st.caption('已下载 CSV 只有药物对和等级，不含完整机制或处置建议。')
                if pair.get('uncovered'): st.caption('另有成分对未被当前子集覆盖；没有完成全面审查。')
            elif pair['status']=='unresolved': st.warning('存在未确定的药名，无法完成这一组合的匹配。')
            elif pair['status']=='duplicate_only': st.info('此组合涉及同一成分，需先核对是否实际重复用药。')
            else: st.info('当前 DDInter 子集没有该组合的记录，不代表没有相互作用或可以安全合用。')
    info=output.get('knowledge_info',{})
    if info.get('ready'):
        with st.expander('数据来源、版本与覆盖范围'):
            st.caption('索引构建时间：'+info['built_at'])
            for source,coverage in info['coverage'].items(): st.write(source+'：'+coverage)
            for source,license in info['licenses'].items(): st.caption(source+' · '+license)
