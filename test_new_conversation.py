import os,tempfile
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='new_chat_',dir='runtime')
from streamlit.testing.v1 import AppTest
from agents import accounts

app=AppTest.from_file('app.py',default_timeout=40)
token=accounts.register('new_chat_user','New-chat-password-123','新对话验证')['token']
app.session_state.personal_token=token
app.run()
app.switch_page('app_pages/evaluation.py').run()
app.session_state.api_key='synthetic-key'
app.session_state.llm_model='configured-id'
previous=app.session_state.session_id
app.session_state.turns=[{'request':'old_request','question':'旧问题','answer':'旧回复','trace':[],'evidences':[],'conflicts':[]}]
next(x for x in app.button if x.label=='开始新对话').click().run()
assert not app.exception,[x.message for x in app.exception]
assert len(app.chat_input)==1
assert app.session_state.session_id!=previous
assert app.session_state.turns==[]
from agents import conversations
assert any(x['title']=='旧问题' for x in conversations.listing(token))
assert app.session_state.history.messages==[]
assert app.session_state.personal_token==token
assert app.session_state.api_key=='synthetic-key'
assert app.session_state.llm_model=='configured-id'
app.switch_page('app_pages/evaluation.py').run()
app.segmented_control[0].set_value('项目说明').run()
assert not app.exception
assert not any('尚未完成说明书' in x.value for x in app.warning)
assert not app.dataframe
print('New conversation resets context, opens consultation and preserves account/configuration')
