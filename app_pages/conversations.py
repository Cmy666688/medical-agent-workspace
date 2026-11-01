from datetime import datetime,timedelta,timezone
import streamlit as st
from agents import conversations as store
from conversation_ui import switch_conversation,ensure_conversation

st.caption('个人空间 / 历史对话')
st.title('历史对话',icon=':material/history:')
st.write('新建对话会保留旧记录。可以继续问诊、重命名、导出或删除指定会话。')
st.caption('记录保存在本机服务中，仅当前账号可访问。这里不保存相机照片或 API 密钥。')
query=st.text_input('搜索对话名称',placeholder='输入名称关键词')
records=store.listing(st.session_state.personal_token,query)
if not records: st.info('暂无匹配的对话。')
else: st.caption(f'显示最近 {len(records)} 条匹配记录')
for item in records:
    key=item['id']
    with st.container(border=True):
        st.subheader(item['title'])
        stamp=datetime.fromisoformat(item['updated']).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
        st.caption(f"{item['turn_count']} 轮问诊 · 更新于 {stamp}（北京时间）"+(' · 当前对话' if key==st.session_state.conversation_id else ''))
        st.button('继续对话',key='continue_'+key,on_click=switch_conversation,args=(key,),icon=':material/forum:')
        with st.expander('管理这段对话'):
            with st.form('rename_'+key):
                title=st.text_input('对话名称',value=item['title'],max_chars=80)
                if st.form_submit_button('保存名称'):
                    try: store.rename(st.session_state.personal_token,key,title); st.rerun()
                    except ValueError as exc: st.error(str(exc))
            if st.button('准备导出',key='export_prepare_'+key): st.session_state['export_chat_'+key]=True
            if st.session_state.get('export_chat_'+key):
                record=store.load(st.session_state.personal_token,key)
                st.download_button('下载中文对话记录',store.markdown(record),file_name='问诊对话.md',key='export_download_'+key,mime='text/markdown')
            confirm=st.checkbox('确认仅删除这段对话，删除后无法恢复',key='confirm_delete_'+key)
            if st.button('删除这段对话',key='delete_'+key,disabled=not confirm,icon=':material/delete:'):
                store.delete(st.session_state.personal_token,key)
                st.session_state.pop('export_chat_'+key,None)
                if st.session_state.conversation_id==key:
                    st.session_state.pop('conversation_id',None)
                    st.session_state.turns=[]
                    ensure_conversation()
                st.rerun()
