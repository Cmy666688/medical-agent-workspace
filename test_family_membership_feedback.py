"""Actual family forms must show a result and open the selected household."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

Path('runtime').mkdir(exist_ok=True)
runtime=Path(tempfile.mkdtemp(prefix='membership_feedback_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'no-api.toml')

from agents import accounts,family
from streamlit.testing.v1 import AppTest


class Tests(unittest.TestCase):
    def setUp(self):
        self.owner_name='owner_'+uuid.uuid4().hex[:8]
        self.member_name='member_'+uuid.uuid4().hex[:8]
        self.owner=accounts.register(self.owner_name,'Family-feedback-test-123','创建人')['token']
        self.member=accounts.register(self.member_name,'Family-feedback-test-123','家人')['token']
        self.group=family.create_family('加入验证家庭','本人',self.owner)

    def page(self,token):
        app=AppTest.from_file('app.py',default_timeout=30)
        app.session_state.personal_token=token
        app.run();app.switch_page('app_pages/family_home.py').run()
        next(w for w in app.get('segmented_control') if w.label=='家庭操作').set_value('加入家庭').run()
        self.assertFalse(app.exception,[w.message for w in app.exception])
        return app

    def join(self,app,code):
        next(w for w in app.text_input if w.label=='家庭邀请码').set_value(code)
        next(w for w in app.button if w.label=='加入家庭').click().run()
        self.assertFalse(app.exception,[w.message for w in app.exception])

    def test_new_member_opens_details_with_success_and_durable_confirmation(self):
        app=self.page(self.member)
        self.join(app,self.group['invite'])
        self.assertTrue(any('已成功加入「加入验证家庭」' in w.value for w in app.success))
        self.assertTrue(any(w.value=='家庭成员与留言' for w in app.title))
        self.assertTrue(any('@'+self.member_name in w.value and '2 位成员' in w.value for w in app.caption))
        self.assertEqual(len(family.members(self.group['token'])),2)
        with patch('agents.family.join_family',side_effect=AssertionError('Rerun must not join again')):
            # AppTest retains the source script hash after switch_page inside a
            # script; explicitly target the destination to replay that page.
            app.switch_page('app_pages/agent_family.py').run()
            self.assertTrue(any('已成功加入' in w.value for w in app.success))
            next(w for w in app.button if w.label=='我知道了').click().run()
        self.assertFalse(app.exception)
        self.assertFalse(any('已成功加入' in w.value for w in app.success))

    def test_existing_membership_switches_from_another_family_without_duplicates(self):
        original=family.join_family(self.group['invite'],'家人',self.member)
        other=family.create_family('另一家庭','我',self.member)
        app=self.page(self.member)
        app.session_state.family_token=other['token']
        self.join(app,self.group['invite'])
        self.assertEqual(app.session_state.family_token,original['token'])
        self.assertTrue(any('你已是「加入验证家庭」的成员' in w.value for w in app.info))
        self.assertEqual(len(family.members(self.group['token'])),2)
        self.assertEqual(len(family.my_families(self.member)),2)

    def test_owner_joining_own_code_has_explicit_already_member_notice(self):
        app=self.page(self.owner)
        self.join(app,self.group['invite'])
        self.assertTrue(any('你已是「加入验证家庭」的成员' in w.value for w in app.info))
        self.assertEqual(len(family.members(self.group['token'])),1)
        result=family.join_family(self.group['invite'],'重复操作',self.owner)
        self.assertTrue(result['already_member'])
        self.assertEqual(result['member_count'],1)

    def test_invalid_and_expired_invites_show_error_and_preserve_input(self):
        app=self.page(self.member)
        self.join(app,'')
        self.assertTrue(any('请先填写家庭邀请码' in w.value for w in app.error))
        self.join(app,'incorrect-code')
        self.assertTrue(any('邀请码无效' in w.value for w in app.error))
        self.assertEqual(next(w for w in app.text_input if w.label=='家庭邀请码').value,'incorrect-code')
        group_id=family.profile(self.group['token'])['group_id']
        with family.connect() as db:
            db.execute('UPDATE households SET expires=? WHERE id=?',((family.now()-timedelta(seconds=1)).isoformat(),group_id))
        self.join(app,self.group['invite'])
        self.assertTrue(any('邀请码已过期' in w.value for w in app.error))
        self.assertFalse(family.my_families(self.member))

    def test_new_join_does_not_grant_access_to_other_members_health_records(self):
        result=family.join_family(self.group['invite'],'家人',self.member)
        self.assertFalse(result['already_member'])
        self.assertEqual(result['member_count'],2)
        owner_id=family.profile(self.group['token'])['id']
        with self.assertRaises(PermissionError):family.health_records(result['token'],owner_id)

    def test_busy_database_has_visible_retry_message(self):
        app=self.page(self.member)
        with patch('agents.family.join_family',side_effect=sqlite3.OperationalError('synthetic busy')):
            self.join(app,self.group['invite'])
        self.assertTrue(any('家庭服务暂时繁忙' in w.value for w in app.error))
        self.assertEqual(len(family.members(self.group['token'])),1)


if __name__=='__main__':unittest.main(verbosity=2)
