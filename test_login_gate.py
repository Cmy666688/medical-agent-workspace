"""Require a valid registered account before registering or executing feature pages."""
import os
import tempfile
from unittest.mock import patch

os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='login_gate_',dir='runtime')
from streamlit.testing.v1 import AppTest
from agents import accounts,family,telemetry

protected=['home','knowledge','agent_consultation','agent_retrieval','agent_medication',
           'agent_risk','agent_education','family_home','agent_family','agent_care',
           'agent_schedule','monitor','evaluation']

def only_account(app):
    assert not app.exception,[x.message for x in app.exception]
    assert len(app.chat_input)==0
    assert len(app.get('file_uploader'))==0
    assert len(app.get('page_link'))==0
    for name in protected:
        try: app.switch_page('app_pages/'+name+'.py')
        except ValueError: pass
        else: raise AssertionError('Unauthenticated page registered: '+name)

with patch.object(telemetry,'bind_user',side_effect=AssertionError('Guest bound to private telemetry')):
    guest=AppTest.from_file('app.py',default_timeout=40).run()
    only_account(guest)
    assert guest.form('account_auth')

# A member credential or an old unregistered identity cannot unlock the workspace.
legacy=family.create_identity('旧身份')
member=family.create_family('旧家庭','成员',legacy)
guest.session_state.family_token=member['token']
guest.session_state.user_id='member_forged'
guest.run(); only_account(guest)
guest.session_state.personal_token=legacy
guest.run(); only_account(guest)
assert guest.form('upgrade_account')

# Login opens the same routes, and logout/expiration blocks an already selected deep page.
result=accounts.register('gate_user','Gate-password-123','验证用户')
app=AppTest.from_file('app.py',default_timeout=40)
app.session_state.personal_token=result['token']
app.run()
app.switch_page('app_pages/agent_education.py').run()
assert any(x.value=='资料解读 Agent' for x in app.title)
accounts.logout(result['token'])
app.run(); only_account(app)
assert app.form('account_auth')
assert 'personal_token' not in app.session_state

# A fabricated token is rejected at the shared entry point.
app.session_state.personal_token='session_invalid'
app.run(); only_account(app)
assert app.form('account_auth')
print('All 13 feature routes require registration and a valid login; legacy and revoked sessions blocked')
