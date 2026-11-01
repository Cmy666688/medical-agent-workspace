"""页面导航和展示共享的唯一 Agent 注册表。"""
AGENTS = {
    'consultation': dict(name='问诊 Agent',icon='clinical_notes',page='agent_consultation',role='多轮问诊，协同风险评估、检索、用药核对与资料解读',input='症状描述、照片、个人情况和会话历史',output='问诊追问、风险提示、相关资料和原文依据',scope='本地规则与知识库协作；配置模型后可进行结构化提取和资料解读。'),
    'retrieval': dict(name='检索 Agent',icon='travel_explore',page='agent_retrieval',role='查找可引用的医疗资料',input='问诊问题或疾病名称',output='疾病资料、相关性分数和原始记录 ID',scope='已接入 BGE 与 Milvus；当前是向量检索，尚无精排或指南文献库。'),
    'medication': dict(name='用药 Agent',icon='medication',page='agent_medication',role='核对用药相关信息',input='药物过敏史、当前用药',output='信息缺项及需人工核实事项',scope='当前仅检查信息完整性，尚未实现药物相互作用、禁忌或处方推荐。'),
    'risk': dict(name='风险评估 Agent',icon='health_and_safety',page='agent_risk',role='优先提示危险信号，结合相关资料整理风险信息',input='症状描述、问诊上下文与用药信息',output='危险信号、已知信息、待补充问题、参考资料与用药核对',scope='风险提醒先展示，资料检索继续进行；当前为关键词检查及可选模型复核，不构成临床风险评分。'),
    'vision': dict(name='视觉观察 Agent',icon='photo_camera',page='agent_vision',role='拍照或上传图片，整理可见特征',input='照片与观察问题',output='外观特征、可辨认文字及局限',scope='需配置视觉模型，不直接诊断。'),
    'family': dict(name='家庭协作 Agent',icon='family_restroom',page='agent_family',role='创建家庭、管理授权与组内交流',input='成员访问密钥、共享授权与留言',output='家庭成员、共享范围与留言板',scope='成员密钥验证；健康共享由本人逐项授权。'),
    'schedule': dict(name='定时关怀 Agent',icon='alarm',page='agent_schedule',role='按时服药、测量提醒与完成确认',input='每日提醒时间与事项',output='站内待办、完成状态和计划',scope='后台进程运行且电脑开机时调度，不发送手机推送。'),
    'care': dict(name='亲属照护 Agent',icon='diversity_1',page='agent_care',role='查看授权记录并远程发起关怀请求',input='手动健康记录、本人授权',output='记录时间、待办状态与请求',scope='可管理已获授权的站内提醒；未接入穿戴设备。'),
    'education': dict(name='资料解读 Agent',icon='description',page='agent_education',role='解读检索证据并保留来源',input='检索 Agent 提供的资料',output='资料摘要、来源 ID 和局限',scope='本地来源汇总；在线解读须配置模型。'),
}
