"""Account administration and conversation isolation, using synthetic accounts only."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

Path('runtime').mkdir(exist_ok=True)
runtime=Path(tempfile.mkdtemp(prefix='user_management_test_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'no-api.toml')

from agents import accounts, family, conversations as store, user_management as users
from agents import telemetry
from agents.llm import LLMConfig, reserve, quota_usage
from streamlit.testing.v1 import AppTest


def sample(question):
    return dict(request=uuid.uuid4().hex,question=question,card_original=question,
                answer='合成的隔离测试答复',trace=[],evidences=[],conflicts=[])


class Tests(unittest.TestCase):
    def setUp(self):
        self.admin_name='admin_'+uuid.uuid4().hex[:8]
        self.name='user_'+uuid.uuid4().hex[:8]
        self.password='User-management-test-123'
        self.admin=accounts.register(self.admin_name,self.password,'管理员')['token']
        self.result=accounts.register(self.name,self.password,'普通用户')
        self.token=self.result['token']
        self.identity=family.identity_profile(self.token)['id']
        users.bootstrap_admin(self.admin_name)

    def page(self,token,page='app_pages/agent_consultation.py'):
        app=AppTest.from_file('app.py',default_timeout=30)
        app.session_state.personal_token=token
        app.run(); app.switch_page(page).run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        return app

    def test_default_role_and_all_admin_operations_are_guarded(self):
        self.assertEqual(family.identity_profile(self.token)['role'],'user')
        for action in [lambda:users.listing(self.token),lambda:users.audit_log(self.token),
                       lambda:users.update(self.token,self.identity,display='自己升级',role='admin',enabled=True),
                       lambda:users.revoke_sessions(self.token,self.identity),
                       lambda:users.create(self.token,'forbidden_user',self.password,'禁止')]:
            with self.assertRaises(PermissionError):action()
        with self.assertRaises(ValueError):users.bootstrap_admin('missing_'+uuid.uuid4().hex[:8])

    def test_disable_revokes_access_and_enable_does_not_resurrect_sessions(self):
        key=store.create(self.token)
        group=family.create_family('合成家庭','我',self.token)
        users.update(self.admin,self.identity,display='停用用户',role='user',enabled=False)
        for action in [lambda:family.identity_profile(self.token),lambda:store.load(self.token,key),
                       lambda:family.profile(group['token']),lambda:accounts.login(self.name,self.password),
                       lambda:accounts.recover(self.name,self.result['recovery'],self.password+'new')]:
            with self.assertRaises(PermissionError):action()
        users.update(self.admin,self.identity,display='恢复用户',role='user',enabled=True)
        with self.assertRaises(PermissionError):family.identity_profile(self.token)
        restored=accounts.login(self.name,self.password)
        self.assertTrue(store.exists(restored,key))

    def test_admin_cannot_read_other_users_conversation_or_self_lock(self):
        key=store.create(self.token);store.append(self.token,key,sample('仅本人可见的测试原话'))
        with self.assertRaises(PermissionError):store.load(self.admin,key)
        owner=family.identity_profile(self.admin)['id']
        for role,enabled in [('user',True),('admin',False)]:
            with self.assertRaises(ValueError):users.update(self.admin,owner,display='管理员',role=role,enabled=enabled)
        rows=users.listing(self.admin,self.name)
        self.assertEqual(rows[0]['username'],self.name)
        self.assertEqual(set(rows[0]),{'identity','username','display','created','role','enabled','sessions'})
        self.assertNotIn('仅本人可见',str(rows))

    def test_role_update_revoke_and_creation_audit(self):
        users.update(self.admin,self.identity,display='新管理员',role='admin',enabled=True)
        with self.assertRaises(PermissionError):users.listing(self.token)
        promoted=accounts.login(self.name,self.password)
        self.assertTrue(users.listing(promoted))
        users.revoke_sessions(self.admin,self.identity)
        with self.assertRaises(PermissionError):users.listing(promoted)
        name='created_'+uuid.uuid4().hex[:8]
        recovery=users.create(self.admin,name,self.password,'创建的用户')
        new=accounts.login(name,self.password)
        self.assertEqual(family.identity_profile(new)['role'],'user')
        with family.connect() as db:
            row=db.execute('SELECT * FROM accounts WHERE username=?',(name,)).fetchone()
            self.assertNotIn(self.password,dict(row).values())
            self.assertNotIn(recovery,dict(row).values())
        self.assertTrue(any(x['action']=='account.create' for x in users.audit_log(self.admin)))

    def test_active_selection_and_continuation_are_owned_durable_snapshots(self):
        key=store.create(self.token);first=sample('我咳嗽3天了')
        store.append(self.token,key,first,{'age':31})
        card=store.ingest_card(self.token,key,first['request'],first['question'])
        reserve(key,90,LLMConfig(session_tokens=100))
        store.select_active(self.token,key)
        newer=store.create(self.token)
        fresh=accounts.login(self.name,self.password)
        self.assertEqual(store.active(fresh),key)
        for action in [lambda:store.select_active(self.admin,key),lambda:store.continue_from(self.admin,key)]:
            with self.assertRaises(PermissionError):action()
        continuation=store.continue_from(fresh,key)
        copy=store.load(fresh,continuation)
        self.assertEqual(copy['turns'],[first]);self.assertEqual(copy['context'],{'age':31})
        self.assertEqual(store.load_card(fresh,continuation)['fields'],card['fields'])
        self.assertEqual(quota_usage(continuation),0);self.assertEqual(quota_usage(key),90)
        store.append(fresh,continuation,sample('继续补充信息'))
        self.assertEqual(len(store.load(fresh,key)['turns']),1)
        self.assertEqual(len(store.load(fresh,continuation)['turns']),2)
        self.assertEqual(store.load(fresh,newer)['turns'],[])

    def test_account_switch_discards_stale_history_card_and_vision(self):
        key=store.create(self.token);store.append(self.token,key,sample('甲用户的合成隐私'))
        group=family.create_family('甲用户的家庭','本人',self.token)
        app=self.page(self.token)
        app.session_state.new_family_credentials={'invite':group['invite']}
        app.session_state.family_invites={'test':{'invite':group['invite']}}
        app.session_state.vision_handoff='甲用户的图片观察'
        app.session_state.agent_tests={'risk':{'output':'甲用户结果'}}
        app.session_state.personal_token=self.admin  # stale browser state must not migrate
        app.run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertEqual(app.session_state.turns,[])
        self.assertNotIn('vision_handoff',app.session_state)
        self.assertEqual(app.session_state.agent_tests,{})
        self.assertEqual(app.session_state.family_token,'')
        self.assertNotIn('new_family_credentials',app.session_state)
        self.assertNotIn('family_invites',app.session_state)
        self.assertEqual(store.load(self.token,key)['turns'][0]['question'],'甲用户的合成隐私')
        self.assertNotIn('甲用户',str(store.listing(self.admin)))

    def test_continue_ui_and_new_login_restore_selected_conversation(self):
        key=store.create(self.token);store.append(self.token,key,sample('第一段测试'))
        second=store.create(self.token);store.append(self.token,second,sample('第二段测试'))
        app=self.page(self.token,'app_pages/conversations.py')
        app.button(key='continue_'+key).click().run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertEqual(app.session_state.conversation_id,key)
        self.assertIn('第一段测试',[m.content for m in app.session_state.history.messages])
        fresh=self.page(accounts.login(self.name,self.password))
        self.assertEqual(fresh.session_state.conversation_id,key)

    def test_user_management_page_is_guarded_and_editable(self):
        ordinary=self.page(self.token)
        with self.assertRaises(ValueError):ordinary.switch_page('app_pages/users.py')
        with self.assertRaises(ValueError):ordinary.switch_page('app_pages/monitor.py')
        app=self.page(self.admin,'app_pages/users.py')
        app.text_input[0].set_value(self.name).run()
        next(x for x in app.text_input if x.label=='称呼').set_value('已修改称呼')
        next(x for x in app.button if x.label=='保存用户设置').click().run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertEqual(family.identity_profile(self.token)['display'],'已修改称呼')
        self.assertFalse(app.json)

    def test_recent_activity_uses_authenticated_owner_in_both_modes(self):
        telemetry.bind_user('isolated_'+self.identity,'member_'+self.identity)
        telemetry.record('isolated_'+self.identity,'private-request','request',mode='local')
        self.assertEqual(telemetry.personal_events(self.token)[0]['request'],'private-request')
        self.assertNotIn('private-request',[x['request'] for x in telemetry.personal_events(self.admin)])

    def test_quota_continuation_button_preserves_history_and_sources(self):
        key=store.create(self.token)
        item=sample('我咳嗽3天了')
        store.append(self.token,key,item)
        card=store.ingest_card(self.token,key,item['request'],item['question'])
        reserve(key,95,LLMConfig(session_tokens=100))
        with patch('ui.llm_config',return_value=LLMConfig(api_key='synthetic-only',session_tokens=100,budget_tokens=20)):
            app=self.page(self.token)
            app.button(key='continue_with_context').click().run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertNotEqual(app.session_state.conversation_id,key)
        self.assertEqual(app.session_state.turns,[item])
        self.assertIn('我咳嗽3天了',[m.content for m in app.session_state.history.messages])
        self.assertEqual(store.load_card(self.token,app.session_state.conversation_id)['fields'],card['fields'])
        self.assertEqual(len(store.load(self.token,key)['turns']),1)

    def test_continued_message_uses_only_owners_history(self):
        a=store.create(self.token);store.append(self.token,a,sample('普通用户自己的原话'))
        b=store.create(self.admin);store.append(self.admin,b,sample('管理员的其他原话'))
        app=self.page(self.token)
        observed=[]
        async def run(question,context,history,session,config,**kwargs):
            observed.extend(m.content for m in history.messages)
            return dict(request=kwargs['request_id'],answer='新的隔离测试答复',trace=[],evidences=[],conflicts=[])
        with patch('agents.coordinator.Coordinator.run',side_effect=run):
            app.chat_input[0].set_value('补充新的描述').run()
        self.assertFalse(app.exception,[x.message for x in app.exception])
        self.assertIn('普通用户自己的原话',observed)
        self.assertNotIn('管理员的其他原话',observed)
        self.assertEqual(len(store.load(self.token,a)['turns']),2)
        self.assertEqual(len(store.load(self.admin,b)['turns']),1)


if __name__=='__main__':unittest.main(verbosity=2)
