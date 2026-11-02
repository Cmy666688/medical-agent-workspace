import streamlit as st
from ui import document_jobs
from agents.documents import read_upload,DocumentStore

def document_panel():
    from public_policy import public_mode
    from agents.family import identity_profile
    token=st.session_state.get('personal_token')
    if public_mode() or not token or identity_profile(token).get('role')!='admin':
        st.caption('共享参考库由服务管理者维护。')
        return
    with st.expander('添加参考资料 / 增量索引',icon=':material/library_add:'):
        st.caption('支持 UTF-8 文本、Markdown 和带文字层的 PDF。资料按页切片，更新同名文件会原子替换旧版本；不重新训练模型或覆盖原疾病库。')
        photo=st.file_uploader('选择参考资料',type=['txt','md','pdf'],max_upload_size=5,key='knowledge_document')
        consent=st.checkbox('添加到本服务的共享参考库，供登录用户检索；文件不含私人病历或身份信息。',key='knowledge_consent')
        if st.button('提交索引任务',disabled=not(photo and consent),type='primary'):
            try:
                pages=read_upload(photo.getvalue(),photo.name)
                job=document_jobs().submit(photo.name,pages)
                st.success('任务已提交，后台处理过程中可以切换页面。')
            except Exception as exc:
                st.error(str(exc) if isinstance(exc,ValueError) else '资料提交失败，请检查文件格式与运行日志。')
        index_status()

@st.fragment(run_every='3s')
def index_status():
    store=DocumentStore(); info=store.info()
    st.caption(f"补充参考库：{len(info['sources'])} 份资料 · {info['chunks']} 个切片")
    # Loading the queue resumes interrupted tasks, but does not load inference until a job exists.
    tasks=document_jobs().jobs()
    labels={'queued':'等待处理','running':'索引中','completed':'已完成','failed':'失败，可重新提交'}
    if tasks:
        st.dataframe([dict(资料=item['source'],状态=labels[item['status']],完成切片=item['progress'],总切片=item['total']) for item in tasks],hide_index=True,alt='资料索引任务进度')
    if info['sources']:
        with st.expander('已入库资料'): st.dataframe(info['sources'],column_config={'name':'资料名称','updated':'更新时间'},hide_index=True,alt='补充参考库的资料名称和更新时间')
