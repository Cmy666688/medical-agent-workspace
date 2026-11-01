import os,tempfile,unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
Path('runtime').mkdir(exist_ok=True)
os.environ['MEDICAL_RUNTIME_DIR']=tempfile.mkdtemp(prefix='extended_family_',dir='runtime')
from agents import family as f

class Tests(unittest.TestCase):
    def setUp(self):
        self.owner=f.create_family('家庭','创建者'); self.a=f.join_family(self.owner['invite'],'甲'); self.b=f.join_family(self.owner['invite'],'乙')
        self.mid=f.profile(self.a['token'])['id']; self.bid=f.profile(self.b['token'])['id']
        self.created=datetime(2026,10,31,7,tzinfo=f.TZ)
    def add(self,**kwargs):
        with patch('agents.family.now',return_value=self.created):
            return f.add_schedule(self.a['token'],self.mid,'测试事项','饮水','08:00',**kwargs)
    def count(self): return len(f.notices(self.a['token'],self.mid))
    def test_direct_message_visible_only_to_participants(self):
        f.send_message(self.a['token'],'只给乙',self.bid)
        self.assertEqual(f.messages(self.a['token'])[0]['body'],'只给乙')
        self.assertEqual(f.messages(self.b['token'])[0]['body'],'只给乙')
        self.assertFalse(f.messages(self.owner['token']))
        f.send_message(self.owner['token'],'公开留言')
        self.assertEqual(len(f.messages(self.a['token'])),2)
    def test_cannot_message_outside_group(self):
        other=f.create_family('外部','外部成员')
        with self.assertRaises(PermissionError): f.send_message(self.a['token'],'内容',f.profile(other['token'])['id'])
    def test_interval_slots_and_window_boundary(self):
        self.add(repeat='interval',end_clock='10:00',interval_minutes=30,start_date='2026-10-31',end_date='2026-10-31')
        f.tick(self.created.replace(hour=7,minute=59)); self.assertEqual(self.count(),0)
        f.tick(self.created.replace(hour=8,minute=5)); self.assertEqual(self.count(),1)
        f.tick(self.created.replace(hour=8,minute=20)); self.assertEqual(self.count(),1)
        f.tick(self.created.replace(hour=8,minute=30)); self.assertEqual(self.count(),2)
        f.tick(self.created.replace(hour=11)); self.assertEqual(self.count(),2)
        f.tick(self.created.replace(hour=8)+timedelta(days=1)); self.assertEqual(self.count(),2)
    def test_latest_slot_only_after_downtime(self):
        self.add(repeat='interval',end_clock='12:00',interval_minutes=30)
        f.tick(self.created.replace(hour=11,minute=45))
        self.assertEqual(self.count(),1)
        self.assertIn('11:30',f.notices(self.a['token'],self.mid)[0]['due'])
    def test_weekly_filter(self):
        self.add(repeat='weekly',weekdays=[0],start_date='2026-10-31',end_date='2026-11-03')
        f.tick(self.created.replace(hour=8)); self.assertEqual(self.count(),0)
        f.tick(self.created.replace(hour=8)+timedelta(days=2)); self.assertEqual(self.count(),1)
        f.tick(self.created.replace(hour=8)+timedelta(days=3)); self.assertEqual(self.count(),1)
    def test_once(self):
        self.add(repeat='once',start_date='2026-11-01')
        f.tick(self.created.replace(hour=8)); self.assertEqual(self.count(),0)
        f.tick(self.created.replace(hour=8)+timedelta(days=1)); self.assertEqual(self.count(),1)
        f.tick(self.created.replace(hour=8)+timedelta(days=2)); self.assertEqual(self.count(),1)
    def test_overnight(self):
        with patch('agents.family.now',return_value=self.created):
            f.add_schedule(self.a['token'],self.mid,'晚间关怀','护理','22:00',repeat='interval',end_clock='02:00',interval_minutes=60,start_date='2026-10-31',end_date='2026-10-31')
        f.tick(self.created.replace(hour=1)+timedelta(days=1)); self.assertEqual(self.count(),1)
        f.tick(self.created.replace(hour=3)+timedelta(days=1)); self.assertEqual(self.count(),1)
    def test_invalid_plan(self):
        with self.assertRaises(ValueError): self.add(start_date='2026-11-02',end_date='2026-11-01')
        with self.assertRaises(ValueError): self.add(repeat='interval',end_clock='10:00',interval_minutes=0)
        with self.assertRaises(ValueError): self.add(repeat='weekly',weekdays=[])
    def test_legacy_daily_compatible(self):
        sid=self.add()
        with f.connect() as db: db.execute('UPDATE schedules SET settings=NULL WHERE id=?',(sid,))
        f.tick(self.created.replace(hour=8)); self.assertEqual(self.count(),1)

if __name__=='__main__': unittest.main(verbosity=2)
