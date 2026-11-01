"""集成验证：真实检索、多轮上下文、风险中断、缓存、页面交互。"""
import asyncio
import json
import os
import tempfile
import shutil
from pathlib import Path
Path('runtime').mkdir(exist_ok=True)
verification_runtime=Path(tempfile.mkdtemp(prefix='verify_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(verification_runtime)
# Exercise the published index, rather than loading the older two-collection training DB.
published_manifest=Path('runtime/index_manifest.json')
if published_manifest.exists():
    published=json.loads(published_manifest.read_text(encoding='utf-8'))
    shutil.copytree(published_manifest.parent/published['database'],verification_runtime/published['database'])
    shutil.copy2(published_manifest,verification_runtime/published_manifest.name)
from langchain_core.chat_history import InMemoryChatMessageHistory
from agents.coordinator import Coordinator, LLMConfig
from agents.retrieval import RetrievalService
from streamlit.testing.v1 import AppTest
from agents import accounts

def main():
    service=RetrievalService()
    first=service.search('花粉季鼻子发痒、喷嚏不断，想看变应性鼻炎的介绍')
    second=service.search('花粉季鼻子发痒、喷嚏不断，想看变应性鼻炎的介绍')
    assert first['evidences'] and second['cache_hit']
    assert any(x['name']=='过敏性鼻炎' for x in first['evidences'])
    assert not service.search('测试无命中分支',threshold=1.0)['evidences']
    history=InMemoryChatMessageHistory(); coordinator=Coordinator(service)
    result=asyncio.run(coordinator.run('鼻子发痒打喷嚏三天，查过敏性鼻炎',dict(allergies='无',medications='无'),history,'integration_test'))
    assert result['evidences'] and len(history.messages)==2
    follow=asyncio.run(coordinator.run('还伴有咳嗽',dict(allergies='无',medications='无'),history,'integration_test'))
    assert follow['trace'][0]['output']['history_turns']==1
    emergency=asyncio.run(coordinator.run('胸口压榨样疼痛伴大汗放射左臂',{},InMemoryChatMessageHistory(),'integration_test'))
    assert emergency['conflicts'] and not emergency['evidences'] and '120' in emergency['answer']
    negative=asyncio.run(coordinator.run('鼻子痒，没有胸痛，无呼吸困难',{},InMemoryChatMessageHistory(),'integration_test'))
    assert not negative['conflicts']
    budget=asyncio.run(coordinator.run('查过敏性鼻炎',{},InMemoryChatMessageHistory(),'integration_test',LLMConfig(api_key='test',budget_tokens=1)))
    assert any(x['error']=='budget_overflow' for x in budget['trace'])
    import ui
    ui.retrieval=lambda: service
    app=AppTest.from_file('app.py',default_timeout=90)
    app.session_state.personal_token=accounts.register('integration_user','Integration-password-123','集成验证用户')['token']
    app.run()
    assert not app.exception
    app.switch_page('app_pages/agent_consultation.py').run(timeout=90)
    app.chat_input[0].set_value('查过敏性鼻炎，鼻痒三天').run(timeout=90)
    assert not app.exception and app.session_state.turns
    assert len(app.json)==0
    assert {'问诊 Agent','风险评估 Agent','检索 Agent','用药 Agent','资料解读 Agent'}.issubset({row['agent'] for row in app.session_state.turns[-1]['trace']})
    app.switch_page('app_pages/home.py').run()
    app.switch_page('app_pages/agent_consultation.py').run()
    assert len(app.session_state.turns)==1
    app.chat_input[0].set_value('还伴有咳嗽').run(timeout=90)
    assert not app.exception and len(app.session_state.turns)==2
    assert app.session_state.turns[-1]['trace'][0]['output']['history_turns']==1
    for page in ['knowledge','monitor','evaluation']:
        app.switch_page('app_pages/'+page+'.py').run(timeout=90)
        assert not app.exception, [x.message for x in app.exception]
        if page=='knowledge':
            app.text_input[0].set_value('过敏性鼻炎')
            app.form_submit_button[0].click().run(timeout=90)
            assert not app.exception
        if page=='evaluation':
            app.segmented_control[0].set_value('模型接口').run()
            assert not app.exception
    from ui import document_jobs
    import time
    jobs=document_jobs()
    jobs.submit('软件索引验收参考.md',[(1,'软件索引验收参考：这是验证软件文档增量索引功能的原文，不提供医疗建议。')])
    deadline=time.monotonic()+40
    while time.monotonic()<deadline and jobs.jobs()[0]['status'] not in ('completed','failed'): time.sleep(.1)
    assert jobs.jobs()[0]['status']=='completed',jobs.jobs()[0]
    custom=service.search('软件索引验收参考.md',5,0.)
    assert any(row['name']=='软件索引验收参考.md' and row['page']==1 for row in custom['evidences'])
    report=dict(status='passed',checks=['真实 Milvus 混合检索','缓存命中','无命中分支','多轮历史','危险信号中断','否定症状','LLM 预算阻断','问诊提交','知识库查询','监控页面','评估与设置页面','真实 BGE 后台文档索引与页码回查'],records=service.count,dimension=service.dimension)
    Path('runtime/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    service.client.close()
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
