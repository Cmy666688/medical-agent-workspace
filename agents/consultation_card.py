"""Deterministic information checking, with no model calls or clinical conclusions.

Pure operations here; account-owned persistence lives in conversations.py.
"""
import copy
import re
from .risk_workflow import information

FIELDS = {
    'complaint': '主要不适', 'duration': '持续时间', 'severity': '不适程度',
    'associated': '伴随情况', 'allergies': '药物过敏史', 'medications': '当前用药',
}
STATUSES = ('未提供', '不清楚', '待确认', '已确认')
UNKNOWN = re.compile(r'^(?:不清楚|不知道|不确定|记不清|未知)$')


def empty_card():
    return {key: dict(value='', status='未提供', confirmed=False, sources=[], pending=None)
            for key in FIELDS}


def _source(request_id, quote, origin='用户输入'):
    return dict(request_id=request_id, quote=quote, origin=origin)


def extract(text, request_id):
    """Reuse existing symptom/negation/time rules; only take explicitly stated facts."""
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ValueError('问诊原话需为 1～10000 字')
    if not isinstance(request_id, str) or not request_id or len(request_id) > 100:
        raise ValueError('来源请求编号无效')
    result = {}

    def put(key, value):
        value = value.strip()
        if value:
            unknown = bool(UNKNOWN.fullmatch(value))
            result[key] = dict(value='不清楚' if unknown else value,
                               status='不清楚' if unknown else '待确认',
                               sources=[_source(request_id, text)])

    known = information(text)
    # A phrase introduced as an accompanying symptom must not become the chief complaint.
    chief_text = re.split(r'(?:伴有|伴随|伴发|同时有|另外还有)', text, maxsplit=1)[0]
    chief = information(chief_text)['reported_symptoms']
    if chief:
        put('complaint', '、'.join(chief))
    else:
        match = re.search(r'(?:主要不适|主要症状|主诉)[：:为是\s]*(.+?)(?=[，,。；;]|$)', text)
        if match: put('complaint', match.group(1))
    labels = {'持续时间：': 'duration', '你描述的程度：': 'severity', '伴随情况：': 'associated'}
    for line in known['provided_info']:
        for prefix, key in labels.items():
            if line.startswith(prefix): put(key, line[len(prefix):])
    associated = re.search(r'(?:伴有|伴随|伴发|同时有|另外还有)[：:为是\s]*(.+?)(?=[，,。；;]|$)', text)
    if associated: put('associated', associated.group(1))
    # Dedicated labels allow values outside the deliberately small symptom dictionary.
    for label, key in [(label, key) for key, label in FIELDS.items() if key != 'complaint']:
        match = re.search(re.escape(label) + r'[：:]\s*(.+?)(?=[，,。；;]|$)', text)
        if match: put(key, match.group(1))
    for label, key in [('症状持续时间', 'duration'), ('持续时间', 'duration'), ('程度', 'severity'),
                       ('伴随情况', 'associated'), ('药物过敏史', 'allergies'), ('过敏史', 'allergies'),
                       ('当前用药', 'medications')]:
        match = re.search(re.escape(label) + r'(?:[：:为是]|\s)*(不清楚|不知道|不确定|记不清|未知)', text)
        if match: put(key, match.group(1))
    if re.search(r'(?:无|没有)(?:已知的?|任何)?(?:药物过敏(?:史)?|过敏史)|(?:无|没有)已知药物过敏', text):
        put('allergies', '无已知药物过敏')
    else:
        match = re.search(r'(?:对(.{1,40}?)过敏|(?:药物过敏史|过敏药物)[：:]\s*([^，,。；;]+))', text)
        if match: put('allergies', match.group(1) or match.group(2))
    if re.search(r'(?:现在|目前|当前)?(?:没有|没|未)(?:在|有)?(?:吃药|用药|服药)|未服用药物', text):
        put('medications', '目前未用药')
    else:
        match = re.search(r'(?:现在|目前|当前)(?:正在|在)?(?:服用|用药[：:]?|吃)([^，,。；;]+)', text)
        if match: put('medications', match.group(1))
    return result


def merge(card, extracted):
    """Protect confirmed values, including a user-confirmed unknown answer."""
    result = copy.deepcopy(card)
    for key, candidate in extracted.items():
        field = result[key]
        if field['value'] == candidate['value']:
            for source in candidate['sources']:
                if source not in field['sources']: field['sources'].append(source)
            continue
        if field['confirmed']:
            field['pending'] = copy.deepcopy(candidate)
        else:
            result[key] = dict(candidate, confirmed=False, pending=None)
    return result


def confirm(card, edits, request_id):
    """Explicit user decisions replace values and keep all original provenance."""
    if set(edits) != set(FIELDS): raise ValueError('请提交完整的六项核对信息')
    result = copy.deepcopy(card)
    for key, item in edits.items():
        value = item['value'].strip()
        status = item['status']
        if status not in STATUSES or len(value) > 1000: raise ValueError('核对信息格式不正确')
        if status == '未提供': value = ''
        elif status == '不清楚': value = '不清楚'
        elif not value: raise ValueError(FIELDS[key] + '：请填写内容，或选择未提供/不清楚')
        elif UNKNOWN.fullmatch(value): status, value = '不清楚', '不清楚'
        field = result[key]
        changed = field['value'] != value
        if changed or status != field['status'] or field['pending'] or (not field['confirmed'] and status in ('已确认', '不清楚')):
            if field['pending'] and value == field['pending']['value']:
                for source in field['pending']['sources']:
                    if source not in field['sources']: field['sources'].append(source)
            field['sources'].append(_source(request_id, item['value'], '用户核对编辑' if changed else '用户核对确认'))
        field.update(value=value, status=status, confirmed=status in ('已确认', '不清楚'), pending=None)
    return result


def same_decisions(card, edits):
    """Idempotent retry after a previous successful save, without new edit provenance."""
    try:
        return confirm(card, edits, 'unchanged') == card
    except (ValueError, KeyError, TypeError):
        return False


def context_from_card(card, context):
    """Fill otherwise missing personal context using explicitly confirmed answers."""
    result = dict(context)
    for key in ('allergies', 'medications'):
        field = card[key]
        if not result.get(key) and field['confirmed']:
            result[key] = field['value']
    return result


def summary(card, version):
    """Fixed Markdown template: facts and missing items only, never model-generated."""
    def safe(value):
        # Keep a user's text inside plain, escaped Markdown, including raw HTML.
        return re.sub(r'([\\`*_{}\[\]()#+.!|<>~-])', r'\\\1', str(value)).replace('\n', ' ')

    lines = ['# 问诊信息摘要', '', f'核对卡版本：{version}', '',
             '本摘要仅整理用户提供及核对的信息。', '', '## 已有信息', '']
    for key, label in FIELDS.items():
        field = card[key]
        if field['status'] != '未提供':
            lines.append(f"- {label}：{safe(field['value'])}（{field['status']}）")
    if not any(f['status'] != '未提供' for f in card.values()): lines.append('- 暂无已提供的信息。')
    lines += ['', '## 待补充与待核对', '']
    todo = []
    for key, label in FIELDS.items():
        field = card[key]
        if field['status'] != '已确认': todo.append(f"- {label}：{field['status']}")
        if field['pending']: todo.append(f"- {label}有新描述待核对：{safe(field['pending']['value'])}；已保存值仍为 {safe(field['value'])}。")
    lines += todo or ['- 六项信息均已确认。']
    lines += ['', '## 字段来源', '']
    for key, label in FIELDS.items():
        lines += [f'### {label}', '']
        field = card[key]
        sources = field['sources'] + (field['pending']['sources'] if field['pending'] else [])
        for source in sources:
            lines.append(f"- 请求 {safe(source['request_id'])} · {source['origin']} · 原话：{safe(source['quote'])}")
        if not sources: lines.append('- 尚无来源。')
        lines.append('')
    return '\n'.join(lines)
