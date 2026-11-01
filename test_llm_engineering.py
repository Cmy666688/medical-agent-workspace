"""离线 HTTP 契约测试：不向真实供应商发请求，不作为医学质量评估。"""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import uuid
from pathlib import Path
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='llm_test_',dir='runtime')
import httpx
from agents.llm import LLMClient, LLMConfig, LLMError, ConsultationSummary, quota_usage
from agents.coordinator import Coordinator
from langchain_core.chat_history import InMemoryChatMessageHistory

VALID={'chief_complaint':'鼻痒','symptoms':['鼻痒'],'followup':['持续多久？']}
def success():
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(VALID,ensure_ascii=False)}}],'usage':{'prompt_tokens':100,'completion_tokens':20}})

class Tests(unittest.IsolatedAsyncioTestCase):
    def config(self,**kw):
        return LLMConfig(base_url='https://primary.test/v1',model='test-model',api_key='not-a-real-key',**kw)
    async def call(self,handler,config=None,**kw):
        return await LLMClient(config or self.config(),httpx.MockTransport(handler),retry_delay=0).structured('提取症状',{'question':'鼻痒'},ConsultationSummary,kw.pop('session',uuid.uuid4().hex),'test-request','test-agent',**kw)
    async def test_structured_success(self):
        value=await self.call(lambda req:success())
        self.assertEqual(value.symptoms,['鼻痒'])
    async def test_official_deepseek_structured_disables_thinking(self):
        def handler(req):
            body=json.loads(req.content)
            self.assertEqual(body['thinking'],{'type':'disabled'})
            self.assertEqual(body['max_tokens'],2048)
            return success()
        await self.call(handler,LLMConfig(base_url='https://api.deepseek.com/v1',model='deepseek-flash',api_key='synthetic',response_format='json_object'))
    async def test_other_gateway_has_no_provider_specific_fields(self):
        def handler(req):
            self.assertNotIn('thinking',json.loads(req.content))
            return success()
        await self.call(handler)
    async def test_truncated_output_retries_with_budget_and_no_reasoning_leak(self):
        from agents.telemetry import events
        attempts=[]; session=uuid.uuid4().hex
        def handler(req):
            attempts.append(json.loads(req.content))
            if len(attempts)==1:
                return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'','reasoning_content':'PRIVATE REASONING'}}],'usage':{'completion_tokens':700}})
            return success()
        await self.call(handler,session=session)
        self.assertEqual([x['max_tokens'] for x in attempts],[2048,4096])
        self.assertGreater(quota_usage(session),2048+4096)
        failures=[e for e in events(kind='failure') if e['session']==session]
        self.assertEqual(failures[0]['error'],'output_truncated')
        self.assertEqual(failures[0]['finish_reason'],'length')
        self.assertNotIn('PRIVATE REASONING',json.dumps(failures))
    async def test_recovery_cannot_bypass_request_budget(self):
        attempts=[]
        def handler(req):
            attempts.append(req)
            return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':''}}]})
        with self.assertRaisesRegex(LLMError,'budget_overflow'):
            await self.call(handler,self.config(budget_tokens=4000))
        self.assertEqual(len(attempts),1)
    async def test_blank_json_response_retries_once(self):
        attempts=[]
        def handler(req):
            attempts.append(req)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'   '}}]})
        with self.assertRaisesRegex(LLMError,'empty_response'): await self.call(handler)
        self.assertEqual(len(attempts),2)
    async def test_refusal_is_not_retried(self):
        attempts=[]
        def handler(req):
            attempts.append(req)
            return httpx.Response(200,json={'choices':[{'finish_reason':'content_filter','message':{'content':''}}]})
        with self.assertRaisesRegex(LLMError,'model_refusal'): await self.call(handler)
        self.assertEqual(len(attempts),1)
    async def test_complete_fenced_json_is_validated(self):
        value=await self.call(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'```json\n'+json.dumps(VALID)+'\n```'}}]}))
        self.assertEqual(value.chief_complaint,'鼻痒')
    async def test_sse_truncation_is_not_accepted_as_complete(self):
        attempts=[]
        def handler(req):
            attempts.append(req)
            reason='length' if len(attempts)==1 else 'stop'
            wire='data: '+json.dumps({'choices':[{'delta':{'content':json.dumps(VALID)},'finish_reason':reason}]})+'\n\ndata: [DONE]\n\n'
            return httpx.Response(200,text=wire)
        await self.call(handler,stream=True)
        self.assertEqual(len(attempts),2)
    async def test_retry_429(self):
        attempts=[]
        def handler(req):
            attempts.append(req)
            return httpx.Response(429) if len(attempts)<3 else success()
        await self.call(handler)
        self.assertEqual(len(attempts),3)
    async def test_primary_failure_fallback(self):
        hosts=[]
        def handler(req):
            hosts.append(req.url.host)
            return httpx.Response(503) if req.url.host=='primary.test' else success()
        await self.call(handler,self.config(fallback_url='https://backup.test/v1',fallback_key='fake',fallback_model='backup'))
        self.assertEqual(hosts,['primary.test']*3+['backup.test'])
    async def test_no_retry_on_auth_error(self):
        attempts=[]
        def handler(req): attempts.append(req); return httpx.Response(401)
        with self.assertRaisesRegex(LLMError,'http_error'): await self.call(handler)
        self.assertEqual(len(attempts),1)
    async def test_invalid_schema(self):
        def handler(req): return httpx.Response(200,json={'choices':[{'message':{'content':'{"symptoms":42}'}}]})
        with self.assertRaisesRegex(LLMError,'parse_failure'): await self.call(handler)
    async def test_streaming_sse(self):
        text=json.dumps(VALID,ensure_ascii=False)
        events=[{'choices':[{'delta':{'content':text[:15]}}]},{'choices':[{'delta':{'content':text[15:]}}]},{'choices':[],'usage':{'prompt_tokens':100,'completion_tokens':20}}]
        wire=''.join('data: '+json.dumps(x,ensure_ascii=False)+'\n\n' for x in events)+'data: [DONE]\n\n'
        deltas=[]
        value=await self.call(lambda req:httpx.Response(200,text=wire),stream=True,on_delta=deltas.append)
        self.assertEqual(value.chief_complaint,'鼻痒'); self.assertEqual(''.join(deltas),text)
    async def test_timeout(self):
        attempts=[]
        def handler(req): attempts.append(req); raise httpx.ReadTimeout('test',request=req)
        with self.assertRaisesRegex(LLMError,'timeout'): await self.call(handler)
        self.assertEqual(len(attempts),3)
    async def test_pre_request_budget(self):
        def forbidden(req): self.fail('必须在发出网络请求前阻断')
        with self.assertRaisesRegex(LLMError,'budget_overflow'): await self.call(forbidden,self.config(budget_tokens=1))
    async def test_session_quota(self):
        with self.assertRaisesRegex(LLMError,'session_budget_overflow'): await self.call(lambda req:success(),self.config(session_tokens=1))
    async def test_rate_limit_and_persisted_usage(self):
        session=uuid.uuid4().hex; cfg=self.config(calls_per_minute=1)
        await self.call(lambda req:success(),cfg,session=session)
        self.assertGreater(quota_usage(session),0)
        with self.assertRaisesRegex(LLMError,'local_rate_limit'): await self.call(lambda req:success(),cfg,session=session)
    async def test_empty_stream(self):
        with self.assertRaisesRegex(LLMError,'empty_response'): await self.call(lambda req:httpx.Response(200,text='data: [DONE]\n\n'),stream=True)
    async def test_network_error(self):
        def handler(req): raise httpx.ConnectError('offline',request=req)
        with self.assertRaisesRegex(LLMError,'network_error'): await self.call(handler)
    async def test_coordinator_urgent_skips_llm(self):
        with patch('agents.coordinator.LLMClient.structured',side_effect=AssertionError('危险信号不应调用 LLM')):
            value=await Coordinator(None).run('胸口压榨伴大汗',{},InMemoryChatMessageHistory(),'test-urgent',self.config())
        self.assertTrue(value['conflicts'])
    async def test_coordinator_two_structured_agents(self):
        class Search:
            def search(self,q): return dict(evidences=[dict(doc_id='test-record',name='测试资料',content='测试内容')],cache_hit=False,latency_ms=1)
        def handler(req):
            body=json.loads(req.content)
            if body['response_format']['json_schema']['name']=='ConsultationSummary': return success()
            content=json.dumps(dict(summary='测试摘要',source_ids=['test-record'],limitations=['测试数据']))
            return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+'\n\ndata: [DONE]\n\n')
        client=LLMClient(self.config(),httpx.MockTransport(handler),retry_delay=0)
        with patch('agents.coordinator.LLMClient',return_value=client):
            value=await Coordinator(Search()).run('鼻痒',{},InMemoryChatMessageHistory(),uuid.uuid4().hex,self.config())
        self.assertIn('测试摘要',value['answer'])
        self.assertEqual(value['trace'][0]['output']['mode'],'在线 LLM 结构化信息整理')
    async def test_reject_invented_source(self):
        from agents.llm import EvidenceSummary
        class Search:
            def search(self,q): return dict(evidences=[dict(doc_id='real',name='测试',content='测试内容')],cache_hit=False,latency_ms=1)
        async def fake(*args,**kwargs):
            return ConsultationSummary(**VALID) if args[2] is ConsultationSummary else EvidenceSummary(summary='不能显示的摘要',source_ids=['invented'],limitations=[])
        with patch('agents.coordinator.LLMClient.structured',side_effect=fake):
            value=await Coordinator(Search()).run('鼻痒',{},InMemoryChatMessageHistory(),uuid.uuid4().hex,self.config())
        self.assertNotIn('不能显示的摘要',value['answer'])
        self.assertTrue(any(t['error']=='invalid_citation' for t in value['trace']))

if __name__=='__main__': unittest.main(verbosity=2)
