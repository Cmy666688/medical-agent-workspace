import os,tempfile,unittest
from pathlib import Path
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='identity_test_',dir='runtime')
from agents import family as f

class Tests(unittest.TestCase):
    def test_families_persist_across_reconnection(self):
        account=f.create_identity('成员')
        first=f.create_family('我的家庭','我',account)
        other=f.create_family('亲属家庭','亲属')
        joined=f.join_family(other['invite'],'我',account)
        listing=f.my_families(account)
        self.assertEqual(len(listing),2)
        self.assertEqual(sorted(r['role'] for r in listing),['member','owner'])
        self.assertEqual(f.profile(first['token'])['family'],'我的家庭')
        self.assertEqual(f.profile(joined['token'])['family'],'亲属家庭')
    def test_identity_cannot_select_other_member(self):
        account=f.create_identity('我'); other=f.create_family('他人家庭','他人')
        with self.assertRaises(PermissionError): f.profile(account+'.'+f.profile(other['token'])['id'])
    def test_restore_legacy_without_replacing_records(self):
        legacy=f.create_family('旧家庭','原成员')
        f.add_measurement(legacy['token'],'状态',{'说明':'测试记录'})
        account=f.create_identity('原成员'); active=f.import_membership(account,legacy['token'])
        self.assertEqual(len(f.my_families(account)),1)
        self.assertEqual(f.health_records(active,f.profile(active)['id'])[0]['values']['说明'],'测试记录')
        self.assertEqual(f.profile(legacy['token'])['id'],f.profile(active)['id'])
        another=f.create_identity('其他人')
        with self.assertRaises(PermissionError): f.import_membership(another,legacy['token'])
    def test_join_same_family_once(self):
        owner=f.create_family('家庭','家人'); account=f.create_identity('我')
        first=f.join_family(owner['invite'],'我',account); second=f.join_family(owner['invite'],'我',account)
        self.assertEqual(first['token'],second['token'])
        self.assertEqual(len(f.my_families(account)),1)

if __name__=='__main__': unittest.main(verbosity=2)
