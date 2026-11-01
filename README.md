# 医知协作 · Medical Agent Workspace

基于 Streamlit 的医疗资料与家庭关怀协作系统。以问诊 Agent 为统一入口，协调资料检索、风险信息提示、用药资料核对与资料解读，并提供家庭成员授权、定时关怀和持久化历史对话。

![医知协作视觉主题](assets/wellness-orbit.svg)

> 本项目用于课程实验与问诊准备，不是经过临床验证的诊断或处方系统。不输出校准后的患病概率、未经验证的慢病风险分数或药物剂量。

## 功能

- **账号与历史**：注册、登录、恢复码、过期及可撤销会话；历史对话按账号保存，支持切换、搜索、重命名、导出和单条删除。
- **多 Agent 问诊**：多轮信息采集、危险信号优先处理、证据汇总、实时阶段状态和执行轨迹。
- **独立风险信息整理**：展示本次提交内容、已提供的持续时间/程度/伴随情况及待补充问题；已配置文本模型时进行在线信息复核，超时或格式错误保留本地结果并明确提示，危险信号优先处理。
- **结构化接口兼容**：官方 DeepSeek 接口的 JSON 提取任务关闭默认推理，输出预留 2,048 token；空答案或截断最多恢复重试一次，每次预留额度并保持字段校验。监控仅记录结束原因、长度和用量，不保存模型推理内容。
- **原生 RAG**：BGE + Milvus 向量检索、中文 BM25、RRF 融合及可选的 LLM 重排；检索路径不使用 LangChain。
- **资料增量索引**：TXT、Markdown、带文字层 PDF，按页切片、重叠、来源页码、后台队列、重复文件去重与原子替换。
- **视觉输入**：在问诊和用药页面拍照或上传图片，观察可见特征、识别文字，结果可交给问诊流程。
- **家庭组**：邀请码加入家庭、指定成员私信、健康记录、逐成员共享权限、远程关怀请求与提醒管理。
- **关怀提醒**：多种提醒类型，支持单次、每日、每周、时段间隔与生效日期范围。
- **工程能力**：兼容 Chat Completions、JSON Schema/JSON 模式、重试、主备接口、SSE 接收、配额、成本事件、反馈和中文质量评估报告。

## 快速开始

建议 Python 3.13。克隆仓库后在项目根目录执行：

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
```

将 `config/api.example.toml` 复制为 **`config/api.local.toml`**，填写自己服务商的接口、密钥与模型 ID。密钥文件已被 Git 忽略。

Windows 可双击 **启动医知协作.cmd**。它会启动网页和提醒服务，就绪后打开：

```text
http://localhost:8502/account
```

也可只启动网页：

```bash
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

**首次启动需注册账号。** 未登录时所有功能页只呈现登录入口。API 未配置时可使用账号、历史和家庭功能；模型调用不会返回伪造结果。

## 检索资源需要另行准备

本仓库仅发布源码、配置模板、项目文档和测试，**不包含医疗原始数据、课程原文、模型权重、训练产物或用户数据库**。

医疗检索依赖本地 BGE 权重及 Milvus 索引；只克隆代码尚不能执行完整医疗检索。准备自己的授权数据或恢复自己的模型备份，具体目录、训练与索引命令见 [部署说明](docs/DEPLOYMENT.md)。当前数据管道针对 8808 条疾病记录和 512 维向量，换用其他语料需要调整校验与字段适配。

## 配置与说明

- [API 配置与交付说明](API配置与交付说明.md)
- [运行与部署说明](docs/DEPLOYMENT.md)
- [检索与训练运行说明](运行说明.md)
- [项目验收范围与历史记录](项目验收对照.md)

文件配置支持独立文本/视觉服务、备用服务与预算。页面配置优先于环境变量和文件；私有文件中的密钥不回显到浏览器。没有密钥时生成质量评审会明确跳过，不将空指标展示成零分。

## 测试

离线业务和 API 契约测试不需要真实密钥，使用合成 HTTP 响应：

```bash
mkdir -p runtime
python -m unittest test_accounts test_family test_family_extensions test_identity_product test_conversations
python -m unittest test_llm_engineering test_vision_monitor test_project_completion
```

Windows PowerShell 可先运行 `New-Item -ItemType Directory -Force runtime`。

`test_*pages.py` 使用 Streamlit AppTest 验证界面。`verify_project.py` 使用真实本地权重、数据和索引验证检索与文档编码，需要先准备相关资源；不应将合成测试结果当成真实医学评估成绩。

## 部署范围

GitHub 仓库用于托管代码，**GitHub Pages 不能运行此 Python 后端**。在线服务需要另外配置服务器、HTTPS 和持久磁盘。当前提醒工作进程的单实例锁使用 Windows `msvcrt`，Linux 部署需要适配锁及进程管理。浏览器相机、异地网络和真实供应商调用需要在目标环境验证。

账号、家庭、消息、历史对话和补充索引存放在 `runtime/`；本地 API 密钥、数据库、日志与模型资源不纳入版本控制。请不要将已有用户的运行目录当作公开演示数据。
