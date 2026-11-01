import os,tempfile
from pathlib import Path
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='family_product_',dir='runtime')
from streamlit.testing.v1 import AppTest
from agents import family as f

app=AppTest.from_file('app.py',default_timeout=40).run()
app.segmented_control(key='auth_mode').set_value('注册').run()
for field,value in zip(app.form('account_auth').text_input,['page_user','验证用户','Page-password-123','Page-password-123']): field.set_value(value)
app.form('account_auth').form_submit_button[0].click().run()
assert not app.exception,[x.message for x in app.exception]
personal=app.session_state.personal_token
app.switch_page('app_pages/family_home.py').run()
app.form('family_membership').text_input[0].set_value('验证家庭')
app.form('family_membership').form_submit_button[0].click().run()
assert not app.exception,[x.message for x in app.exception]
assert len(f.my_families(personal))==1
member=app.session_state.family_token
app.switch_page('app_pages/agent_schedule.py').run()
app.form('create_schedule').text_input[0].set_value('测量血压提醒')
app.form('create_schedule').form_submit_button[0].click().run()
assert not app.exception,[x.message for x in app.exception]
app.switch_page('app_pages/agent_care.py').run()
app.form('health_record').form_submit_button[0].click().run()
assert not app.exception,[x.message for x in app.exception]
assert len(f.health_records(member,f.profile(member)['id']))==1
app.switch_page('app_pages/agent_family.py').run()
app.form('family_message').text_area[0].set_value('已完成测量')
app.form('family_message').form_submit_button[0].click().run()
assert not app.exception
assert f.messages(member)[0]['body']=='已完成测量'
fresh=AppTest.from_file('app.py',default_timeout=40).run()
fresh.form('account_auth').text_input[0].set_value('page_user')
fresh.form('account_auth').text_input[1].set_value('Page-password-123')
fresh.form('account_auth').form_submit_button[0].click().run()
fresh.switch_page('app_pages/family_home.py').run()
assert not fresh.exception,[x.message for x in fresh.exception]
assert any('验证家庭' in x.value for x in fresh.subheader)
for name in ('agent_medication','agent_consultation'):
    fresh.switch_page('app_pages/'+name+'.py').run()
    assert len(fresh.get('file_uploader'))==1
    if name=='agent_medication': fresh.form_submit_button[0].click().run()
    else: assert len(fresh.chat_input)==1
    assert not fresh.exception,[x.message for x in fresh.exception]
    assert len(fresh.json)==0
fresh.switch_page('app_pages/account.py').run()
next(x for x in fresh.button if x.label=='退出登录').click().run()
assert not fresh.exception,[x.message for x in fresh.exception]
assert fresh.session_state.turns==[]
assert len(fresh.chat_input)==0
assert fresh.form('account_auth')
print('家庭身份恢复、家庭操作、嵌入识图与中文结果验证通过')
