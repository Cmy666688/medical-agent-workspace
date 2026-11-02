import json
from pathlib import Path
import streamlit as st
from ui import llm_config
from public_policy import require_project_admin

require_project_admin()

ROOT=Path(__file__).resolve().parents[1]
st.caption('EVALUATION / CONFIGURATION')
st.title('评估与设置')
tab=st.segmented_control('查看内容',['召回评估','模型接口','项目说明'],default='召回评估')
if tab=='召回评估':
    p=ROOT/'runs/check_full_1031/evaluation.json'
    if p.exists():
        data=json.loads(p.read_text(encoding='utf-8'))
        st.caption('固定 24 条留出问句 · 8,808 条疾病资料 · 本地验证模型，不代表临床准确率')
        from retrieval_evaluation_ui import render_retrieval_comparison
        audit_path=ROOT/'runs/check_full_1031/audit_comparison.json'
        audit=json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else None
        render_retrieval_comparison(data,audit)
        st.image(str(ROOT/'runs/check_full_1031/loss_curve.png'),alt='BGE 50 步微调训练损失曲线')
        st.subheader('检索与生成质量评估')
        st.caption('使用固定留出问句，评估忠实性、切题度与原始疾病简介一致性。评审由同配置 LLM 执行，有自评偏差；未配密钥时只评检索，不填充生成分数。评估会消耗 token 并受会话配额限制。')
        size=st.selectbox('评估问句数',[3,24])
        if not llm_config().api_key:
            st.info('当前未配置模型 API 密钥，本次将只评估检索命中率。要包含生成质量，请先在“模型接口”中完成配置。')
        if st.button('运行端到端评估' if llm_config().api_key else '运行检索评估',type='primary'):
            import asyncio
            from agents.quality import evaluate_quality
            from ui import retrieval
            samples=[json.loads(x) for x in next(ROOT.glob('bert_retrieval_samples*.jsonl')).read_text(encoding='utf-8').splitlines() if x.strip()]
            samples=[x for x in samples if x['split']=='eval'][:size]
            with st.spinner('正在评估，请等待实际结果…'):
                try:
                    report=asyncio.run(evaluate_quality(retrieval(),samples,llm_config(),st.session_state.session_id))
                    st.session_state.quality_report=report
                except Exception as exc: st.error('本次评估失败：'+str(exc))
        if 'quality_report' in st.session_state:
            report=st.session_state.quality_report
            from evaluation_ui import render_quality_report
            render_quality_report(report)
    else: st.info('暂无评估文件，请运行训练脚本。')
elif tab=='模型接口':
    st.write('这里填写 API 服务商提供的模型 ID。文本模型用于问诊、重排和资料解读；视觉模型用于图片识别。本地 BGE 检索模型无需在这里填写。')
    st.caption('页面设置仅用于当前管理员会话。服务默认配置由本机 config/api.local.toml 维护，已保存的密钥不会回显。')
    cfg=llm_config()
    with st.form('llm_settings'):
        url=st.text_input('API base URL（以 /v1 等接口前缀结束）',value=cfg.base_url)
        model=st.text_input('文本模型 ID',value=cfg.model,placeholder='填写服务商提供的完整模型 ID')
        key=st.text_input('API key',value='',type='password',placeholder='留空保留已有或文件配置，不回显密钥')
        budget=st.number_input('单次请求 token 预算（保守上界）',2000,50000,cfg.budget_tokens,1000)
        inp=st.number_input('输入价格 / 百万 token（供应商计价货币）',min_value=0.0,value=float(cfg.input_price))
        out=st.number_input('输出价格 / 百万 token（同一货币）',min_value=0.0,value=float(cfg.output_price))
        currencies=['未指定','USD','CNY']
        currency=st.selectbox('单价币种',currencies,index=currencies.index(cfg.price_currency) if cfg.price_currency in currencies else 0)
        bases={'configured_rates':'按填写单价参考估算','deepseek_peak_upper_bound':'DeepSeek 峰时未命中上限参考'}
        basis=st.selectbox('计价口径',list(bases),format_func=bases.get,index=1 if cfg.pricing_basis=='deepseek_peak_upper_bound' else 0)
        st.caption('这些价格仅用于费用估算，不改变服务商实际扣费；缺失 token 用量时不填补为零。')
        st.subheader('备用接口与调用控制')
        backup_url=st.text_input('备用 API base URL',value=cfg.fallback_url)
        backup_model=st.text_input('备用模型名称',value=cfg.fallback_model)
        backup_key=st.text_input('备用 API key',value='',type='password',placeholder='留空保留已有配置')
        fip=st.number_input('备用接口输入价格 / 百万 token',min_value=0.0,value=float(cfg.fallback_input_price))
        fop=st.number_input('备用接口输出价格 / 百万 token',min_value=0.0,value=float(cfg.fallback_output_price))
        st.subheader('视觉观察 Agent')
        vision=st.text_input('视觉模型 ID（需要支持图片输入）',value=cfg.vision_model,placeholder='填写视觉或多模态模型 ID')
        vf=st.text_input('备用视觉模型名称（可留空）',value=cfg.vision_fallback_model)
        vision_url=st.text_input('视觉接口地址（留空共用文本接口）',value=cfg.vision_url)
        vision_key=st.text_input('视觉 API key（留空保留配置，未配置时共用文本密钥）',value='',type='password')
        response_format=st.selectbox('结构化输出模式',['json_schema','json_object'],index=0 if cfg.response_format=='json_schema' else 1)
        rerank=st.checkbox('检索后使用文本模型重排证据',value=cfg.enable_rerank)
        specialist=st.checkbox('使用文本模型复核风险与用药资料',value=cfg.enable_specialist_review)
        vip=st.number_input('视觉模型输入价格 / 百万 token',min_value=0.0,value=float(cfg.vision_input_price))
        vop=st.number_input('视觉模型输出价格 / 百万 token',min_value=0.0,value=float(cfg.vision_output_price))
        st.caption('视觉模型必须支持图片输入，图片仅在你同意并点击识别后传给服务商。')
        session_tokens=st.number_input('会话累计 token 预留上限',1000,10000000,cfg.session_tokens,1000)
        calls_per_minute=st.number_input('每会话每分钟调用上限（含重试）',1,120,cfg.calls_per_minute)
        st.caption('每次网络尝试预留保守 token 上界，失败后不返还；备用接口单价未配置，成本显示未计价。资料解读使用流式 API 接收，完成校验后展示。')
        save=st.form_submit_button('应用配置',type='primary')
    if save:
        if url!=cfg.base_url and cfg.api_key and not key.strip(): st.error('更换文本接口地址时，请同时填写对应的新密钥。')
        elif backup_url!=cfg.fallback_url and cfg.fallback_key and not backup_key.strip(): st.error('更换备用接口地址时，请同时填写对应的新密钥。')
        elif vision_url!=cfg.vision_url and (cfg.vision_key or cfg.api_key) and not vision_key.strip(): st.error('更换视觉接口地址时，请同时填写对应的新密钥。')
        elif (key or cfg.api_key) and (not url.startswith(('http://','https://')) or not model): st.error('请填写完整接口地址和模型名称。')
        elif (backup_key or cfg.fallback_key) and (not backup_url.startswith(('http://','https://')) or not backup_model): st.error('请补全备用接口地址和模型名称。')
        elif vision_url and not vision_url.startswith(('http://','https://')): st.error('请填写有效视觉接口地址。')
        else:
            st.session_state.update(base_url=url,llm_model=model,budget=budget,input_price=inp,output_price=out,fallback_url=backup_url,fallback_model=backup_model,session_tokens=session_tokens,calls_per_minute=calls_per_minute)
            st.session_state.update(price_currency='' if currency=='未指定' else currency,pricing_basis=basis)
            st.session_state.update(vision_model=vision,vision_fallback_model=vf,vision_input_price=vip,vision_output_price=vop,fallback_input_price=fip,fallback_output_price=fop)
            st.session_state.update(vision_url=vision_url,response_format=response_format,enable_rerank=rerank,enable_specialist_review=specialist)
            for state_name,secret in [('api_key',key),('fallback_key',backup_key),('vision_key',vision_key)]:
                if secret.strip(): st.session_state[state_name]=secret.strip()
            st.success('配置已应用。下一次问诊将按此配置运行。')
else:
    st.subheader('系统使用指南')
    st.write('问诊 Agent 负责多轮信息整理，并协同检索、用药资料核对、风险提示与资料解读。每轮结果可展开查看原文证据与协作记录。')
    st.write('家庭组用于邀请家人、授权查看近况、安排关怀提醒和指定成员留言。')
    st.write('在医疗知识库中查询疾病记录、添加共享参考资料；在召回评估中检查检索与生成结果。')
    st.caption('医疗资料与模型解读用于问诊准备，不能替代医生诊断或药师用药审查。')
    if st.session_state.get('developer_mode'):
        audit=ROOT/'项目验收对照.md'
        st.download_button('下载工程验收对照表',audit.read_text(encoding='utf-8'),file_name=audit.name)
