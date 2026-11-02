"""Public project management uses verified administrator roles."""
import os,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
Path('runtime').mkdir(exist_ok=True)
runtime=Path(tempfile.mkdtemp(prefix='public_management_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'no-api.toml')
from agents import accounts,user_management
from streamlit.testing.v1 import AppTest

class Tests(unittest.TestCase):
    def setUp(self):
        name='admin_'+uuid.uuid4().hex[:8]
        self.admin=accounts.register(name,'Public-admin-test-123','管理员')['token']
        user_management.bootstrap_admin(name)
        self.user=accounts.register('user_'+uuid.uuid4().hex[:8],'Public-admin-test-123','普通用户')['token']

    def test_public_admin_can_open_both_management_pages(self):
        with patch.dict(os.environ,MEDICAL_PUBLIC_MODE='1'):
            app=AppTest.from_file('app.py',default_timeout=30)
            app.session_state.personal_token=self.admin
            app.run()
            for page in ('monitor','evaluation'):
                app.switch_page('app_pages/'+page+'.py').run()
                self.assertFalse(app.exception,[w.message for w in app.exception])
            next(w for w in app.get('segmented_control') if w.label=='查看内容').set_value('模型接口').run()
            key=next(w for w in app.text_input if w.label=='API key')
            self.assertEqual(key.value,'')
            next(w for w in app.text_input if w.label=='API base URL（以 /v1 等接口前缀结束）').set_value('https://synthetic.test/v1')
            next(w for w in app.text_input if w.label=='文本模型 ID').set_value('synthetic-model')
            key.set_value('synthetic-secret')
            next(w for w in app.button if w.label=='应用配置').click().run()
            self.assertFalse(app.exception,[w.message for w in app.exception])
            self.assertEqual(app.session_state.llm_model,'synthetic-model')
            self.assertTrue(any('配置已应用' in w.value for w in app.success))

    def test_ordinary_user_denied_by_navigation_and_direct_guard(self):
        with patch.dict(os.environ,MEDICAL_PUBLIC_MODE='1'):
            app=AppTest.from_file('app.py',default_timeout=30)
            app.session_state.personal_token=self.user
            app.run()
            for page in ('monitor','evaluation'):
                with self.assertRaises(ValueError):app.switch_page('app_pages/'+page+'.py')
                direct=AppTest.from_file('app_pages/'+page+'.py')
                direct.session_state.personal_token=self.user
                direct.run()
                self.assertFalse(direct.exception,[w.message for w in direct.exception])
                self.assertTrue(any('仅管理员' in w.value for w in direct.error))

    def test_only_public_admin_receives_session_overrides(self):
        script='import streamlit as st\nfrom ui import llm_config\nst.text(llm_config().model)'
        with patch.dict(os.environ,MEDICAL_PUBLIC_MODE='1'),patch('api_config.configured_values',return_value=dict(model='server-model')):
            for token,expected in [(self.admin,'admin-model'),(self.user,'server-model')]:
                app=AppTest.from_string(script)
                app.session_state.personal_token=token;app.session_state.llm_model='admin-model'
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(app.text[0].value,expected)

if __name__=='__main__':unittest.main(verbosity=2)
