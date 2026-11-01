import asyncio,os,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
runtime=Path(tempfile.mkdtemp(prefix='risk_results_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'absent.toml')
from agents.risk_workflow import information,assess
from agents.coordinator import RiskAgent
from agents.llm import LLMConfig,LLMError
from agents.specialists import SpecialistReview
from agents import accounts
from streamlit.testing.v1 import AppTest

QUESTION='鼻子痒，没有明显的胸痛，无呼吸困难，持续两周了，不是很严重，无伴随症状'

class Tests(unittest.IsolatedAsyncioTestCase):
    def test_existing_information_not_asked_again(self):
        result=RiskAgent().execute({'query':QUESTION})
        self.assertFalse(result['red_flags'])
        self.assertEqual(result['followup'],[])
        self.assertEqual(result['reported_symptoms'],['鼻痒'])
        self.assertIn('胸痛',result['denied_symptoms'])
        self.assertTrue(any('两周' in value for value in result['provided_info']))
        self.assertTrue(any('不是很严重' in value for value in result['provided_info']))
    def test_urgent_and_double_negation(self):
        self.assertTrue(RiskAgent().execute({'query':'没有发热，但胸口压榨伴大汗'})['red_flags'])
        self.assertTrue(RiskAgent().execute({'query':'不是没有胸痛'})['red_flags'])
    async def test_local_result_has_explicit_mode(self):
        result=await assess(QUESTION,LLMConfig(),'test-risk')
        self.assertEqual(result.output['online_status'],'not_configured')
        self.assertEqual(result.output['input_snapshot'],QUESTION)
    async def test_online_review_is_used(self):
        class Client:
            def __init__(self,cfg): pass
            async def structured(self,*args,**kwargs):
                return SpecialistReview(summary='已收到两周持续时间和程度描述，需补充既往情况。',source_ids=[],followup=['是否有既往相关情况？'],limitations=['仅整理信息'])
        result=await assess(QUESTION,LLMConfig(api_key='synthetic'),'test-risk',Client)
        self.assertEqual(result.output['online_status'],'completed')
        self.assertIn('两周',result.output['model_review']['summary'])
    async def test_timeout_keeps_local_result(self):
        class Client:
            def __init__(self,cfg): pass
            async def structured(self,*args,**kwargs): raise LLMError('timeout')
        result=await assess(QUESTION,LLMConfig(api_key='synthetic'),'test-risk',Client)
        self.assertEqual(result.status,'完成')
        self.assertEqual(result.output['online_status'],'failed')
        self.assertEqual(result.output['review_error'],'timeout')
        self.assertTrue(result.output['provided_info'])
    async def test_urgent_does_not_wait_for_model(self):
        def forbidden(cfg): self.fail('Urgent rule must not wait for remote service')
        result=await assess('胸口压榨伴大汗',LLMConfig(api_key='synthetic'),'test-risk',forbidden)
        self.assertEqual(result.output['online_status'],'skipped_urgent')
    def test_page_displays_submission_and_distinguishes_online_failure(self):
        app=AppTest.from_file('app.py',default_timeout=40)
        app.session_state.personal_token=accounts.register('risk_user','Risk-password-123','风险结果验证')['token']
        app.session_state.api_key=''
        app.run();app.switch_page('app_pages/agent_risk.py').run()
        app.form('risk_test').text_area[0].set_value(QUESTION)
        app.form('risk_test').form_submit_button[0].click().run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertEqual(app.session_state.agent_tests['risk']['output']['input_snapshot'],QUESTION)
        self.assertTrue(any('两周' in x.value for x in app.markdown))
        self.assertFalse(any('最近一次协作结果'==x.label for x in app.expander))
        self.assertFalse(app.json)
        result=asyncio.run(assess(QUESTION,LLMConfig(),'test-ui-local'))
        result.output.update(online_status='failed',review_error='output_truncated')
        with patch('agents.risk_workflow.assess',return_value=result):
            app.form('risk_test').form_submit_button[0].click().run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertTrue(any('本地检查已完成；在线复核失败' in x.value for x in app.warning))
        self.assertFalse(app.success)
        self.assertTrue(any('输出长度上限' in x.value for x in app.warning))
        result.output.update(online_status='completed',model_review=dict(summary='格式验证完成',followup=[],limitations=[]))
        with patch('agents.risk_workflow.assess',return_value=result):
            app.form('risk_test').form_submit_button[0].click().run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertTrue(any('本地检查和在线复核均已完成' in x.value for x in app.success))
        self.assertTrue(any('格式验证完成' in x.value for x in app.markdown))

if __name__=='__main__': unittest.main(verbosity=2)
