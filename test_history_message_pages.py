import os,tempfile,uuid
from pathlib import Path
from unittest.mock import patch
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='history_pages_',dir='runtime')
os.environ['MEDICAL_API_CONFIG']=str(Path(os.environ['MEDICAL_RUNTIME_DIR'])/'no_api.toml')
from streamlit.testing.v1 import AppTest
from agents import accounts,family,conversations

owner=accounts.register('family_owner','History-password-123','创建人')['token']
first=accounts.register('family_one','History-password-123','家人')['token']
second=accounts.register('family_two','History-password-123','家人')['token']
group=family.create_family('私信验证家庭','创建人',owner)
member1=family.join_family(group['invite'],'家人',first)['token']
member2=family.join_family(group['invite'],'家人',second)['token']
person1=family.profile(member1); person2=family.profile(member2)
app=AppTest.from_file('app.py',default_timeout=40)
app.session_state.personal_token=first
app.run(); app.switch_page('app_pages/agent_consultation.py').run()
old=app.session_state.conversation_id
app.number_input(key='consultation_context_age').set_value(44).run()
async def fake(*args,**kwargs):
    return dict(request=uuid.uuid4().hex,answer='测试回复',trace=[],evidences=[],conflicts=[])
with patch('agents.coordinator.Coordinator.run',side_effect=fake),patch('ui.retrieval',return_value=object()):
    app.chat_input[0].set_value('我的旧对话').run()
assert not app.exception,[x.message for x in app.exception]
next(x for x in app.button if x.label=='开始新对话').click().run()
assert not app.exception,[x.message for x in app.exception]
assert app.session_state.conversation_id!=old and not app.session_state.turns
assert conversations.load(first,old)['turns'][0]['question']=='我的旧对话'
app.switch_page('app_pages/conversations.py').run()
next(x for x in app.button if x.key=='continue_'+old).click().run()
assert not app.exception,[x.message for x in app.exception]
assert app.session_state.turns[0]['question']=='我的旧对话'
assert len(app.session_state.history.messages)==2
assert app.number_input(key='consultation_context_age').value==44
app.switch_page('app_pages/home.py').run()
app.switch_page('app_pages/agent_consultation.py').run()
assert app.number_input(key='consultation_context_age').value==44
fresh=AppTest.from_file('app.py',default_timeout=40)
fresh.session_state.personal_token=accounts.login('family_one','History-password-123')
fresh.run(); fresh.switch_page('app_pages/conversations.py').run()
assert any(x.value=='我的旧对话' for x in fresh.subheader)

app.switch_page('app_pages/agent_family.py').run()
app.segmented_control(key='message_mode_'+person1['id']).set_value('指定成员私信').run()
selector=app.selectbox(key='message_recipient_'+person1['id'])
selector.set_value(person2['id']).run()
app.form('family_message').text_area[0].set_value('仅给指定家人的留言')
app.form('family_message').form_submit_button[0].click().run()
assert not app.exception,[x.message for x in app.exception]
assert family.messages(member2)[0]['body']=='仅给指定家人的留言'
assert family.messages(member1)[0]['recipient']==person2['id']
assert not family.messages(group['token'])
app.switch_page('app_pages/conversations.py').run()
app.form('rename_'+old).text_input[0].set_value('重命名后的问诊')
app.form('rename_'+old).form_submit_button[0].click().run()
assert any(item['title']=='重命名后的问诊' for item in conversations.listing(first))
other_id=next(item['id'] for item in conversations.listing(first) if item['id']!=old)
app.checkbox(key='confirm_delete_'+other_id).check().run()
next(x for x in app.button if x.key=='delete_'+other_id).click().run()
assert not app.exception,[x.message for x in app.exception]
assert conversations.exists(first,old) and not conversations.exists(first,other_id)
try: family.send_message(member1,'不能误发','')
except ValueError: pass
else: raise AssertionError('Empty recipient became public')
print('Durable history, switching/reconnect and named private messages passed')
