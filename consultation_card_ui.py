"""Editable consultation card; business rules and persistence are separate modules."""
import time
import streamlit as st
from agents import conversations as store
from agents.consultation_card import FIELDS, STATUSES, summary
from agents.telemetry import record


def card_panel():
    token = st.session_state.personal_token
    conversation = st.session_state.conversation_id
    # Migrate existing turns lazily. Receipts make reruns idempotent, including conflicts.
    for turn in st.session_state.turns:
        original = turn.get('card_original', turn['question'].split('\n图片观察（AI 描述，未经核实）：')[0])
        if not original.strip(): continue
        store.ingest_card(token, conversation, turn['request'], original)
    card = store.load_card(token, conversation)
    prefix = f'check_card_{conversation}_{card["version"]}'
    with st.container(border=True):
        st.subheader('问诊信息核对卡', icon=':material/fact_check:')
        st.caption(f'第 {card["version"]} 版 · 自动整理的内容请核对；修改内容后点击“确认并保存”。')
        st.caption('未提供：没有填写；不清楚：暂时无法确定；待确认：已整理但尚未核实；已确认：你已核对。')
        notice = st.session_state.pop('card_saved_notice', None)
        if notice: st.success(notice)
        with st.form(prefix + '_form'):
            edits = {}
            for key, label in FIELDS.items():
                field = card['fields'][key]
                if field['pending']:
                    st.warning(f'{label}出现不同描述。已保存：{field["value"]}；新提取：{field["pending"]["value"]}。请修改下方内容采用新值，或保留原值后确认。')
                left, right = st.columns([3, 1], vertical_alignment='bottom')
                value = left.text_input(label, value=field['value'], key=prefix+'_'+key, max_chars=1000)
                # Saving promotes provided values to confirmed; unknown/missing remain explicit.
                default = field['status']
                status = right.selectbox(label+'确认状态', STATUSES, index=STATUSES.index(default), key=prefix+'_'+key+'_status')
                st.caption('当前保存状态：'+field['status'])
                edits[key] = dict(value=value, status=status)
            submitted = st.form_submit_button('确认并保存', type='primary')
        if submitted:
            tick = time.perf_counter()
            try:
                # Entering a value into a missing field counts as an explicit confirmation.
                for key, item in edits.items():
                    if item['status'] == '待确认' and item['value'].strip():
                        item['status'] = '已确认'
                    if card['fields'][key]['status'] == '未提供' and item['value'].strip() and item['status'] == '未提供':
                        item['status'] = '已确认'
                saved = store.save_card(token, conversation, edits, card['version'])
            except store.CardConflict as exc:
                st.warning(str(exc))
                st.session_state.card_saved_notice = '已载入最新核对卡，请再次核对后保存。'
                st.rerun()
            except (ValueError, PermissionError) as exc: st.error(str(exc))
            else:
                # Do not send field values, original text, or history to the monitor.
                if saved['version'] != card['version']:
                    record(conversation, 'card-v'+str(saved['version']), 'agent', agent='问诊信息核对', status='完成',
                           latency_ms=(time.perf_counter()-tick)*1000, version=saved['version'])
                st.session_state.card_saved_notice = f'已保存第 {saved["version"]} 版核对卡。' if saved['version'] != card['version'] else '内容未变化，已保留当前版本。'
                st.rerun()
        with st.expander('查看字段来源与修改版本', icon=':material/history:'):
            for key, label in FIELDS.items():
                field = card['fields'][key]
                st.markdown('**'+label+'**')
                st.write('当前内容：'+(field['value'] or '未提供')+' · '+field['status'])
                sources = field['sources'] + (field['pending']['sources'] if field['pending'] else [])
                for source in sources:
                    st.caption(source['origin']+' · 来源请求 ID：'+source['request_id'])
                    st.text(source['quote'])
                if not sources: st.caption('尚无来源')
            for version in store.card_versions(token, conversation):
                with st.expander(f'第 {version["version"]} 版 · {version["reason"]} · {version["created"]}'):
                    for key, label in FIELDS.items():
                        field = version['fields'][key]
                        st.text(label+'：'+(field['value'] or '未提供')+'（'+field['status']+'）')
        st.download_button('下载 Markdown 问诊摘要', summary(card['fields'], card['version']),
                           file_name='问诊信息摘要.md', mime='text/markdown', key=prefix+'_download')
    return card
