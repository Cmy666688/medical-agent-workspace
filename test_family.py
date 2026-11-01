import os,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='family_test_',dir='runtime')
from agents import family as f

class Tests(unittest.TestCase):
    def setUp(self):
        self.owner=f.create_family('测试家庭','长者'); self.child=f.join_family(self.owner['invite'],'子女')
        self.elder=f.profile(self.owner['token']); self.young=f.profile(self.child['token'])
    def test_no_health_access_without_consent(self):
        f.add_measurement(self.owner['token'],'血压',{'收缩压':120,'舒张压':80})
        with self.assertRaises(PermissionError): f.health_records(self.child['token'],self.elder['id'])
        f.set_grant(self.owner['token'],self.young['id'],True,False)
        self.assertEqual(len(f.health_records(self.child['token'],self.elder['id'])),1)
        f.set_grant(self.owner['token'],self.young['id'],False,False)
        with self.assertRaises(PermissionError): f.health_records(self.child['token'],self.elder['id'])
    def test_owner_has_no_implicit_access(self):
        with self.assertRaises(PermissionError): f.health_records(self.owner['token'],self.young['id'])
    def test_group_isolation(self):
        outsider=f.create_family('其他家庭','陌生人')
        with self.assertRaises(PermissionError): f.health_records(outsider['token'],self.elder['id'])
        with self.assertRaises(PermissionError): f.set_grant(self.owner['token'],f.profile(outsider['token'])['id'],True,True)
    def test_management_separate_from_read(self):
        f.set_grant(self.owner['token'],self.young['id'],True,False)
        with self.assertRaises(PermissionError): f.add_schedule(self.child['token'],self.elder['id'],'测量血压','测量血压','08:00')
        f.set_grant(self.owner['token'],self.young['id'],True,True)
        self.assertTrue(f.add_schedule(self.child['token'],self.elder['id'],'测量血压','测量血压','08:00'))
    def test_daily_due_idempotent_completion_and_pause(self):
        created=datetime(2026,10,31,7,0,tzinfo=f.TZ)
        with patch('agents.family.now',return_value=created):
            sid=f.add_schedule(self.owner['token'],self.elder['id'],'服药提醒','服药','08:00')
        f.tick(created.replace(hour=7,minute=59)); self.assertFalse(f.notices(self.owner['token'],self.elder['id']))
        due=created.replace(hour=8); f.tick(due); f.tick(due)
        rows=f.notices(self.owner['token'],self.elder['id']); self.assertEqual(len(rows),1)
        f.set_grant(self.owner['token'],self.young['id'],True,True)
        with self.assertRaises(PermissionError): f.complete_notice(self.child['token'],rows[0]['id'])
        f.complete_notice(self.owner['token'],rows[0]['id'])
        self.assertEqual(f.notices(self.owner['token'],self.elder['id'])[0]['status'],'done')
        f.toggle_schedule(self.child['token'],sid,False); f.tick(due+timedelta(days=1))
        self.assertEqual(len(f.notices(self.owner['token'],self.elder['id'])),1)
    def test_remote_request_and_revocation(self):
        f.set_grant(self.owner['token'],self.young['id'],True,True)
        f.request_checkin(self.child['token'],self.elder['id'],'请报平安')
        self.assertEqual(f.notices(self.owner['token'],self.elder['id'])[0]['title'],'请报平安')
        f.set_grant(self.owner['token'],self.young['id'],True,False)
        with self.assertRaises(PermissionError): f.request_checkin(self.child['token'],self.elder['id'],'请求')
    def test_messages_private_to_group(self):
        f.send_message(self.owner['token'],'今天已测量')
        self.assertEqual(f.messages(self.child['token'])[0]['body'],'今天已测量')
        other=f.create_family('其他','成员'); self.assertFalse(f.messages(other['token']))
    def test_invitation_rotation(self):
        invitation=f.rotate_invite(self.owner['token'])
        with self.assertRaises(PermissionError): f.join_family(self.owner['invite'],'新成员')
        self.assertTrue(f.join_family(invitation,'新成员'))
        with self.assertRaises(PermissionError): f.rotate_invite(self.child['token'])
    def test_secret_not_stored_in_plaintext(self):
        with f.connect() as db:
            saved=db.execute('SELECT secret_hash FROM members WHERE id=?',(self.elder['id'],)).fetchone()[0]
        self.assertNotEqual(saved,self.owner['token'])
        with self.assertRaises(PermissionError): f.profile('invalid')
    def test_invalid_measurement(self):
        with self.assertRaises(ValueError): f.add_measurement(self.owner['token'],'血压',{'收缩压':70,'舒张压':80})

if __name__=='__main__': unittest.main(verbosity=2)
