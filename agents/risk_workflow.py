"""Readable risk information collection and optional evidence-constrained model review."""
import asyncio,copy,re,time
from .llm import LLMClient,LLMError
from .specialists import review

def is_denied(text,position):
    prefix=re.split(r'[，,。；;！？!?]',text[:position])[-1][-16:]
    if re.search(r'(不是没有|并非没有)\s*$',prefix): return False
    return bool(re.search(r'(?:没有|无|否认|不伴|未出现)(?:明显的?|任何|持续性|相关的|\s)*$',prefix))

def information(text):
    duration=re.search(r'(?:半|[零一二三四五六七八九十百两\d.]+)\s*(?:个?小时|天|日|周|个?月|年)',text)
    severity=re.search(r'不是很严重|不太严重|不严重|较轻|轻微|轻度|中度|严重|剧烈|加重',text)
    associated=re.search(r'(?:无|没有|不伴)(?:其他)?(?:伴随|伴发|其它)?症状',text)
    aliases={'鼻痒':('鼻痒','鼻子痒','鼻子发痒'),'咳嗽':('咳嗽',),'头痛':('头痛',),'发热':('发热','发烧'),'胸痛':('胸痛',),'呼吸困难':('呼吸困难',),'恶心':('恶心',),'头晕':('头晕',),'腹痛':('腹痛',),'喷嚏':('喷嚏',),'咽痛':('咽痛',)}
    present=[]; denied=[]
    for name,terms in aliases.items():
        for term in terms:
            for match in re.finditer(re.escape(term),text):
                negative=is_denied(text,match.start())
                destination=denied if negative else present
                if name not in destination: destination.append(name)
    provided=[]; followup=[]
    if present: provided.append('你描述的症状：'+'、'.join(present))
    if denied: provided.append('你明确否认的症状：'+'、'.join(denied))
    if duration: provided.append('持续时间：'+duration.group())
    else: followup.append('这些症状持续了多久？')
    if severity: provided.append('你描述的程度：'+severity.group())
    else: followup.append('不适程度如何，是否影响日常活动或持续加重？')
    if associated: provided.append('伴随情况：'+associated.group())
    else: followup.append('是否还有其他伴随症状？没有也请说明。')
    return dict(provided_info=provided,followup=followup,reported_symptoms=present,denied_symptoms=denied,input_snapshot=text)

async def assess(question,config,session,client_factory=LLMClient,retrieval=None,context=None,on_event=None):
    from .coordinator import RiskAgent,MedicationAgent,EducationAgent,Coordinator
    started=time.perf_counter()
    result=await RiskAgent().run(dict(query=question))
    if on_event: on_event(dict(agent='风险评估 Agent',status=result.status,output=copy.deepcopy(result.output)))
    evidence=[]
    if result.status=='完成' and retrieval is not None:
        request='risk-'+str(time.time_ns())
        consultation=dict(query=question,context=context or {},risk_alert=dict(red_flags=result.output['red_flags'],recommendation=result.output['recommendation']))
        tick=time.perf_counter()
        found,medication=await asyncio.gather(asyncio.to_thread(Coordinator(retrieval).search,question),MedicationAgent().run(consultation),return_exceptions=True)
        if not isinstance(medication,Exception): result.output['medication_check']=medication.output
        if isinstance(found,Exception): result.output.update(retrieval_status='failed',retrieval_error=type(found).__name__)
        else:
            from .telemetry import record
            evidence=found['evidences']
            result.output.update(retrieval_status='completed' if evidence else 'no_hit',evidences=evidence)
            record(session,request,'retrieval',latency_ms=found.get('latency_ms',(time.perf_counter()-tick)*1000),no_hit=not evidence,cache_hit=found.get('cache_hit',False))
            education=await EducationAgent().run(evidence)
            result.output['education']=education.output
    result.output['online_status']='not_requested'
    if result.status!='完成' or result.output.get('red_flags'):
        result.output['online_status']='skipped_urgent' if result.output.get('red_flags') else 'not_requested'
    elif config.api_key:
        try:
            value=await review(client_factory(config),'风险复核 Agent',dict(query=question,known_information=result.output['provided_info'],missing_information=result.output['followup']),evidence,session,'risk-'+str(time.time_ns()))
            result.output.update(online_status='completed',model_review=value)
        except LLMError as exc: result.output.update(online_status='failed',review_error=str(exc))
    else: result.output['online_status']='not_configured'
    result.duration_ms=(time.perf_counter()-started)*1000
    return result
