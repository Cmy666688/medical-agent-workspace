"""Two users register, join the same family and reconnect without sharing login state."""
import os
import tempfile
from unittest.mock import patch

os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='account_pages_',dir='runtime')
from streamlit.testing.v1 import AppTest
from agents import family,accounts

def signup(username,display):
    app=AppTest.from_file('app.py',default_timeout=40).run()
    app.segmented_control(key='auth_mode').set_value('注册').run()
    for widget,value in zip(app.form('account_auth').text_input,[username,display,'Account-password-123','Account-password-123']): widget.set_value(value)
    with patch('streamlit.commands.navigation.send_page_not_found',side_effect=AssertionError('Login navigation showed a missing-page dialog')):
        app.form('account_auth').form_submit_button[0].click().run()
    assert not app.exception,[x.message for x in app.exception]
    assert not app.error,[x.value for x in app.error]
    return app

owner=signup('family_owner','爸爸')
owner.switch_page('app_pages/family_home.py').run()
owner.form('family_membership').text_input[0].set_value('账号验证家庭')
owner.form('family_membership').form_submit_button[0].click().run()
assert not owner.exception
invite=owner.session_state.new_family_credentials['invite']
child=signup('family_child','子女')
child.switch_page('app_pages/family_home.py').run()
assert not family.my_families(child.session_state.personal_token)
child.segmented_control[0].set_value('加入家庭').run()
child.form('family_membership').text_input[0].set_value(invite)
child.form('family_membership').form_submit_button[0].click().run()
assert not child.exception,[x.message for x in child.exception]
assert len(family.my_families(child.session_state.personal_token))==1
child.switch_page('app_pages/agent_care.py').run()
assert not child.exception
assert len(family.members(child.session_state.family_token))==2
owner_id=family.profile(owner.session_state.family_token)['id']
try: family.health_records(child.session_state.family_token,owner_id)
except PermissionError: pass
else: raise AssertionError('Joining automatically granted access')

# Logout also invalidates any saved browser token and clears private model credentials.
previous=child.session_state.personal_token
child.session_state.api_key='synthetic-private-key'
child.switch_page('app_pages/account.py').run()
next(x for x in child.button if x.label=='退出登录').click().run()
assert not child.exception
assert 'api_key' not in child.session_state
try: family.identity_profile(previous)
except PermissionError: pass
else: raise AssertionError('Logout token still active')

child.form('account_auth').text_input[0].set_value('family_child')
child.form('account_auth').text_input[1].set_value('Account-password-123')
child.form('account_auth').form_submit_button[0].click().run()
child.switch_page('app_pages/family_home.py').run()
assert any(x.value=='账号验证家庭' for x in child.subheader)
assert not child.exception

# A remembered session reaches the same restoration callback used by the browser.
import identity_ui
import streamlit as st
saved=accounts.login('family_child','Account-password-123',remember=True)
original_bootstrap=identity_ui.bootstrap_identity
def simulate_browser_restore():
    st.session_state.identity_storage={'token':saved}
    identity_ui._restore()
    return original_bootstrap()
with patch('identity_ui.bootstrap_identity',side_effect=simulate_browser_restore):
    fresh=AppTest.from_file('app.py').run()
fresh.switch_page('app_pages/family_home.py').run()
assert not fresh.exception
assert any(x.value=='账号验证家庭' for x in fresh.subheader)
print('Account registration, family invitations, logout and session restoration passed')
