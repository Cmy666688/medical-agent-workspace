import os,tempfile,unittest,uuid
from pathlib import Path
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='conversations_test_',dir='runtime')
from agents import accounts,conversations as c

def turn(question='测试问题'):
    return dict(request=uuid.uuid4().hex,question=question,answer='测试答复',evidences=[],trace=[],conflicts=[])

class Tests(unittest.TestCase):
    def setUp(self):
        self.name='u_'+uuid.uuid4().hex[:10]
        self.token=accounts.register(self.name,'History-password-123','历史用户')['token']
        self.other=accounts.register('u_'+uuid.uuid4().hex[:10],'History-password-123','其他用户')['token']
    def test_retention_reconnect_and_deduplication(self):
        key=c.create(self.token); item=turn('旧的问题'); c.append(self.token,key,item,{'age':44})
        c.append(self.token,key,item)
        second=c.create(self.token)
        fresh=accounts.login(self.name,'History-password-123')
        self.assertEqual(len(c.listing(fresh)),2)
        self.assertEqual(c.load(fresh,key)['turns'],[item])
        self.assertEqual(c.load(fresh,key)['context']['age'],44)
        self.assertFalse(c.load(fresh,second)['turns'])
    def test_owner_checks_on_all_operations(self):
        key=c.create(self.token)
        for action in [lambda:c.load(self.other,key),lambda:c.append(self.other,key,turn()),lambda:c.rename(self.other,key,'别人的记录'),lambda:c.delete(self.other,key),lambda:c.context(self.other,key,{})]:
            with self.assertRaises(PermissionError): action()
        self.assertFalse(c.listing(self.other))
    def test_rename_search_and_individual_delete(self):
        first=c.create(self.token); second=c.create(self.token)
        c.append(self.token,first,turn()); c.rename(self.token,first,'我的血压记录')
        c.append(self.token,first,turn('继续补充'))
        self.assertEqual(c.listing(self.token,'血压')[0]['title'],'我的血压记录')
        self.assertIn('继续补充',c.markdown(c.load(self.token,first)))
        c.delete(self.token,first)
        self.assertEqual(c.listing(self.token)[0]['id'],second)
        with self.assertRaises(PermissionError): c.load(self.token,first)
    def test_revoked_session_cannot_read(self):
        key=c.create(self.token); accounts.logout(self.token)
        with self.assertRaises(PermissionError): c.load(self.token,key)

if __name__=='__main__': unittest.main(verbosity=2)
