import asyncio
import streamlit as st
from agents.vision import VisionAgent,prepare_image
from ui import llm_config
from result_ui import friendly_error

def vision_panel(context='consultation'):
    medication=context=='medication'
    title='拍照识别药品包装或说明书' if medication else '用照片补充症状描述'
    prefix='embedded_vision_'+context
    with st.expander(title,icon=':material/photo_camera:'):
        st.caption('支持拍照与上传。只整理可见特征和文字，不能仅凭图片确认疾病、药物真伪或剂量。')
        source=st.segmented_control('添加照片方式',['上传照片','相机拍照'],default='上传照片',key=prefix+'_source')
        key=prefix+'_'+st.session_state.session_id
        if source=='上传照片': photo=st.file_uploader('选择图片',type=['jpg','jpeg','png','webp'],max_upload_size=10,key=key+'_upload')
        else: photo=st.camera_input('拍摄清晰照片',key=key+'_camera')
        cfg=llm_config()
        if not (cfg.vision_key or cfg.api_key) or not cfg.vision_model:
            st.caption('请在“评估与设置 → 模型接口”配置视觉模型后使用识图。')
        consent=st.checkbox('点击识别时将图片发送给已配置模型服务，图片不写入日志。',key=prefix+'_consent')
        info=None
        if photo:
            try:
                info=prepare_image(photo.getvalue()); st.image(photo.getvalue(),width=300,alt='待识别照片')
            except ValueError as exc: st.error(str(exc))
        if info and st.session_state.get(prefix+'_hash')!=info['sha256']:
            st.session_state[prefix+'_hash']=info['sha256']; st.session_state.pop(prefix+'_result',None)
        if st.button('识别包装文字' if medication else '观察照片',key=prefix+'_run',disabled=not(info and consent and (cfg.vision_key or cfg.api_key) and cfg.vision_model)):
            question='请识别包装或说明书上清晰可见的药品名称、规格等文字；看不清的不要猜，不推荐处方或剂量。' if medication else '请中性描述可见外观特征，指出图片质量与局限，不作诊断，并列出需要补充的信息。'
            with st.spinner('正在观察图片…'):
                st.session_state[prefix+'_result']=asyncio.run(VisionAgent(cfg).run(photo.getvalue(),question,st.session_state.session_id))
        result=st.session_state.get(prefix+'_result') if photo else None
        if result:
            if result['status']!='完成': st.warning(friendly_error(result.get('error')))
            else:
                output=result['output']; st.write(output['description'])
                if output['text_in_image']:
                    st.markdown('**图片中的文字（请核对原图）**')
                    for item in output['text_in_image']: st.text(item)
                if output['visible_features']:
                    st.markdown('**可见特征**')
                    for item in output['visible_features']: st.write('• '+item)
                st.caption(output['image_quality'])
                for item in output['limitations']: st.caption('注意：'+item)
                if not medication and st.button('作为下一次问诊的补充',key=prefix+'_handoff'):
                    st.session_state.vision_handoff='图片观察（AI 描述，未经核实）：'+output['description']+'；'+'；'.join(output['visible_features'])
                    st.success('已添加。请在问诊输入框继续描述你的情况。')
