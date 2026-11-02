"""三个持久化工具 Agent，界面与调度器共享同一业务权限校验。"""
import time
import uuid
from . import family
from .telemetry import record

class HouseholdAgent:
    name=''
    actions=()
    def run(self,action,*args,**kwargs):
        if action not in self.actions: raise ValueError('不支持的 Agent 操作')
        started=time.perf_counter(); status='完成'; error=''; member='unknown'
        try:
            if args:
                try: member=family.profile(args[0])['id']
                except PermissionError: pass
            value=getattr(family,action)(*args,**kwargs)
            if action in ('create_family','join_family'): member=family.profile(value['token'])['id']
            return value
        except Exception as exc:
            status='失败'; error=type(exc).__name__; raise
        finally:
            request=uuid.uuid4().hex[:12]; duration=(time.perf_counter()-started)*1000
            record('family_'+member,request,'agent',agent=self.name,status=status,error=error,latency_ms=duration,user_id=member,action=action)
            record('family_'+member,request,'request',mode='family',latency_ms=duration,user_id=member)

class FamilyAgent(HouseholdAgent):
    name='家庭协作 Agent'
    actions=('create_family','join_family','set_grant','rotate_invite','send_message','set_reminder_delegates','request_reminder_access','respond_reminder_access')

class ScheduleAgent(HouseholdAgent):
    name='定时关怀 Agent'
    actions=('add_schedule','toggle_schedule','complete_notice')

class CareAgent(HouseholdAgent):
    name='亲属照护 Agent'
    actions=('add_measurement','request_checkin','health_records')

class Tools:
    def __getattr__(self,action):
        for cls in (FamilyAgent,ScheduleAgent,CareAgent):
            if action in cls.actions: return lambda *a,**kw:cls().run(action,*a,**kw)
        if action in ('profile','members','grants_given','messages','schedules','notices','audit_log','tick','now','worker_status','poll_reminders','reminder_requests','reminder_request_status'):
            return getattr(family,action)
        raise AttributeError(action)

tools=Tools()
