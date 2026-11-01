import asyncio,os,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
runtime=Path(tempfile.mkdtemp(prefix='risk_results_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'absent.toml')
from agents.risk_workflow import information,assess
from agents.coordinator import RiskAgent,Coordinator
from agents.llm import LLMConfig,LLMError,EvidenceSummary
from langchain_core.chat_history import InMemoryChatMessageHistory
from agents.specialists import SpecialistReview
from agents import accounts
from streamlit.testing.v1 import AppTest

QUESTION='鼻子痒，没有明显的胸痛，无呼吸困难，持续两周了，不是很严重，无伴随症状'
EVIDENCE=dict(doc_id='synthetic-source',name='测试参考资料',content='仅用于验证检索链路的测试正文',score=.8,source='synthetic',symptoms=[])

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
    async def test_urgent_alert_precedes_lazy_retrieval_and_other_agents_continue(self):
        timeline=[]
        class Search:
            def search(self,q):
                timeline.append('search')
                return dict(evidences=[dict(EVIDENCE)],latency_ms=1,cache_hit=False)
        def factory():
            timeline.append('load-resource')
            return Search()
        def notify(event):
            if event.get('output',{}).get('red_flags'): timeline.append('alert')
        result=await Coordinator(factory).run('胸痛一周，不适程度适中',{'medications':'未用药','allergies':'无已知过敏'},InMemoryChatMessageHistory(),'urgent-with-references',on_event=notify)
        self.assertLess(timeline.index('alert'),timeline.index('load-resource'))
        self.assertLess(timeline.index('load-resource'),timeline.index('search'))
        rows={x['agent']:x for x in result['trace']}
        for name in ('风险评估 Agent','检索 Agent','用药 Agent','资料解读 Agent'): self.assertEqual(rows[name]['status'],'完成')
        self.assertEqual(rows['风险评估 Agent']['output']['evidences'][0]['doc_id'],'synthetic-source')
        self.assertTrue(result['answer'].startswith(rows['风险评估 Agent']['output']['recommendation']))
        self.assertIn('测试参考资料',result['answer'])
        self.assertNotIn('中止检索','；'.join(result['conflicts']))
    async def test_urgent_can_continue_online_source_summary(self):
        class Search:
            def search(self,q): return dict(evidences=[dict(EVIDENCE)],latency_ms=1,cache_hit=False)
        async def fake(system,payload,schema,*args,**kw):
            self.assertTrue(payload.get('risk_alert',payload.get('consultation',{}).get('risk_alert'))['red_flags'])
            if schema is SpecialistReview: return SpecialistReview(summary='测试复核',source_ids=['synthetic-source'],followup=[],limitations=[])
            self.assertIs(schema,EvidenceSummary)
            return EvidenceSummary(summary='测试在线资料整理',source_ids=['synthetic-source'],limitations=[])
        with patch('agents.coordinator.LLMClient.structured',side_effect=fake):
            result=await Coordinator(Search()).run('胸痛一周',{},InMemoryChatMessageHistory(),'urgent-online',LLMConfig(api_key='synthetic',enable_specialist_review=True))
        self.assertIn('测试在线资料整理',result['answer'])
        self.assertTrue(all(x['status']=='完成' for x in result['trace']))
    async def test_retrieval_failure_does_not_discard_risk_or_medication(self):
        class Search:
            def search(self,q): raise RuntimeError('synthetic-unavailable')
        result=await Coordinator(Search()).run('胸痛一周',{},InMemoryChatMessageHistory(),'urgent-search-failure')
        rows={x['agent']:x for x in result['trace']}
        self.assertEqual(rows['风险评估 Agent']['status'],'完成')
        self.assertEqual(rows['用药 Agent']['status'],'完成')
        self.assertEqual(rows['检索 Agent']['status'],'失败')
        self.assertTrue(result['answer'].startswith(rows['风险评估 Agent']['output']['recommendation']))
    async def test_independent_urgent_still_retrieves_after_alert(self):
        timeline=[]
        class Search:
            def search(self,q):
                timeline.append('search')
                return dict(evidences=[dict(EVIDENCE)],latency_ms=1,cache_hit=False)
        def notify(event): timeline.append('alert')
        result=await assess('胸痛一周',LLMConfig(),'independent-urgent',retrieval=Search(),on_event=notify)
        self.assertEqual(timeline,['alert','search'])
        self.assertEqual(result.output['retrieval_status'],'completed')
        self.assertIn('medication_check',result.output)
        self.assertEqual(result.output['evidences'][0]['doc_id'],'synthetic-source')
    def test_risk_page_displays_consultation_record_without_loading_search(self):
        result=asyncio.run(Coordinator(lambda:None).run('胸痛一周',{},InMemoryChatMessageHistory(),'linked-record'))
        risk=next(row for row in result['trace'] if row['agent']=='风险评估 Agent')
        risk['output'].update(evidences=[dict(EVIDENCE)],retrieval_status='completed')
        result['evidences']=[dict(EVIDENCE)]
        app=AppTest.from_file('app.py',default_timeout=40)
        app.session_state.personal_token=accounts.register('linked_risk','Risk-password-123','关联结果验证')['token']
        app.session_state.api_key=''
        app.run()
        app.session_state.turns=[dict(question='胸痛一周',**result)]
        with patch('ui.retrieval',side_effect=AssertionError('Navigation must not load retrieval resources')):
            app.switch_page('app_pages/agent_risk.py').run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertTrue(any(x.label=='最近问诊的风险评估与相关资料' for x in app.expander))
        self.assertTrue(any('测试参考资料' in x.label for x in app.expander))
        self.assertTrue(any('出现危险信号' in x.value for x in app.warning))
        self.assertFalse(app.json)
    def test_consultation_page_keeps_urgent_reference_results_after_rerun(self):
        class Search:
            def search(self,q): return dict(evidences=[dict(EVIDENCE)],latency_ms=1,cache_hit=False)
        app=AppTest.from_file('app.py',default_timeout=40)
        app.session_state.personal_token=accounts.register('urgent_chat','Risk-password-123','问诊结果验证')['token']
        app.session_state.api_key=''
        app.run();app.switch_page('app_pages/agent_consultation.py').run()
        with patch('ui.retrieval',return_value=Search()):
            app.chat_input[0].set_value('胸痛一周').run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        turn=app.session_state.turns[-1]
        self.assertTrue(turn['evidences'])
        self.assertTrue(next(row for row in turn['trace'] if row['agent']=='风险评估 Agent')['output']['red_flags'])
        self.assertTrue(all(row['status']=='完成' for row in turn['trace']))
        app.switch_page('app_pages/agent_risk.py').run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertTrue(any('测试参考资料' in x.label for x in app.expander))
    def test_page_displays_submission_and_distinguishes_online_failure(self):
        app=AppTest.from_file('app.py',default_timeout=40)
        app.session_state.personal_token=accounts.register('risk_user','Risk-password-123','风险结果验证')['token']
        app.session_state.api_key=''
        app.session_state.risk_include_references=False
        app.run();app.switch_page('app_pages/agent_risk.py').run()
        app.form('risk_test').text_area[0].set_value(QUESTION)
        app.form('risk_test').form_submit_button[0].click().run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertEqual(app.session_state.agent_tests['risk']['status'],'完成',app.session_state.agent_tests['risk'])
        self.assertIn('input_snapshot',app.session_state.agent_tests['risk']['output'],app.session_state.agent_tests['risk'])
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
