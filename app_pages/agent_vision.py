import asyncio
import json
import streamlit as st
from agents.vision import VisionAgent,prepare_image
from ui import llm_config

st.caption('医知协作 / Agent 中心')
st.title('视觉观察 Agent',icon=':material/photo_camera:')
st.write('拍一张照片或上传图片，让视觉模型整理可见特征、可辨认文字和需要补充的信息。')
st.caption('支持普通物体、药品包装文字等图片查阅；医疗照片只做外观观察，不提供诊断、身份识别或处方。')
source=st.segmented_control('图片来源',['上传照片','相机拍照'],default='上传照片')
if source=='上传照片':
    photo=st.file_uploader('选择 JPG / PNG / WebP 图片',type=['jpg','jpeg','png','webp'],max_upload_size=10,key='vision_upload_'+st.session_state.session_id)
else:
    st.info('相机由浏览器请求权限；请允许使用摄像头。localhost 可用，远程部署需 HTTPS。')
    photo=st.camera_input('拍摄照片',key='vision_camera_'+st.session_state.session_id)
question=st.text_area('你希望观察什么？',value='请描述图片中可见的内容和文字，并说明看不清或无法判断的部分。',max_chars=1000)
cfg=llm_config()
if not cfg.api_key or not cfg.vision_model:
    st.warning('尚未配置视觉模型。请先在“评估与设置 → 模型接口”填写支持图片输入的模型名称及 API key。')
    st.page_link('app_pages/evaluation.py',label='前往配置视觉模型',icon=':material/settings:')
consent=st.checkbox('点击识图时，将图片和本页问题发送至已配置的模型服务；图片不写入本机日志。')
if photo:
    try:
        info=prepare_image(photo.getvalue())
        st.image(photo.getvalue(),width=420,alt='待识别图片预览')
        st.caption(f"原图 {info['width']} × {info['height']}，发送前缩小至最长边 512 像素并去除 EXIF 信息。小字可能无法辨认。")
        if st.session_state.get('vision_hash')!=info['sha256']:
            st.session_state.pop('vision_result',None); st.session_state.vision_hash=info['sha256']
    except ValueError as exc:
        st.error(str(exc)); photo=None
if st.button('调用视觉 Agent 识图',type='primary',disabled=not(photo and consent and cfg.api_key and cfg.vision_model)):
    with st.spinner('正在调用视觉模型…'):
        st.session_state.vision_result=asyncio.run(VisionAgent(cfg).run(photo.getvalue(),question,st.session_state.session_id))
result=st.session_state.get('vision_result') if photo else None
if result:
    if result['status']=='失败': st.error('本次识图未完成：'+result['error'])
    else:
        output=result['output']
        st.subheader('图片观察结果')
        st.write(output['description'])
        left,right=st.columns(2)
        with left:
            st.markdown('**可见特征**')
            for text in output['visible_features']: st.write('• '+text)
            st.markdown('**可辨认文字**')
            if not output['text_in_image']: st.caption('没有可靠辨认的文字。')
            for text in output['text_in_image']: st.write(text)
        with right:
            st.markdown('**图片质量与局限**'); st.write(output['image_quality'])
            for text in output['limitations']: st.write('• '+text)
            st.markdown('**建议补充的信息**')
            for text in output['followup_questions']: st.write('• '+text)
        st.caption('以上内容由视觉模型生成，请核对原图，尤其不要据此自行用药。')
        st.download_button('导出观察结果',json.dumps(result,ensure_ascii=False,indent=2),file_name='visual_observation.json')
        if st.button('带着这些观察继续问诊'):
            st.session_state.vision_handoff='图片观察（AI 描述，未经核实，不是诊断）：'+output['description']+'；'+ '；'.join(output['visible_features'])
            st.switch_page('app_pages/agent_consultation.py')
