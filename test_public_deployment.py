"""Public profile policy and limits; no real API calls or local user records."""
import os,tempfile,unittest,uuid
from unittest.mock import patch
from pathlib import Path
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='public_policy_test_',dir='runtime')
os.environ['MEDICAL_API_CONFIG']=str(Path(os.environ['MEDICAL_RUNTIME_DIR'])/'absent.toml')
from agents import accounts
from agents.telemetry import bind_user
from agents.llm import LLMConfig,LLMError,reserve
from streamlit.testing.v1 import AppTest

class Tests(unittest.TestCase):
    def test_public_navigation_hides_management_and_shared_uploads(self):
        with patch.dict(os.environ,MEDICAL_PUBLIC_MODE='1'):
            app=AppTest.from_file('app.py',default_timeout=40)
            app.session_state.personal_token=accounts.register('public_test','Public-password-123','公网测试')['token']
            app.session_state.developer_mode=True
            app.run()
            self.assertFalse(app.exception,[e.message for e in app.exception])
            self.assertFalse(app.session_state.developer_mode)
            self.assertFalse(any(x.label=='查看运行记录' for x in app.get('page_link')))
            for page in ('monitor','evaluation'):
                with self.assertRaises(ValueError): app.switch_page('app_pages/'+page+'.py')
            app.switch_page('app_pages/knowledge.py').run()
            self.assertFalse(app.exception,[e.message for e in app.exception])
            self.assertFalse(app.get('file_uploader'))
    def test_public_config_cannot_redirect_server_credentials(self):
        import streamlit as st
        from ui import llm_config
        with patch.dict(os.environ,MEDICAL_PUBLIC_MODE='1'),patch('api_config.configured_values',return_value=dict(base_url='https://intended.test',model='intended',api_key='synthetic')):
            with patch.object(st,'session_state',dict(base_url='https://untrusted.test',api_key='visitor',llm_model='other')):
                config=llm_config()
                self.assertEqual(config.base_url,'https://intended.test')
                self.assertEqual(config.api_key,'synthetic')
    def test_daily_account_quota_survives_new_conversations(self):
        one=uuid.uuid4().hex; two=uuid.uuid4().hex; identity=uuid.uuid4().hex
        bind_user(one,identity);bind_user(two,identity)
        with patch.dict(os.environ,MEDICAL_PUBLIC_MODE='1',MEDICAL_PUBLIC_USER_TOKENS='10',MEDICAL_PUBLIC_DAILY_TOKENS='1000'):
            reserve(one,8,LLMConfig())
            with self.assertRaisesRegex(LLMError,'public_daily_budget'): reserve(two,3,LLMConfig())
    def test_global_daily_quota_applies_to_different_accounts(self):
        session=uuid.uuid4().hex; bind_user(session,uuid.uuid4().hex)
        with patch.dict(os.environ,MEDICAL_PUBLIC_MODE='1',MEDICAL_PUBLIC_USER_TOKENS='1000',MEDICAL_PUBLIC_DAILY_TOKENS='1'):
            with self.assertRaisesRegex(LLMError,'public_daily_budget'): reserve(session,2,LLMConfig())

if __name__=='__main__': unittest.main(verbosity=2)
