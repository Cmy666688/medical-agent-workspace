"""Offline migration and invitations, using isolated synthetic identities."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

Path('runtime').mkdir(exist_ok=True)
runtime=Path(tempfile.mkdtemp(prefix='shared_store_test_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
os.environ['MEDICAL_API_CONFIG']=str(runtime/'no-api.toml')

from agents import family,accounts,conversations,telemetry,user_management
from agents.storage_paths import user_data_root
from merge_user_data import build_merge,inspect
from streamlit.testing.v1 import AppTest


class Tests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(dir=runtime))
        self.local=self.root/'local';self.public=self.root/'public'
        self.local.mkdir();self.public.mkdir()
        self.a=self.seed(self.local,'abc','Local-password-123',admin=True)
        self.b=self.seed(self.public,'abc','Public-password-123')

    def databases(self,root):
        from contextlib import ExitStack
        stack=ExitStack()
        for module,name in [(family,'family.sqlite'),(conversations,'conversations.sqlite'),(telemetry,'monitor.sqlite')]:
            stack.enter_context(patch.object(module,'DB',root/name))
        return stack

    def seed(self,root,name,password,admin=False):
        with self.databases(root):
            result=accounts.register(name,password,'测试成员')
            token=result['token']
            if admin:user_management.bootstrap_admin(name)
            group=family.create_family('测试家庭','本人',token)
            conversation=conversations.create(token)
            conversations.ingest_card(token,conversation,'source','咳嗽3天')
            conversations.append(token,conversation,dict(request='request-'+conversation,question='仅此账号的测试原话',answer='合成测试答复',trace=[],evidences=[],conflicts=[]))
            conversations.select_active(token,conversation)
            telemetry.bind_user(conversation,'member_'+family.identity_profile(token)['id'])
            telemetry.record(conversation,'request-'+conversation,'request',mode='local')
            return dict(token=token,group=group,conversation=conversation)

    def merge(self):
        target=self.root/'shared'
        build_merge(self.local,self.public,target,rename_public={'abc':'abc_public'})
        return target

    def test_merge_preserves_accounts_admin_passwords_and_owner_checks(self):
        self.assertEqual(inspect(self.local,self.public)['username_conflicts'],['abc'])
        target=self.merge()
        with self.databases(target):
            admin=accounts.login('abc','Local-password-123')
            member=accounts.login('abc_public','Public-password-123')
            self.assertEqual(family.identity_profile(admin)['role'],'admin')
            self.assertEqual(family.identity_profile(member)['role'],'user')
            self.assertEqual(conversations.active(admin),self.a['conversation'])
            self.assertEqual(conversations.active(member),self.b['conversation'])
            self.assertTrue(conversations.load_card(admin,self.a['conversation'])['version'])
            with self.assertRaises(PermissionError):conversations.load(member,self.a['conversation'])
            self.assertTrue(family.identity_profile(self.a['token']))
            self.assertTrue(family.identity_profile(self.b['token']))
        # Each original database remains unchanged, including the old username.
        with self.databases(self.public):self.assertTrue(accounts.login('abc','Public-password-123'))

    def test_existing_local_invite_works_for_original_public_account(self):
        target=self.merge()
        with self.databases(target):
            joined=family.join_family('  '+self.a['group']['invite']+'\n','家人',self.b['token'])
            members=family.members(self.a['group']['token'])
            self.assertEqual(len(members),2)
            self.assertEqual(family.profile(joined['token'])['group_id'],family.profile(self.a['group']['token'])['group_id'])
            with self.assertRaises(PermissionError):family.health_records(joined['token'],family.profile(self.a['group']['token'])['id'])
            family.join_family(self.a['group']['invite'],'重复点击',self.b['token'])
            self.assertEqual(len(family.members(self.a['group']['token'])),2)

    def test_unresolved_conflict_fails_without_overwriting_source_or_target(self):
        target=self.root/'shared'
        with self.assertRaises(ValueError):build_merge(self.local,self.public,target)
        self.assertFalse(target.exists())
        with self.databases(self.local):self.assertTrue(accounts.login('abc','Local-password-123'))
        self.merge()
        with self.assertRaises(ValueError):build_merge(self.local,self.public,target,rename_public={'abc':'abc_public'})

    def test_services_resolve_same_explicit_store_but_isolated_tests_do_not(self):
        target=self.merge()
        with patch.dict(os.environ,MEDICAL_USER_DATA_DIR=str(target)):
            for service in (self.local,self.public):
                with patch.dict(os.environ,MEDICAL_RUNTIME_DIR=str(service)):
                    self.assertEqual(user_data_root(),target.resolve())
        with patch.dict(os.environ,MEDICAL_RUNTIME_DIR=str(self.root/'unrelated-demo')):
            self.assertEqual(user_data_root(),(self.root/'unrelated-demo').resolve())

    def test_invite_panel_never_shows_another_household_or_rotated_code(self):
        with self.databases(self.local):
            second=family.create_family('第二家庭','我',self.a['token'])
            script='''
import streamlit as st
from family_invite_ui import invitation_panel
invitation_panel(st.session_state.family_token)
'''
            app=AppTest.from_string(script)
            app.session_state.family_token=second['token']
            app.session_state.new_family_credentials={'invite':self.a['group']['invite']}
            app.run()
            self.assertFalse(app.exception,[x.message for x in app.exception])
            self.assertFalse(app.code)
            app.session_state.new_family_credentials={'invite':second['invite']}
            app.run()
            self.assertEqual(app.code[0].value,second['invite'])
            family.rotate_invite(second['token'])
            app.run()
            self.assertFalse(app.code)

    def test_public_admin_access_and_join_form_use_the_same_family_store(self):
        target=self.merge()
        with self.databases(target),patch.dict(os.environ,MEDICAL_PUBLIC_MODE='1'):
            admin=AppTest.from_file('app.py',default_timeout=30)
            admin.session_state.personal_token=self.a['token']
            admin.run();admin.switch_page('app_pages/users.py').run()
            self.assertFalse(admin.exception,[x.message for x in admin.exception])
            member=AppTest.from_file('app.py',default_timeout=30)
            member.session_state.personal_token=self.b['token']
            member.run();member.switch_page('app_pages/family_home.py').run()
            next(w for w in member.get('segmented_control') if w.label=='家庭操作').set_value('加入家庭').run()
            invite=next(w for w in member.text_input if w.label=='家庭邀请码')
            invite.set_value('incorrect-invitation')
            next(w for w in member.button if w.label=='加入家庭').click().run()
            self.assertEqual(next(w for w in member.text_input if w.label=='家庭邀请码').value,'incorrect-invitation')
            next(w for w in member.text_input if w.label=='家庭邀请码').set_value(self.a['group']['invite'])
            next(w for w in member.button if w.label=='加入家庭').click().run()
            self.assertFalse(member.exception,[x.message for x in member.exception])
            self.assertEqual(len(family.members(self.a['group']['token'])),2)
            with self.assertRaises(ValueError):member.switch_page('app_pages/users.py')


if __name__=='__main__':unittest.main(verbosity=2)
