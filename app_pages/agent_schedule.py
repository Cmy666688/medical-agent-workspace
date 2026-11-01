import json
from datetime import datetime,timedelta,time
import streamlit as st
from agents.household_agents import tools as store
from agents.family import REMINDER_TYPES
from family_ui import require_member,target_picker,inbox

st.caption('医知协作 / 家庭组')
st.title('关怀提醒',icon=':material/alarm:')
st.write('设置不同类型的关怀事项，按日期、星期或每日时间段提醒。')
person=require_member(); token=st.session_state.family_token
heartbeat=store.worker_status()
if heartbeat:
    st.caption('后台调度最近心跳：'+heartbeat[:19].replace('T',' ')+'（北京时间）')
    if (store.now()-datetime.fromisoformat(heartbeat)).total_seconds()>60: st.warning('后台调度可能未运行，关闭页面后无法保证到期提醒。')
else: st.warning('后台调度尚无心跳，请通过启动项目.ps1 启动完整服务。')
st.caption('北京时间；事项与频次由成员填写，不自动决定药物或剂量。提醒为站内待办，依赖电脑和后台运行。')
inbox()
target=target_picker('can_manage')
patterns={'每天一次':'daily','仅提醒一次':'once','每周指定日':'weekly','每日时间段内重复':'interval'}
pattern=st.selectbox('重复方式',list(patterns))
limited=st.checkbox('限定生效日期范围',value=False,disabled=pattern=='仅提醒一次')
today=store.now().date(); labels=['周一','周二','周三','周四','周五','周六','周日']
with st.form('create_schedule'):
    title=st.text_input('提醒内容',placeholder='例如：按医嘱服药 / 测量血压 / 复诊准备',max_chars=150)
    kind=st.selectbox('提醒类型',REMINDER_TYPES)
    if pattern=='仅提醒一次':
        begin=st.date_input('提醒日期',value=today,min_value=today); end=begin
    elif limited:
        cols=st.columns(2)
        begin=cols[0].date_input('开始日期',value=today)
        end=cols[1].date_input('结束日期',value=today+timedelta(days=30))
    else: begin=today; end=None
    if pattern=='每日时间段内重复':
        cols=st.columns(2)
        clock=cols[0].time_input('每日开始时间',value=time(8,0))
        finish=cols[1].time_input('每日结束时间',value=time(20,0))
        interval=st.number_input('间隔分钟',min_value=5,max_value=1440,value=60,step=5)
        st.caption('结束早于开始表示跨午夜；日期以时间段开始当天为准。错过时段不集中补发，仅在当前时段投递最近一次到期提醒。')
    else:
        clock=st.time_input('提醒时间',value=time(8,0)); finish=None; interval=60
    weekdays=st.multiselect('每周提醒日',labels,default=labels[:5]) if pattern=='每周指定日' else []
    if st.form_submit_button('创建提醒计划',type='primary'):
        try:
            store.add_schedule(token,target['id'],title,kind,clock.strftime('%H:%M'),start_date=begin,end_date=end,repeat=patterns[pattern],end_clock=finish.strftime('%H:%M') if finish else None,interval_minutes=int(interval),weekdays=[labels.index(x) for x in weekdays])
            st.success('提醒计划已创建')
        except (ValueError,PermissionError) as exc: st.error(str(exc))
st.subheader(target['name']+'的提醒计划')
for task in store.schedules(token,target['id']):
    settings=json.loads(task['settings'] or '{}'); repeat=settings.get('repeat','daily')
    with st.container(border=True):
        st.write(task['title'])
        mode={'daily':'每天','once':'单次','weekly':'每周','interval':'时间段重复'}[repeat]
        timing=task['clock']
        if repeat=='interval': timing+='～'+settings['end_clock']+f"，每 {settings['interval_minutes']} 分钟"
        if repeat=='weekly': timing+=' · '+'、'.join(labels[x] for x in settings['weekdays'])
        st.caption(f"{task['kind']} · {mode} {timing} · {'启用' if task['active'] else '暂停'}")
        if settings.get('start_date'): st.caption('生效日期：'+settings['start_date']+' 至 '+(settings.get('end_date') or '长期'))
        if st.button('暂停' if task['active'] else '恢复',key='toggle_'+task['id']):
            store.toggle_schedule(token,task['id'],not task['active']); st.rerun()
