"""Offline acceptance tests, isolated SQLite databases and normal account identity."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
# Other legacy test modules initialize their stores at import time. Keep the
# combined suite away from the real runtime even when this module loads first.
SUITE_RUNTIME = Path(tempfile.mkdtemp(prefix='card_suite_', dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR'] = str(SUITE_RUNTIME)
os.environ['MEDICAL_API_CONFIG'] = str(SUITE_RUNTIME / 'no-api.toml')
from agents import accounts, conversations as store, family, telemetry
from agents.consultation_card import FIELDS, empty_card, extract, merge, summary, context_from_card


def decisions(card, **values):
    result = {key: dict(value=field['value'], status=('已确认' if field['value'] and field['status'] != '不清楚' else field['status']))
              for key, field in card['fields'].items()}
    for key, value in values.items(): result[key] = dict(value=value, status='已确认')
    return result


class CardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for module, name in [(family, 'family'), (store, 'conversations'), (telemetry, 'monitor')]:
            patcher = patch.object(module, 'DB', root / (name+'.sqlite'))
            patcher.start(); self.addCleanup(patcher.stop)
        self.token = accounts.register('card_owner', 'Card-test-password-123', '核对卡演示')['token']
        self.other = accounts.register('card_other', 'Card-test-password-123', '其他账号')['token']
        self.key = store.create(self.token)

    def test_required_example_and_provenance(self):
        card = store.ingest_card(self.token, self.key, 'q1', '我咳嗽3天了')
        self.assertEqual(card['fields']['complaint']['value'], '咳嗽')
        self.assertEqual(card['fields']['duration']['value'], '3天')
        self.assertEqual(card['fields']['severity']['status'], '未提供')
        card = store.ingest_card(self.token, self.key, 'q2', '无已知药物过敏，现在没吃药')
        self.assertEqual(card['fields']['allergies']['value'], '无已知药物过敏')
        self.assertEqual(card['fields']['medications']['value'], '目前未用药')
        card = store.save_card(self.token, self.key, decisions(card, duration='5天'), card['version'])
        self.assertEqual(card['fields']['duration']['status'], '已确认')
        origins = card['fields']['duration']['sources']
        self.assertEqual(origins[0]['request_id'], 'q1')
        self.assertEqual(origins[0]['quote'], '我咳嗽3天了')
        self.assertEqual(origins[-1]['quote'], '5天')
        report = summary(card['fields'], card['version'])
        self.assertIn('持续时间：5天（已确认）', report)
        self.assertIn('## 待补充与待核对', report)
        self.assertNotIn('风险评分', report)

    def test_confirmed_protection_and_explicit_resolution(self):
        card = store.ingest_card(self.token, self.key, 'q1', '我咳嗽3天了')
        card = store.save_card(self.token, self.key, decisions(card), card['version'])
        card = store.ingest_card(self.token, self.key, 'q2', '其实是咳嗽5天了')
        field = card['fields']['duration']
        self.assertEqual(field['value'], '3天')
        self.assertEqual(field['pending']['value'], '5天')
        self.assertIn('新描述待核对', summary(card['fields'], card['version']))
        card = store.save_card(self.token, self.key, decisions(card, duration='5天'), card['version'])
        self.assertEqual(card['fields']['duration']['value'], '5天')
        self.assertIsNone(card['fields']['duration']['pending'])
        self.assertTrue(any(s['request_id'] == 'q2' for s in card['fields']['duration']['sources']))

    def test_repeated_input_save_and_rerun_are_idempotent(self):
        card = store.ingest_card(self.token, self.key, 'q1', '我咳嗽3天了')
        original_version = card['version']
        self.assertEqual(store.ingest_card(self.token, self.key, 'q1', '我咳嗽3天了')['version'], original_version)
        edits = decisions(card, duration='5天')
        saved = store.save_card(self.token, self.key, edits, original_version)
        self.assertEqual(store.save_card(self.token, self.key, edits, original_version), saved)
        self.assertEqual(store.ingest_card(self.token, self.key, 'q1', '我咳嗽3天了'), saved)
        self.assertEqual(len(store.card_versions(self.token, self.key)), 2)
        with self.assertRaises(ValueError): store.ingest_card(self.token, self.key, 'q1', '不一样的原话')

    def test_switch_relogin_and_account_isolation(self):
        saved = store.ingest_card(self.token, self.key, 'q1', '我咳嗽3天了')
        second = store.create(self.token)
        self.assertEqual(store.load_card(self.token, second)['version'], 0)
        self.assertEqual(store.load_card(self.token, self.key), saved)
        accounts.logout(self.token)
        fresh = accounts.login('card_owner', 'Card-test-password-123')
        self.assertEqual(store.load_card(fresh, self.key), saved)
        for token in (self.other, self.token):
            for operation in (
                lambda: store.load_card(token, self.key), lambda: store.card_versions(token, self.key),
                lambda: store.ingest_card(token, self.key, 'bad', '咳嗽5天'),
                lambda: store.save_card(token, self.key, decisions(saved), saved['version']),
            ):
                with self.assertRaises(PermissionError): operation()

    def test_unknown_negation_accompanying_and_custom_text(self):
        fields = merge(empty_card(), extract('主要不适：嗓子干；持续时间不清楚，轻微，伴有发热；药物过敏史不清楚，当前用药：维生素C', 'q1'))
        self.assertEqual(fields['complaint']['value'], '嗓子干')
        self.assertEqual(fields['duration']['status'], '不清楚')
        self.assertEqual(fields['allergies']['status'], '不清楚')
        self.assertEqual(fields['associated']['value'], '发热')
        self.assertEqual(fields['medications']['value'], '维生素C')
        self.assertNotIn('胸痛', extract('没有胸痛，咳嗽3天', 'q2')['complaint']['value'])

    def test_stale_writer_does_not_overwrite_and_delete_cleans_versions(self):
        old = store.ingest_card(self.token, self.key, 'q1', '我咳嗽3天了')
        store.ingest_card(self.token, self.key, 'q2', '我咳嗽4天了')
        with self.assertRaises(store.CardConflict):
            store.save_card(self.token, self.key, decisions(old, duration='5天'), old['version'])
        store.delete(self.token, self.key)
        with store._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM consultation_card_versions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM consultation_card_inputs').fetchone()[0], 0)

    def test_confirmed_context_and_unknown_protection(self):
        card = store.ingest_card(self.token, self.key, 'q1', '药物过敏史不清楚，现在没吃药')
        self.assertEqual(context_from_card(card['fields'], {}), {})
        card = store.save_card(self.token, self.key, decisions(card), card['version'])
        self.assertEqual(context_from_card(card['fields'], {})['allergies'], '不清楚')
        self.assertEqual(context_from_card(card['fields'], {'medications':'人工补充药名'})['medications'], '人工补充药名')
        card = store.ingest_card(self.token, self.key, 'q2', '对青霉素过敏')
        self.assertEqual(card['fields']['allergies']['value'], '不清楚')
        self.assertEqual(card['fields']['allergies']['pending']['value'], '青霉素')

    def test_ui_save_rerun_switch_and_refresh(self):
        from streamlit.testing.v1 import AppTest
        fixture = '''
import streamlit as st
from consultation_card_ui import card_panel
st.session_state.setdefault('turns', [])
card_panel()
'''
        store.ingest_card(self.token, self.key, 'q1', '我咳嗽3天了')
        def page(token, key):
            app = AppTest.from_string(fixture)
            app.session_state.personal_token = token
            app.session_state.conversation_id = key
            app.run()
            self.assertFalse(app.exception, [x.message for x in app.exception])
            return app
        app = page(self.token, self.key)
        next(w for w in app.text_input if w.label == '持续时间').set_value('5天')
        next(b for b in app.button if b.label == '确认并保存').click().run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        saved = store.load_card(self.token, self.key)
        self.assertEqual(saved['fields']['duration']['value'], '5天')
        app.run()
        next(b for b in app.button if b.label == '确认并保存').click().run()
        self.assertEqual(store.load_card(self.token, self.key)['version'], saved['version'])
        fresh = page(accounts.login('card_owner', 'Card-test-password-123'), self.key)
        self.assertEqual(next(w for w in fresh.text_input if w.label == '持续时间').value, '5天')
        second = store.create(self.token)
        app.session_state.conversation_id = second
        app.run()
        self.assertEqual(next(w for w in app.text_input if w.label == '持续时间').value, '')
        app.session_state.conversation_id = self.key
        app.run()
        self.assertEqual(next(w for w in app.text_input if w.label == '持续时间').value, '5天')
        # Sources are shown as text, not interpolated HTML/JSON, even for arbitrary originals.
        self.assertTrue(any('q1' in x.value for x in fresh.caption))

    def test_full_page_uses_original_and_shared_request_even_on_failure(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file('app.py', default_timeout=30)
        app.session_state.personal_token = self.token
        app.run(); app.switch_page('app_pages/agent_consultation.py').run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        key = app.session_state.conversation_id
        seen = []
        async def completed(*args, **kwargs):
            seen.append(kwargs['request_id'])
            return dict(request=kwargs['request_id'], answer='离线流程测试', trace=[], evidences=[], conflicts=[])
        app.session_state.vision_handoff = '图片观察（AI 描述，未经核实）：胸痛7天，严重'
        with patch('agents.coordinator.Coordinator.run', side_effect=completed):
            app.chat_input[0].set_value('我咳嗽3天了').run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        card = store.load_card(self.token, key)
        self.assertEqual(card['fields']['duration']['value'], '3天')
        self.assertEqual(card['fields']['complaint']['value'], '咳嗽')
        self.assertEqual(card['fields']['severity']['status'], '未提供')
        source = card['fields']['duration']['sources'][0]
        self.assertEqual(source['request_id'], seen[0])
        self.assertEqual(source['quote'], '我咳嗽3天了')
        self.assertEqual(store.load(self.token, key)['turns'][0]['card_original'], '我咳嗽3天了')
        app.run()
        self.assertEqual(store.load_card(self.token, key)['version'], card['version'])
        async def failed(*args, **kwargs): raise RuntimeError('离线测试的预期失败')
        with patch('agents.coordinator.Coordinator.run', side_effect=failed):
            app.chat_input[0].set_value('无已知药物过敏，现在没吃药').run()
        self.assertFalse(app.exception, [x.message for x in app.exception])
        self.assertTrue(any('已保留核对卡' in x.value for x in app.error))
        self.assertEqual(store.load_card(self.token, key)['fields']['medications']['value'], '目前未用药')


if __name__ == '__main__': unittest.main(verbosity=2)
