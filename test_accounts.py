import os
import tempfile
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='accounts_test_',dir='runtime')
from agents import accounts as a,family as f


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.username='u_'+uuid.uuid4().hex[:12]
        self.password='Private-password-123'
        self.result=a.register(self.username,self.password,'测试用户')

    def test_login_and_secret_storage(self):
        token=a.login(self.username.upper(),self.password)
        person=f.identity_profile(token)
        self.assertEqual(person['username'],self.username)
        self.assertEqual(person['id'],f.identity_profile(self.result['token'])['id'])
        with f.connect() as db:
            row=db.execute('SELECT * FROM accounts WHERE username=?',(self.username,)).fetchone()
            self.assertNotIn(self.password,dict(row).values())
            self.assertNotEqual(row['recovery_hash'],self.result['recovery'])
            self.assertIsNone(db.execute('SELECT * FROM login_sessions WHERE secret_hash=?',(token,)).fetchone())

    def test_validation_and_duplicate(self):
        for name,password in [('a','valid-password'),('含中文账号','valid-password'),('valid_name','short')]:
            with self.assertRaises(ValueError): a.register(name,password,'用户')
        with self.assertRaises(ValueError): a.register(self.username.upper(),self.password,'其他人')

    def test_failed_login_limit(self):
        for _ in range(5):
            with self.assertRaisesRegex(PermissionError,'用户名或密码不正确'): a.login(self.username,'wrong-password')
        with self.assertRaisesRegex(PermissionError,'15 分钟'): a.login(self.username,self.password)

    def test_logout_and_expiry(self):
        family=f.create_family('测试家庭','本人',self.result['token'])
        a.logout(self.result['token'])
        with self.assertRaises(PermissionError): f.profile(family['token'])
        token=a.login(self.username,self.password)
        with patch.object(f,'now',return_value=f.now()+timedelta(days=2)):
            with self.assertRaises(PermissionError): f.identity_profile(token)

    def test_password_change_revokes_other_devices(self):
        other=a.login(self.username,self.password,True)
        with self.assertRaises(PermissionError): a.change_password(other,'wrong-password','new-password-123')
        token=a.change_password(self.result['token'],self.password,'new-password-123')
        self.assertEqual(f.identity_profile(token)['username'],self.username)
        for old in [other,self.result['token']]:
            with self.assertRaises(PermissionError): f.identity_profile(old)
        with self.assertRaises(PermissionError): a.login(self.username,self.password)
        self.assertTrue(a.login(self.username,'new-password-123'))

    def test_recovery_rotates_code_and_sessions(self):
        with self.assertRaises(PermissionError): a.recover(self.username,'wrong-code','new-password-123')
        result=a.recover(self.username,self.result['recovery'],'new-password-123')
        self.assertNotEqual(result['recovery'],self.result['recovery'])
        with self.assertRaises(PermissionError): f.identity_profile(self.result['token'])
        with self.assertRaises(PermissionError): a.recover(self.username,self.result['recovery'],'other-password-123')
        self.assertTrue(a.login(self.username,'new-password-123'))

    def test_upgrade_keeps_families_and_revokes_legacy_identity(self):
        legacy=f.create_identity('原用户')
        old=f.create_family('原家庭','我',legacy)
        member=f.profile(old['token'])['id']
        f.add_measurement(old['token'],'状态',{'说明':'原来的记录'})
        result=a.register('legacy_'+uuid.uuid4().hex[:8],self.password,'原用户',legacy_token=legacy)
        self.assertEqual(f.my_families(result['token'])[0]['member_id'],member)
        token=result['token']+'.'+member
        self.assertEqual(f.health_records(token,member)[0]['values']['说明'],'原来的记录')
        with self.assertRaises(PermissionError): f.identity_profile(legacy)
        with self.assertRaises(PermissionError): f.profile(old['token'])

    def test_upgrade_revokes_imported_member_key(self):
        original=f.create_family('旧家庭','原成员')
        legacy=f.create_identity('原成员')
        f.import_membership(legacy,original['token'])
        result=a.register('import_'+uuid.uuid4().hex[:8],self.password,'原成员',legacy_token=legacy)
        self.assertEqual(len(f.my_families(result['token'])),1)
        with self.assertRaises(PermissionError): f.profile(original['token'])

    def test_user_isolation_and_explicit_family_consent(self):
        other=a.register('other_'+uuid.uuid4().hex[:8],self.password,'另一人')
        owner=f.create_family('我的家庭','我',self.result['token'])
        member=f.profile(owner['token'])['id']
        self.assertFalse(f.my_families(other['token']))
        with self.assertRaises(PermissionError): f.profile(other['token']+'.'+member)
        joined=f.join_family(owner['invite'],'家人',other['token'])
        with self.assertRaises(PermissionError): f.health_records(joined['token'],member)

if __name__=='__main__': unittest.main(verbosity=2)
