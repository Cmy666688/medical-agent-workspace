# 运行与部署

## GitHub 仓库与在线服务

GitHub 托管源码。这个项目是 Python/Streamlit 后端应用，不能通过 GitHub Pages 执行 Python。推送代码不会自动获得一个运行中的问诊网站。

可在本机、自己的服务器或支持持久磁盘的 Python 容器平台启动。平台需要运行网页进程和提醒工作进程，并为运行目录提供持久存储。账号、家庭、对话与索引都是本地持久化数据，不能放在会随每次发布清空的临时文件系统中。

## 基本启动

### 本机 HTTPS 公网入口（Windows）

安装官方 `cloudflared` 后，双击根目录“启动公网入口.cmd”，或执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_public.ps1
```

启动器在后台管理三个独立进程：127.0.0.1:8503 的 Streamlit 公网实例、该实例的提醒工作进程和 Cloudflare Quick Tunnel。窗口会显示 HTTPS 地址并打开登录页；重复启动会复用仍在运行的入口。现有 8502 本机工作台继续运行。

公网账号、家庭、对话、提醒、监控和补充参考库保存在被 Git 忽略的 `runtime/public/`，不复制本机已有用户数据。首次访问公网入口需要重新注册。疾病知识库及 BGE 权重继续使用本机已经准备的资料；API 由服务端读取 `config/api.local.toml`，不会公开上传。公网访客无法编辑模型服务地址、查看全站监控、启用开发数据或上传共享索引资料。

公网模型调用额外受持久化每日预留额度控制，默认全站 2,000,000 token、每账号 200,000 token；可用 `MEDICAL_PUBLIC_DAILY_TOKENS` 和 `MEDICAL_PUBLIC_USER_TOKENS` 在启动前调整。预留额度是上界，失败也保留预留，不能用新建对话重置每日限制。既有单请求/会话/分钟限制仍生效。

停止时双击“停止公网入口.cmd”，或执行 `stop_public.ps1`。只关闭已核验的公网进程，保留数据和本机 8502 服务。当前公网地址保存在 `runtime/public/hosting.json`；重建隧道后域名会变化。电脑关机、休眠或网络断开时入口无法使用；这不是长期托管。

Quick Tunnel 是临时演示服务，没有可用性保证，最多 200 个并发请求；固定域名与长期服务需要命名隧道或云服务器。Streamlit 浏览器通信使用 WebSocket；服务端到模型供应商的 SSE 不经过访客隧道。来源：[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。

### 常规 Python 环境

建议使用 Python 3.13。在项目根目录建立虚拟环境并安装依赖：

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
```

将 `config/api.example.toml` 复制为 `config/api.local.toml`，按自己的服务商配置。也可使用 `MEDICAL_LLM_BASE_URL`、`MEDICAL_LLM_MODEL`、`MEDICAL_LLM_API_KEY` 等环境变量。完整说明见根目录的 API 配置文档。未填写时可以登录、管理家庭与历史记录；真实 API 功能不会返回模拟模型答案。

Windows 双击“启动医知协作.cmd”，会检查启动网页、提醒服务并打开登录页。跨平台网页命令：

```bash
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

## 模型和资料准备

仓库不分发原始医疗数据、模型权重或训练产物。医疗检索、问诊检索和生成评估依赖这些资源，只有源码无法完成对应推理。

准备自己有权使用的疾病数据（原始 JSONL 格式，文件名 `medical*.json`）、检索训练问句（`bert_retrieval_samples*.jsonl`）和 BGE 基础模型资源。当前检索实现针对本项目的 8808 条记录和 512 维向量验收，替换成不同规模的语料时需同步调整检索器的规模校验与数据字段。

```bash
python medical_retrieval.py --mode train --run-name check_full_1031 --steps 50 --logging-steps 5
python publish_index.py
```

也可以从自己的备份恢复：

```text
runs/check_full_1031/model/             # BGE 权重、配置与 tokenizer
runs/check_full_1031/evaluation.json
runs/check_full_1031/loss_curve.png
runs/check_full_1031/full.db/           # 训练索引目录
runtime/index_manifest.json           # 可选，已发布索引清单
runtime/index_*.db/                    # 对应索引目录
```

上述文件不应混入 Git 提交。不要把已有用户的 runtime 目录公开上传作为演示数据。

## 提醒进程与外网访问

`reminder_worker.py` 当前使用 Windows `msvcrt` 文件锁；Windows 启动器会在后台管理它。在 Linux 上不能直接宣称提醒工作进程已兼容，需要改成平台适用的单实例锁并用进程管理器运行。网页打开期间有定时任务的限频回退调度，不能替代常驻提醒服务。

对外部署时由服务器管理者配置 HTTPS、域名、备份、进程重启和访问策略。浏览器相机跨设备访问需要安全上下文；当前没有接入穿戴设备或手机系统推送。代码仓库本身不会完成这些外部服务配置。

## 离线验证

不需要真实 API、模型权重或医疗语料：

```bash
mkdir -p runtime
python -m unittest test_accounts test_family test_family_extensions test_identity_product test_conversations
python -m unittest test_llm_engineering test_vision_monitor test_project_completion
```

`test_*pages.py` 是 Streamlit 页面交互测试；`verify_project.py` 还需要真实本地数据、权重与索引。离线 HTTP 响应使用明确的合成测试数据，不代表供应商连通或医学质量验证。
