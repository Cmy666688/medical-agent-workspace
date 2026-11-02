"""Real progress, replay, missing timing and the actual Streamlit page."""
import asyncio
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

Path('runtime').mkdir(exist_ok=True)
runtime=Path(tempfile.mkdtemp(prefix='timeline_test_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'no-api.toml')
from execution_timeline import TimelineState,duration_label
from agents.coordinator import Coordinator
from agents.llm import LLMConfig
from agents import accounts
from langchain_core.chat_history import InMemoryChatMessageHistory
from streamlit.testing.v1 import AppTest


class Search:
    def search(self, query):
        return dict(evidences=[dict(doc_id='timeline-source',name='流程测试资料',content='人工构造的测试记录，不作医学判断。')],cache_hit=False,latency_ms=12.5)


class Tests(unittest.TestCase):
    def test_terminal_replay_and_repeated_completion_do_not_duplicate(self):
        timeline=TimelineState()
        timeline.update(dict(agent='检索 Agent',status='执行中'))
        timeline.update(dict(agent='检索 Agent',status='完成',duration_ms=12.5))
        timeline.update(dict(agent='检索 Agent',status='完成',duration_ms=12.5))
        timeline.update(dict(agent='检索 Agent',status='执行中'))
        self.assertEqual(len(timeline.rows()),1)
        self.assertEqual(timeline.rows()[0]['status'],'完成')
        self.assertEqual(timeline.rows()[0]['duration_ms'],12.5)

    def test_no_fake_timing_and_failed_running_nodes(self):
        self.assertEqual(duration_label(None),'耗时未记录')
        self.assertEqual(duration_label(float('nan')),'耗时未记录')
        self.assertEqual(duration_label(-1),'耗时未记录')
        self.assertEqual(duration_label(.2),'<1 ms')
        self.assertEqual(duration_label(1250),'1.25 s')
        timeline=TimelineState()
        timeline.update(dict(agent='问诊 Agent',status='完成',duration_ms=5))
        timeline.update(dict(agent='检索 Agent',status='执行中'))
        timeline.fail_unfinished()
        self.assertEqual([x['status'] for x in timeline.rows()],['完成','失败'])

    def test_real_coordinator_completion_events_have_measured_durations(self):
        events=[]; timeline=TimelineState()
        def observe(event): events.append(event); timeline.update(event)
        result=asyncio.run(Coordinator(Search()).run('咳嗽3天',{},InMemoryChatMessageHistory(),uuid.uuid4().hex,LLMConfig(),on_event=observe))
        for step in result['trace']:
            event=next(x for x in events if x['agent']==step['agent'] and x['status']==step['status'])
            self.assertEqual(event['duration_ms'],step['duration_ms'])
        self.assertEqual(len(timeline.rows()),len(result['trace']))
        self.assertTrue(all(x['duration_ms'] is not None for x in timeline.rows()))

    def test_native_timeline_captions_preserve_failed_and_missing_metrics(self):
        script='''
from execution_timeline import render_timeline
render_timeline([
    dict(agent='问诊 Agent',status='完成',duration_ms=25),
    dict(agent='检索 Agent',status='失败',duration_ms=None,error='timeout'),
])
'''
        app=AppTest.from_string(script).run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertTrue(any(x.value=='执行时间轴' for x in app.subheader))
        self.assertTrue(any('失败 · 耗时未记录' in x.value for x in app.caption))
        self.assertTrue(any('完成 · 25 ms' in x.value for x in app.caption))
        self.assertFalse(app.json)

    def test_actual_consultation_page_and_replay_do_not_rerun_agents(self):
        name='timeline_'+uuid.uuid4().hex[:8]
        token=accounts.register(name,'Timeline-test-password-123','时间轴验证')['token']
        app=AppTest.from_file('app.py',default_timeout=30)
        app.session_state.personal_token=token
        app.session_state.api_key=''
        app.run(); app.switch_page('app_pages/agent_consultation.py').run()
        with patch('ui.retrieval',return_value=Search()):
            app.chat_input[0].set_value('我咳嗽3天了').run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertTrue(any(x.value=='执行时间轴' for x in app.subheader))
        request=app.session_state.turns[-1]['request']
        with patch('agents.coordinator.Coordinator.run',side_effect=AssertionError('Replay must not call agents')):
            app.run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertEqual(app.session_state.turns[-1]['request'],request)
        self.assertTrue(any(x.value=='执行时间轴' for x in app.subheader))


if __name__=='__main__': unittest.main(verbosity=2)
