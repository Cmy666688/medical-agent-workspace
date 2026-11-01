"""Readable evaluation views preserve missing/failed scores and report coverage."""
import copy,os,tempfile
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='evaluation_ui_',dir='runtime')
from streamlit.testing.v1 import AppTest
from agents import accounts
from evaluation_ui import report_markdown,details

report={'created_at':'2026-11-01T02:24:24+00:00','sample_count':3,
        'recall':{'Recall@1':2/3,'Recall@5':1.,'Recall@10':1.},
        'generation_evaluated':0,'generation_failed':0,'generation_metrics':None,
        'rows':[{'query':question,'rank':rank,'generation_status':'skipped_no_key'} for question,rank in [('测试问题一',3),('测试问题二',1),('测试问题三',1)]]}
app=AppTest.from_file('app.py',default_timeout=40)
app.session_state.personal_token=accounts.register('evaluation_user','Evaluation-password-123','评估验证')['token']
app.session_state.quality_report=copy.deepcopy(report)
app.run(); app.switch_page('app_pages/evaluation.py').run()
assert not app.exception,[x.message for x in app.exception]
assert not app.json
assert any(x.label=='前 1 条命中率' and x.value=='66.7%' for x in app.metric)
assert any('未配置模型 API 密钥' in x.value for x in app.warning)
assert not any(x.label=='忠实性通过率' for x in app.metric)
assert details(report)[0]['生成评估']=='未配置密钥，已跳过'
assert 'skipped_no_key' not in report_markdown(report)
assert '没有可用的生成质量分数' in report_markdown(report)

partial=copy.deepcopy(report)
partial.update(generation_evaluated=1,generation_failed=1,generation_metrics={'faithful':1.,'relevance':.8,'reference_alignment':.6})
partial['rows'][0].update(generation_status='evaluated',judgment={'faithful':True,'relevance':.8,'reference_alignment':.6,'unsupported_claims':[]})
partial['rows'][1].update(generation_status='failed',error='timeout',rank=None)
app.session_state.quality_report=partial
app.run()
assert not app.exception,[x.message for x in app.exception]
assert any(x.label=='平均切题度' and x.value=='80.0%' for x in app.metric)
assert any('1/3' in x.value and '失败 1 条' in x.value for x in app.info)
assert '模型响应超时' in report_markdown(partial)
assert details(partial)[1]['目标资料排名']=='前 10 条未命中'
assert not app.json
app.session_state.developer_mode=True
app.run()
assert len(app.json)==1
print('Readable skipped/partial evaluation results, exports and opt-in JSON passed')
