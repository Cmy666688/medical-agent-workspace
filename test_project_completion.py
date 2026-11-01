import asyncio,copy,json,os,tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='completion_',dir='runtime')
from agents.lexical import KeywordIndex,fuse
from agents.documents import DocumentStore,IndexJobs,split_text,read_upload
from agents.llm import LLMConfig,LLMClient,ConsultationSummary,LLMError
from agents.specialists import rerank,Ranking,SpecialistReview
from agents import accounts
from streamlit.testing.v1 import AppTest
from api_config import file_config,configured_values
import httpx

class Tests(unittest.TestCase):
    def test_chunk_overlap_and_validation(self):
        text='abcdefghijklmno'; parts=split_text(text,6,2)
        self.assertEqual(parts[:2],['abcdef','efghij'])
        with self.assertRaises(ValueError): split_text(text,5,5)
        self.assertEqual(read_upload('参考资料'.encode(),'guide.md'),[(None,'参考资料')])
        with self.assertRaises(ValueError): read_upload(b'abc','guide.exe')
    def test_keyword_and_fusion(self):
        rows=[{'_id':{'$oid':'a'},'name':'鼻炎','desc':'鼻塞流涕'},{'_id':{'$oid':'b'},'name':'胃炎','desc':'胃痛'}]
        self.assertEqual(KeywordIndex(rows).search('查鼻炎')[0],'a')
        self.assertEqual(fuse(['a','b'],['b','a'])[0],'a')
    def test_atomic_document_update_and_queue(self):
        store=DocumentStore(Path(os.environ['MEDICAL_RUNTIME_DIR'])/(uuid.uuid4().hex+'.sqlite'))
        class Service:
            def embed_texts(self,texts): return [[1.,0.] for _ in texts]
        jobs=IndexJobs(lambda:Service(),store)
        key=jobs.submit('guide.txt',[(1,'资料原文'*180)])
        deadline=time.monotonic()+8
        while time.monotonic()<deadline and jobs.jobs()[0]['status'] not in ('completed','failed'): time.sleep(.05)
        self.assertEqual(jobs.jobs()[0]['status'],'completed')
        self.assertEqual(jobs.submit('guide.txt',[(1,'资料原文'*180)]),key)
        found=store.search([1.,0.],5,.5)
        self.assertIn('第 1 页',found[0]['source'])
        store.publish('guide.txt','new',[(2,'新的原文')],[[0.,1.]])
        self.assertFalse(store.search([1.,0.],5,.5))
        self.assertEqual(store.info()['chunks'],1)
        self.assertIn('第 2 页',store.search([0.,1.],1,.5)[0]['source'])
        with self.assertRaises(ValueError): store.publish('guide.txt','bad',[(None,'无效')],[[float('nan'),0.]])
        self.assertEqual(store.info()['chunks'],1)
    def test_private_config_and_env_override(self):
        path=Path(os.environ['MEDICAL_RUNTIME_DIR'])/'api.toml'
        path.write_text('[llm]\nmodel="text-id"\napi_key="test-only"\nvision_model="vision-id"\n',encoding='utf-8')
        with patch.dict(os.environ,{'MEDICAL_API_CONFIG':str(path),'MEDICAL_LLM_MODEL':'override'}):
            self.assertEqual(file_config()['model'],'text-id')
            self.assertEqual(configured_values()['model'],'override')
    def test_json_mode_validation(self):
        async def run():
            def handler(request):
                body=json.loads(request.content); self.assertEqual(body['response_format'],{'type':'json_object'})
                self.assertIn('JSON Schema',body['messages'][0]['content'])
                return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'chief_complaint':'测试','symptoms':[],'followup':[]})}}]})
            client=LLMClient(LLMConfig(base_url='https://example.test/v1',api_key='fake',model='test',response_format='json_object'),httpx.MockTransport(handler))
            result=await client.structured('测试',{},ConsultationSummary,uuid.uuid4().hex,'r','test')
            self.assertEqual(result.chief_complaint,'测试')
        asyncio.run(run())
    def test_rerank_rejects_unknown_sources(self):
        async def run():
            class Client:
                async def structured(self,*args,**kwargs): return Ranking(ordered_source_ids=['invented'])
            with self.assertRaises(LLMError): await rerank(Client(),'问句',[{'doc_id':'real','name':'资料','content':'正文'}],'s','r')
        asyncio.run(run())
    def test_full_specialist_chain_and_progress(self):
        from agents.coordinator import Coordinator
        from agents.llm import EvidenceSummary
        from langchain_core.chat_history import InMemoryChatMessageHistory
        class Search:
            def search(self,query):
                return dict(evidences=[dict(doc_id=key,name='测试资料',content='测试原文') for key in ['one','two']],cache_hit=False,latency_ms=1)
        async def fake(system,payload,schema,*args,**kwargs):
            if schema is ConsultationSummary: return ConsultationSummary(chief_complaint='测试',symptoms=[],followup=[])
            if schema is Ranking: return Ranking(ordered_source_ids=['two','one'])
            if schema is SpecialistReview: return SpecialistReview(summary='仅为测试复核',source_ids=[row['doc_id'] for row in payload.get('evidence',[])][:1],followup=['请补充'],limitations=['测试内容'])
            return EvidenceSummary(summary='测试汇总',source_ids=['two'],limitations=[])
        async def run():
            events=[]
            cfg=LLMConfig(api_key='fake',enable_rerank=True,enable_specialist_review=True)
            with patch('agents.coordinator.LLMClient.structured',side_effect=fake):
                result=await Coordinator(Search()).run('资料查询',{},InMemoryChatMessageHistory(),'specialist-test',cfg,on_event=events.append)
            self.assertEqual(result['evidences'][0]['doc_id'],'two')
            self.assertTrue({'风险复核 Agent','用药复核 Agent','检索重排 Agent'}.issubset({row['agent'] for row in result['trace']}))
            self.assertTrue(all(row['status']=='完成' for row in result['trace']))
            self.assertTrue(any(row['status']=='执行中' for row in events))
        asyncio.run(run())

if __name__=='__main__': unittest.main(verbosity=2)
