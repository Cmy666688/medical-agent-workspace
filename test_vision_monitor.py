import os,tempfile,io,json,uuid,unittest
from unittest.mock import patch
from pathlib import Path
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='feature_test_',dir='runtime')
import httpx
from PIL import Image
from agents.vision import prepare_image,VisionAgent
from agents.llm import LLMClient,LLMConfig
from agents.telemetry import bind_user,record,events,feedback_stats
from agents.quality import evaluate_quality

def image_bytes():
    image=Image.new('RGB',(800,600),'white'); stream=io.BytesIO(); image.save(stream,format='PNG'); return stream.getvalue()

class Tests(unittest.IsolatedAsyncioTestCase):
    def test_preprocess(self):
        result=prepare_image(image_bytes()); self.assertEqual(result['processed_size'],[512,384]); self.assertTrue(result['data_uri'].startswith('data:image/jpeg;base64,'))
    def test_invalid_image(self):
        with self.assertRaises(ValueError): prepare_image(b'not an image')
        with self.assertRaises(ValueError): prepare_image(b'a'*(10*1024*1024+1))
    async def test_vision_no_key(self):
        value=await VisionAgent(LLMConfig()).run(image_bytes(),'描述',uuid.uuid4().hex)
        self.assertEqual(value['error'],'vision_not_configured'); self.assertFalse(value['output'])
    async def test_multimodal_and_private_log(self):
        session=uuid.uuid4().hex
        expected=dict(description='白色矩形',visible_features=['白色'],text_in_image=[],image_quality='清晰',limitations=['测试图片'],followup_questions=[])
        def handler(req):
            body=json.loads(req.content); content=body['messages'][1]['content']
            self.assertEqual(content[1]['type'],'image_url'); self.assertEqual(body['model'],'vision-test')
            self.assertTrue(content[1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            return httpx.Response(200,json=dict(choices=[dict(message=dict(content=json.dumps(expected)))],usage=dict(prompt_tokens=100,completion_tokens=30)))
        factory=lambda cfg:LLMClient(cfg,httpx.MockTransport(handler),retry_delay=0)
        cfg=LLMConfig(base_url='https://fake.test/v1',model='text',api_key='fake',vision_model='vision-test')
        value=await VisionAgent(cfg,factory).run(image_bytes(),'描述',session)
        self.assertEqual(value['status'],'完成')
        logs=json.dumps([r for r in events() if r['session']==session]); self.assertNotIn('base64',logs); self.assertNotIn('白色矩形',logs)
    def test_user_and_feedback(self):
        session=uuid.uuid4().hex; bind_user(session,'user_A')
        record(session,'r1','request'); record(session,'r2','request')
        record(session,'r1','feedback',positive=True); record(session,'r2','feedback',positive=False)
        rows=[r for r in events() if r['session']==session]
        self.assertTrue(all(r['user_id']=='user_A' for r in rows))
        self.assertEqual(feedback_stats(rows),dict(count=2,positive=1,negative=1,coverage=1))
        record(session,'r1','feedback',positive=None)
        self.assertEqual(feedback_stats([r for r in events() if r['session']==session]),dict(count=1,positive=0,negative=1,coverage=.5))
    async def test_quality_without_key_has_no_fake_generation_score(self):
        class Search:
            by_id={'real':{'desc':'疾病简介'}}
            def search(self,*args): return dict(evidences=[dict(doc_id='real',name='测试资料',content='疾病简介')])
        value=await evaluate_quality(Search(),[dict(query='测试',positive_doc_id='real')],LLMConfig(),'test')
        self.assertEqual(value['recall']['Recall@1'],1)
        self.assertIsNone(value['generation_metrics']); self.assertEqual(value['generation_evaluated'],0)
    async def test_quality_generation_and_judge(self):
        class Search:
            by_id={'real':{'desc':'参考疾病简介'}}
            def search(self,*args): return dict(evidences=[dict(doc_id='real',name='测试资料',content='疾病简介')])
        def handler(req):
            name=json.loads(req.content)['response_format']['json_schema']['name']
            output=dict(summary='测试摘要',source_ids=['real'],limitations=[]) if name=='EvidenceSummary' else dict(faithful=True,relevance=.8,reference_alignment=.7,unsupported_claims=[])
            return httpx.Response(200,json=dict(choices=[dict(message=dict(content=json.dumps(output)))]))
        cfg=LLMConfig(base_url='https://fake.test',model='fake',api_key='fake')
        with patch('agents.quality.LLMClient',return_value=LLMClient(cfg,httpx.MockTransport(handler))):
            result=await evaluate_quality(Search(),[dict(query='测试',positive_doc_id='real')],cfg,uuid.uuid4().hex)
        self.assertEqual(result['generation_evaluated'],1)
        self.assertEqual(result['generation_metrics']['reference_alignment'],.7)

if __name__=='__main__': unittest.main(verbosity=2)
