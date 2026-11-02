"""A small, read-only execution timeline for real coordinator events and traces."""
import math
import re
import streamlit as st
from result_ui import friendly_error


def measured(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def duration_label(value):
    value = measured(value)
    if value is None: return '耗时未记录'
    if value < 1: return '<1 ms'
    return f'{value:,.0f} ms' if value < 1000 else f'{value / 1000:.2f} s'


class TimelineState:
    """Repeated completion notifications update a node instead of creating copies."""
    def __init__(self): self.nodes = {}

    def update(self, event):
        name = str(event.get('agent', ''))
        if not name: return
        status = event.get('status', '执行中')
        current = self.nodes.setdefault(name, dict(agent=name, status=status, duration_ms=None, error=''))
        terminal = current['status'] in ('完成', '失败')
        if terminal and status == '执行中': return
        current['status'] = status
        duration = measured(event.get('duration_ms'))
        if duration is not None: current['duration_ms'] = duration
        if event.get('error'): current['error'] = str(event['error'])

    def rows(self): return [dict(node) for node in self.nodes.values()]

    def fail_unfinished(self):
        for node in self.nodes.values():
            if node['status'] == '执行中': node['status'] = '失败'


def render_timeline(rows, *, live=False):
    if not rows: return
    done = sum(row.get('status') == '完成' for row in rows)
    failed = sum(row.get('status') == '失败' for row in rows)
    with st.container(border=True):
        st.subheader('执行时间轴', icon=':material/timeline:')
        st.caption(f'{len(rows)} 个步骤 · {done} 已完成' + (f' · {failed} 未成功' if failed else '') + (' · 协作进行中' if live else ''))
        # Native step containers inherit the current theme and draw the connector.
        # Do not use a context manager: it would mark a live step complete on exit.
        for row in rows:
            status = row.get('status', '执行中')
            state = 'complete' if status == '完成' else ('error' if status == '失败' else 'running')
            name = re.sub(r'([\\`*_{}\[\]()#!|<>])', r'\\\1', str(row.get('agent', '协作步骤')))
            step = st.status(name, state=state, type='step', expanded=True)
            detail = '正在处理' if status == '执行中' else duration_label(row.get('duration_ms'))
            step.caption(str(status) + ' · ' + detail)
            if row.get('error'): step.caption(friendly_error(row['error']))
        st.caption('检索与用药核对可并行执行，各步骤耗时不可直接相加。')
