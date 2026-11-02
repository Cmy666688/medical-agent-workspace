"""Two-account delegation, scope checks, revocation and the actual reminder UI."""
import os,tempfile,unittest,uuid
from datetime import timedelta
from pathlib import Path

Path('runtime').mkdir(exist_ok=True)
runtime=Path(tempfile.mkdtemp(prefix='reminder_delegate_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'no-api.toml')
from agents import accounts,family as f
from streamlit.testing.v1 import AppTest


class Tests(unittest.TestCase):
    def setUp(self):
        self.a=accounts.register('a_'+uuid.uuid4().hex[:8],'Delegate-password-123','同名称呼')['token']
        self.b=accounts.register('b_'+uuid.uuid4().hex[:8],'Delegate-password-123','同名称呼')['token']
        self.group=f.create_family('授权测试家庭','同名称呼',self.a)
        self.at=self.group['token']
        self.bt=f.join_family(self.group['invite'],'同名称呼',self.b)['token']
        self.aid=f.profile(self.at)['id'];self.bid=f.profile(self.bt)['id']

    def page(self,token):
        app=AppTest.from_file('app.py',default_timeout=30)
        app.session_state.personal_token=token
        app.run();app.switch_page('app_pages/agent_schedule.py').run()
        self.assertFalse(app.exception,[w.message for w in app.exception])
        return app

    def test_request_approve_manage_only_and_recipient_inbox(self):
        key=f.request_reminder_access(self.at,self.bid)
        self.assertEqual(f.request_reminder_access(self.at,self.bid),key)
        with self.assertRaises(PermissionError):f.add_schedule(self.at,self.bid,'测量提醒','测量血压','08:00')
        self.assertEqual(len(f.reminder_requests(self.bt)),1)
        with self.assertRaises(PermissionError):f.respond_reminder_access(self.at,key,True)
        self.assertEqual(f.respond_reminder_access(self.bt,key,True),'approved')
        self.assertEqual(f.respond_reminder_access(self.bt,key,True),'approved')
        due=f.now().replace(second=0,microsecond=0)+timedelta(minutes=1)
        sid=f.add_schedule(self.at,self.bid,'测量提醒','测量血压',due.strftime('%H:%M'))
        self.assertEqual(f.schedules(self.at,self.bid)[0]['id'],sid)
        with self.assertRaises(PermissionError):f.health_records(self.at,self.bid)
        f.tick(due)
        self.assertFalse(f.notices(self.at,self.aid))
        self.assertTrue(f.notices(self.bt,self.bid))

    def test_decline_cross_family_revocation_and_read_permission_preserved(self):
        outsider=f.create_family('其他家庭','外人')
        with self.assertRaises(PermissionError):f.request_reminder_access(self.at,f.profile(outsider['token'])['id'])
        with self.assertRaises(PermissionError):f.set_reminder_delegates(self.at,[self.bid,f.profile(outsider['token'])['id']])
        self.assertFalse(next(row for row in f.members(self.bt) if row['id']==self.aid)['can_manage'])
        key=f.request_reminder_access(self.at,self.bid)
        f.respond_reminder_access(self.bt,key,False)
        with self.assertRaises(PermissionError):f.add_schedule(self.at,self.bid,'提醒','饮水','08:00')
        self.assertNotEqual(f.request_reminder_access(self.at,self.bid),key)
        f.set_grant(self.bt,self.aid,True,False)
        f.set_reminder_delegates(self.bt,[self.aid])
        f.set_reminder_delegates(self.bt,[])
        target=next(row for row in f.members(self.at) if row['id']==self.bid)
        self.assertTrue(target['can_read']);self.assertFalse(target['can_manage'])
        self.assertEqual(f.reminder_request_status(self.at,self.bid),'revoked')

    def test_ui_all_members_request_approval_create_and_refresh_after_revocation(self):
        helper=self.page(self.a)
        picker=next(w for w in helper.selectbox if w.label=='选择成员')
        self.assertEqual(len(picker.options),2)
        self.assertTrue(any('待授权' in label for label in picker.options))
        picker.set_value(self.bid).run()
        self.assertFalse(helper.get('form_submit_button') and any(w.label=='创建提醒计划' for w in helper.get('form_submit_button')))
        helper.button(key='request_reminder_'+self.bid).click().run()
        self.assertTrue(helper.button(key='request_reminder_'+self.bid).disabled)
        recipient=self.page(self.b)
        next(w for w in recipient.button if w.label=='同意代设提醒').click().run()
        self.assertFalse(recipient.exception,[w.message for w in recipient.exception])
        helper.button(key='refresh_reminder_'+self.bid).click().run()
        self.assertFalse(helper.exception,[w.message for w in helper.exception])
        self.assertTrue(any(w.label=='创建提醒计划' for w in helper.get('form_submit_button')))
        helper.form('create_schedule').text_input[0].set_value('代设饮水提醒')
        helper.form('create_schedule').form_submit_button[0].click().run()
        self.assertFalse(helper.exception,[w.message for w in helper.exception])
        self.assertEqual(f.schedules(self.bt,self.bid)[0]['title'],'代设饮水提醒')
        f.set_reminder_delegates(self.bt,[])
        helper.run()
        self.assertFalse(helper.exception)
        self.assertFalse(any(w.label=='创建提醒计划' for w in helper.get('form_submit_button')))
        self.assertTrue(any('尚未授权' in w.value for w in helper.info))

    def test_direct_delegate_form(self):
        app=self.page(self.b)
        next(w for w in app.multiselect if w.label=='允许代设我提醒的家人').set_value([self.aid])
        next(w for w in app.button if w.label=='保存代设权限').click().run()
        self.assertFalse(app.exception,[w.message for w in app.exception])
        self.assertTrue(next(row for row in f.members(self.at) if row['id']==self.bid)['can_manage'])
        self.assertFalse(next(row for row in f.members(self.at) if row['id']==self.bid)['can_read'])


if __name__=='__main__':unittest.main(verbosity=2)
