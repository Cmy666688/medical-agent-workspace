"""统一问诊入口、其他 Agent 功能及真实会话状态展示。"""
import os,tempfile
from pathlib import Path
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='agent_ui_test_',dir='runtime')
from streamlit.testing.v1 import AppTest
from agent_ui import AGENTS
from agents import accounts

app=AppTest.from_file('app.py',default_timeout=30)
app.session_state.personal_token=accounts.register('agent_test','Agent-password-123','功能验证用户')['token']
app.session_state.api_key=''
app.session_state.risk_include_references=False
app.run()
assert not app.exception
assert sum(x.label=='打开功能' for x in app.get('page_link'))==5
for name in ['consultation','retrieval','medication','risk']:
    app.switch_page('app_pages/agent_'+name+'.py').run()
    assert not app.exception,[e.message for e in app.exception]
    if name=='consultation':
        assert len(app.chat_input)==1
        assert len(app.get('file_uploader'))==1
        assert any(x.value=='问诊 Agent' for x in app.title)
    elif name!='retrieval':
        app.form_submit_button[0].click().run()
        assert not app.exception,[e.message for e in app.exception]
        assert app.session_state.agent_tests[name]['status']=='完成'
app.switch_page('app_pages/agent_education.py').run()
assert not app.exception,[e.message for e in app.exception]
app.segmented_control[0].set_value('粘贴资料').run()
app.text_area[0].set_value('这是资料整理功能的测试正文。').run()
next(x for x in app.button if x.label=='整理资料与来源').click().run()
assert not app.exception
assert app.session_state.agent_tests['education']['output']['points'][0]['excerpt']=='这是资料整理功能的测试正文。'
app.session_state.risk_include_references=False
app.switch_page('app_pages/agent_risk.py').run()
app.text_area[0].set_value('胸口压榨伴大汗')
app.form_submit_button[0].click().run()
assert app.session_state.agent_tests['risk']['output']['red_flags']
app.session_state['turns']=[dict(trace=[dict(agent='风险评估 Agent',status='完成',duration_ms=1,output={},error=''),dict(agent='用药 Agent',status='跳过',duration_ms=0,output={},error='')])]
app.switch_page('app_pages/home.py').run()
assert not app.exception
assert any('orange-badge[跳过]' in x.value for x in app.markdown)
print('Agent 页面验证通过')
