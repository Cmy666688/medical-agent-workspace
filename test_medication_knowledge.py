"""Synthetic contracts for source matching; not clinical efficacy/safety tests."""
import asyncio,hashlib,json,os,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='medication_test_runtime_',dir='runtime')
os.environ['MEDICAL_API_CONFIG']=str(Path(os.environ['MEDICAL_RUNTIME_DIR'])/'absent.toml')
from agents.drug_data import build,canonical,norm
from agents.medication_knowledge import DrugKnowledge

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(tempfile.mkdtemp(prefix='medication_fixture_',dir='runtime'))
        cls.source=cls.root/'source';cls.source.mkdir();manifest=[]
        def save(name,raw):
            path=cls.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            manifest.append(dict(path=name,url='https://synthetic.test/'+name,sha256=hashlib.sha256(raw).hexdigest()))
        def zipped(name,rows):
            path=cls.root/'temp.zip'
            with zipfile.ZipFile(path,'w') as z: z.writestr('fixture.json',json.dumps(rows,ensure_ascii=False))
            save(name,path.read_bytes())
        def row(key,name,component,cancelled=''):
            return {'許可證字號':key,'中文品名':name,'英文品名':key,'主成分略述':component,'劑型':'测试剂型','有效日期':'2035/01/01','註銷狀態':cancelled}
        products=[row('TEST-1','測試甲錠','METFORMIN HCL'),row('TEST-2','測試乙錠','CIMETIDINE'),row('TEST-C','測試復方錠','METFORMIN HCL;;CIMETIDINE'),row('TEST-OLD','歷史測試錠','METFORMIN HCL','已註銷'),row('TEST-X','同名測試','METFORMIN HCL'),row('TEST-Y','同名測試','CIMETIDINE')]
        zipped('tfda/drug_licenses.json.zip',products)
        zipped('tfda/labels_and_packages.json.zip',[{'許可證字號':'TEST-1','仿單圖檔連結':'https://www.fda.gov.tw/fixture.pdf'}])
        zipped('tfda/appearance.json.zip',[])
        save('ddinter2/code_A.csv',b'DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\na,Metformin,b,Cimetidine,Moderate\na,Metformin,c,TestDrug,Unknown\n')
        save('openfda/fixture.json',json.dumps(dict(results=[dict(id='synthetic-label',set_id='synthetic-set',openfda=dict(generic_name=['METFORMIN HYDROCHLORIDE'],route=['ORAL']),effective_time='20260101',warnings=['SYNTHETIC fixture text; not a clinical instruction.'])])).encode())
        (cls.source/'manifest.json').write_text(json.dumps(dict(retrieved_at='2026-11-01',files=manifest)),encoding='utf-8')
        cls.path=cls.root/'knowledge.sqlite';build(cls.source,cls.path);cls.service=DrugKnowledge(cls.path)
    def test_precise_matching_and_source_citation(self):
        value=self.service.check('二甲双胍\n西咪替丁','无已知过敏')
        self.assertEqual(value['interactions'][0]['records'][0]['level'],'Moderate')
        self.assertEqual(value['items'][0]['components'],['metformin'])
        self.assertEqual(len(value['items'][0]['labels']),1)
        self.assertTrue(any(e['doc_id'].startswith('ddinter:') for e in value['drug_evidences']))
        self.assertTrue(any(e['doc_id'].startswith('openfda:') for e in value['drug_evidences']))
    def test_simplified_product_lookup_and_compound_expansion(self):
        value=self.service.check('测试复方锭')
        self.assertEqual(value['items'][0]['status'],'product')
        self.assertEqual(value['items'][0]['components'],['cimetidine','metformin'])
        self.assertFalse(value['items'][0]['labels']) # Do not substitute a single-ingredient label.
    def test_ambiguous_names_are_not_resolved(self):
        value=self.service.check('同名测试\n西咪替丁')
        self.assertEqual(value['items'][0]['status'],'ambiguous')
        self.assertEqual(value['interactions'][0]['status'],'unresolved')
    def test_unknown_not_covered_and_duplicate(self):
        self.assertEqual(self.service.check('二甲双胍\n完全未知')['interactions'][0]['status'],'unresolved')
        self.assertEqual(self.service.check('二甲双胍\nTestDrug')['interactions'][0]['records'][0]['level'],'Unknown')
        self.assertTrue(self.service.check('二甲双胍\nMetformin')['duplicates'])
    def test_cancelled_license_is_preserved_as_history(self):
        row=self.service.check('TEST-OLD')['items'][0]['products'][0]
        self.assertIn('已标注销',row['registry_status'])
    def test_no_fuzzy_auto_match_or_route_merging(self):
        self.assertNotEqual(canonical('Insulin (human)'),canonical('Insulin (pork)'))
        self.assertNotEqual(canonical('Drug (topical)'),canonical('Drug (systemic)'))
        self.assertEqual(self.service.check('二甲双胍500mg')['items'][0]['status'],'not_found')
        self.assertEqual(self.service.check("%' OR 1=1 --")['items'][0]['status'],'not_found')
    def test_missing_index_and_no_medication(self):
        self.assertEqual(DrugKnowledge(self.root/'absent.sqlite').check('测试')['knowledge_status'],'not_installed')
        self.assertTrue(self.service.check('未用药')['no_medications_reported'])
    def test_coordinator_medication_review_uses_drug_sources(self):
        from agents.coordinator import Coordinator
        from agents.llm import LLMConfig,ConsultationSummary,EvidenceSummary
        from agents.specialists import SpecialistReview
        from langchain_core.chat_history import InMemoryChatMessageHistory
        seen=[]
        class Search:
            def search(self,q): return dict(evidences=[dict(doc_id='disease-source',name='测试疾病百科',content='合成疾病资料')],cache_hit=False,latency_ms=1)
        async def fake(system,payload,schema,*args,**kw):
            if schema is ConsultationSummary: return ConsultationSummary(chief_complaint='测试',symptoms=[],followup=[])
            if schema is SpecialistReview:
                evidence=payload['evidence']
                if args[-1]=='用药复核 Agent':
                    seen.extend(row['doc_id'] for row in evidence)
                    self.assertTrue(evidence)
                    self.assertTrue(all(row['doc_id'].startswith(('ddinter:','openfda:')) for row in evidence))
                return SpecialistReview(summary='合成复核',source_ids=[row['doc_id'] for row in evidence][:1],followup=[],limitations=[])
            return EvidenceSummary(summary='合成摘要',source_ids=['disease-source'],limitations=[])
        async def run():
            with patch.dict(os.environ,MEDICAL_DRUG_DB=str(self.path)),patch('agents.coordinator.LLMClient.structured',side_effect=fake):
                result=await Coordinator(Search()).run('资料查询',dict(medications='二甲双胍\n西咪替丁',allergies='不清楚'),InMemoryChatMessageHistory(),'synthetic-medication-review',LLMConfig(api_key='synthetic',enable_specialist_review=True))
            self.assertTrue(seen)
            self.assertEqual(next(row for row in result['trace'] if row['agent']=='用药复核 Agent')['status'],'完成')
        asyncio.run(run())
    def test_source_corruption_does_not_replace_working_index(self):
        path=self.source/'ddinter2/code_A.csv';original=path.read_bytes();path.write_bytes(b'corrupt')
        try:
            with self.assertRaisesRegex(ValueError,'校验失败'): build(self.source,self.path)
            self.assertTrue(self.service.info()['ready'])
        finally: path.write_bytes(original)
    def test_medication_page_outputs_readable_results(self):
        from streamlit.testing.v1 import AppTest
        from agents import accounts
        with patch.dict(os.environ,MEDICAL_DRUG_DB=str(self.path)):
            app=AppTest.from_file('app.py',default_timeout=40)
            app.session_state.personal_token=accounts.register('medication_page','Test-password-123','用药页面验证')['token']
            app.session_state.api_key=''
            app.run();app.switch_page('app_pages/agent_medication.py').run()
            app.form('medication_test').text_area[0].set_value('二甲双胍\n西咪替丁')
            app.form('medication_test').form_submit_button[0].click().run()
            self.assertFalse(app.exception,[e.message for e in app.exception])
            self.assertTrue(any('Moderate' in x.value for x in app.warning))
            self.assertTrue(any('openFDA 标签参考' in x.label for x in app.expander))
            self.assertFalse(app.json)

if __name__=='__main__': unittest.main(verbosity=2)
