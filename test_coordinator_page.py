"""Authenticated coordinator UI, shared persistence and honest metrics; no API."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

Path('runtime').mkdir(exist_ok=True)
runtime = Path(tempfile.mkdtemp(prefix='coordinator_page_test_', dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR'] = str(runtime)
os.environ['MEDICAL_API_CONFIG'] = str(runtime / 'no-api.toml')

from agents import accounts, conversations as store
from agents.llm import LLMConfig
from coordinator_ui import workflow_overview
from streamlit.testing.v1 import AppTest


class Search:
    def search(self, query):
        return dict(evidences=[dict(doc_id='coord-test', name='合成测试资料',
                                   content='仅用于测试执行流程的资料。')],
                    cache_hit=False, latency_ms=12.5)


class Tests(unittest.TestCase):
    def page(self, token=None):
        app = AppTest.from_file('app.py', default_timeout=30)
        if token:
            app.session_state.personal_token = token
        app.run()
        app.switch_page('app_pages/coordinator.py').run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        return app

    def account(self):
        return accounts.register('coord_' + uuid.uuid4().hex[:10],
                                 'Coordinator-test-password-123', '协作测试')['token']

    def test_locked_route_renders_login_without_workflow(self):
        # Hidden unauthenticated routes use functions rather than protected files.
        app = AppTest.from_file('app.py', default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertFalse(any(x.value == '多智能体协调器' for x in app.title))
        self.assertFalse(any(x.label == '运行协作流程' for x in app.button))
        with self.assertRaises(ValueError):
            app.switch_page('app_pages/coordinator.py')

    def test_shared_saved_turn_card_replay_and_other_account(self):
        token = self.account()
        with patch('ui.llm_config', return_value=LLMConfig()), \
             patch('ui.retrieval', return_value=Search()) as retrieval:
            app = self.page(token)
            self.assertEqual(retrieval.call_count, 0)
            app.text_area[0].set_value('我咳嗽3天了')
            next(x for x in app.button if x.label == '运行协作流程').click().run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        key = app.session_state.conversation_id
        saved = store.load(token, key)
        self.assertEqual(len(saved['turns']), 1)
        turn = saved['turns'][0]
        self.assertGreater(turn['duration_ms'], 0)
        self.assertEqual(store.load_card(token, key)['fields']['duration']['sources'][0]['request_id'], turn['request'])
        self.assertTrue(any(x.value == '执行时间轴' for x in app.subheader))
        self.assertTrue(any(x.value == '各 Agent 输出详情' for x in app.subheader))
        self.assertFalse(app.json)
        with patch('agents.coordinator.Coordinator.run', side_effect=AssertionError('Replay must not execute')):
            app.run()
            app.switch_page('app_pages/agent_consultation.py').run()
            self.assertFalse(app.exception, [x.message for x in app.exception])
            self.assertEqual(app.session_state.turns[-1]['request'], turn['request'])
            app.switch_page('app_pages/coordinator.py').run()
            self.assertFalse(app.exception)
            restored = self.page(token)  # independent browser session restores SQLite
            self.assertEqual(restored.session_state.turns[-1]['request'], turn['request'])
            other = self.page(self.account())
            self.assertEqual(other.session_state.turns, [])
        self.assertEqual(len(store.load(token, key)['turns']), 1)
        with self.assertRaises(PermissionError):
            store.load(other.session_state.personal_token, key)

    def test_danger_alert_precedes_lazy_retrieval_and_failure_is_visible(self):
        app = self.page(self.account())
        from streamlit.delta_generator import DeltaGenerator
        original_warning = DeltaGenerator.warning
        notices = []
        observed_before_retrieval = []
        def warning(widget, body, *args, **kwargs):
            notices.append(str(body))
            return original_warning(widget, body, *args, **kwargs)
        def unavailable():
            observed_before_retrieval.append(any('请勿等待结果再就医' in item for item in notices))
            raise RuntimeError('retrieval_unavailable')
        with patch('ui.llm_config', return_value=LLMConfig()), \
             patch.object(DeltaGenerator, 'warning', warning), \
             patch('ui.retrieval', side_effect=unavailable) as search:
            app.text_area[0].set_value('胸痛3天了')
            next(x for x in app.button if x.label == '运行协作流程').click().run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        search.assert_called_once()
        self.assertEqual(observed_before_retrieval, [True])
        turn = app.session_state.turns[-1]
        self.assertEqual(workflow_overview(turn)['risk'], '有危险信号')
        self.assertTrue(any(x['agent'] == '检索 Agent' and x['status'] == '失败' for x in turn['trace']))
        self.assertTrue(any('步骤未完成' in x.value for x in app.warning))
        self.assertTrue(any(x['agent'] == '用药 Agent' for x in turn['trace']))

    def test_new_conversation_is_independent_and_old_workflow_restores(self):
        app = self.page(self.account())
        with patch('ui.llm_config', return_value=LLMConfig()), patch('ui.retrieval', return_value=Search()):
            app.text_area[0].set_value('我咳嗽3天了')
            next(x for x in app.button if x.label == '运行协作流程').click().run()
        key = app.session_state.conversation_id
        request = app.session_state.turns[-1]['request']
        next(x for x in app.button if x.label == '开始新对话').click().run()
        self.assertNotEqual(app.session_state.conversation_id, key)
        app.switch_page('app_pages/coordinator.py').run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        self.assertEqual(app.session_state.turns, [])
        self.assertEqual(app.text_area[0].value, '')
        next(x for x in app.button if x.key == 'recent_chat_' + key).click().run()
        app.switch_page('app_pages/coordinator.py').run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        self.assertEqual(app.session_state.turns[-1]['request'], request)

    def test_public_mode_exposes_coordinator_without_management(self):
        with patch.dict(os.environ, MEDICAL_PUBLIC_MODE='1'):
            app = self.page(self.account())
            self.assertTrue(any(x.value == '多智能体协调器' for x in app.title))
            with self.assertRaises(ValueError):
                app.switch_page('app_pages/evaluation.py')

    def test_metrics_do_not_invent_old_duration_or_clinical_score(self):
        result = workflow_overview(dict(trace=[dict(agent='风险评估 Agent', status='完成',
                                                    duration_ms=100, output=dict(red_flags=[]))]))
        self.assertEqual(result['duration'], '耗时未记录')
        self.assertEqual(result['risk'], '尚不能确定')
        self.assertEqual(result['completed'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
