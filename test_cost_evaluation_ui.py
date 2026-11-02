"""No fabricated costs; keep single-query regressions visible beside aggregate gains."""
import os,tempfile,unittest,uuid
from pathlib import Path
Path('runtime').mkdir(exist_ok=True)
runtime=Path(tempfile.mkdtemp(prefix='cost_eval_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'no-api.toml')
from agents.costs import cost_summary
from agents.llm import LLMConfig
from agents import accounts,user_management,telemetry
from streamlit.testing.v1 import AppTest


class Tests(unittest.TestCase):
    def test_missing_rates_and_usage_do_not_become_zero_cost(self):
        cfg=LLMConfig(model='current')
        result=cost_summary([dict(model='current',provider='primary',input_tokens=100,output_tokens=20,cost=None),dict(model='current',cost=None)],cfg)
        self.assertEqual(result['missing_price'],1);self.assertEqual(result['missing_usage'],1)
        self.assertEqual(result['totals'],{})
        zero=cost_summary([dict(cost=0.0,price_currency='USD')],cfg)
        self.assertEqual(zero['recorded'],1);self.assertEqual(zero['totals'],{'USD':0.0})

    def test_historical_estimation_matches_model_and_keeps_currencies_separate(self):
        cfg=LLMConfig(model='current',input_price=.3,output_price=1.2,price_currency='USD')
        rows=[dict(model='current',provider='primary',input_tokens=1000,output_tokens=100,cost=None),
              dict(model='other',provider='primary',input_tokens=1000,output_tokens=100,cost=None),
              dict(cost=2,price_currency='CNY'),dict(input_tokens=float('nan'),cost=None)]
        result=cost_summary(rows,cfg)
        self.assertEqual(result['historical'],1)
        self.assertAlmostEqual(result['totals']['USD'],.00042)
        self.assertEqual(result['totals']['CNY'],2)
        self.assertIsNone(rows[0]['cost'])
        self.assertEqual(result['missing_price'],1);self.assertEqual(result['missing_usage'],1)

    def test_original_regressing_example_is_not_replaced_by_success_case(self):
        script='''
from retrieval_evaluation_ui import render_retrieval_comparison
render_retrieval_comparison(dict(before={'Recall@1':.29,'Recall@5':.58,'Recall@10':.83},after={'Recall@1':.5,'Recall@5':.83,'Recall@10':.92},selected_before={'query':'合成问题','rank':2,'top10':[]},selected_after={'query':'合成问题','rank':3,'top10':[]}))
'''
        app=AppTest.from_string(script).run()
        self.assertFalse(app.exception,[w.message for w in app.exception])
        self.assertTrue(any('退步 1 位' in w.value for w in app.warning))
        self.assertTrue(any(w.label=='微调后目标排名' and w.value=='3' for w in app.metric))

    def test_monitor_with_unpriced_calls_shows_reason(self):
        name='cost_admin_'+uuid.uuid4().hex[:8]
        token=accounts.register(name,'Cost-admin-test-123','计价测试')['token']
        user_management.bootstrap_admin(name)
        session=uuid.uuid4().hex
        telemetry.record(session,'cost-1','llm',model='current',provider='primary',input_tokens=100,output_tokens=20,cost=None)
        app=AppTest.from_file('app.py',default_timeout=30)
        app.session_state.personal_token=token
        app.run();app.switch_page('app_pages/monitor.py').run()
        self.assertFalse(app.exception,[w.message for w in app.exception])
        self.assertFalse(any(w.value=='未计价 / 无调用' for w in app.metric))
        self.assertTrue(any('适用单价' in w.value for w in app.info))


if __name__=='__main__':unittest.main(verbosity=2)
