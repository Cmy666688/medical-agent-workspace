import asyncio
import copy
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from .llm import LLMClient, LLMConfig, LLMError, ConsultationSummary, EvidenceSummary
from langchain_core.chat_history import InMemoryChatMessageHistory
from .telemetry import record

@dataclass
class AgentResult:
    agent: str
    status: str
    duration_ms: float
    output: dict = field(default_factory=dict)
    error: str = ''

class BaseAgent:
    name = ''
    async def run(self, *args):
        start = time.perf_counter()
        try:
            value = await asyncio.to_thread(self.execute, *args)
            return AgentResult(self.name, '完成', (time.perf_counter()-start)*1000, value)
        except Exception as exc:
            return AgentResult(self.name, '失败', (time.perf_counter()-start)*1000, error=type(exc).__name__)

class ConsultationAgent(BaseAgent):
    name = '问诊 Agent'
    def execute(self, question, context, history):
        previous = [m.content for m in history.messages if m.type == 'human'][-3:]
        text = '；'.join(previous + [question])
        known = ['头痛','发热','咳嗽','胸痛','恶心','鼻痒','喷嚏','腹痛','呼吸困难','头晕','咽痛']
        symptoms = [x for x in known if x in text]
        followup = []
        if not re.search(r'\d+\s*(天|小时|周|月|年)', text): followup.append('症状持续了多久？')
        if not context.get('allergies'): followup.append('是否有药物过敏史？不清楚也请说明。')
        if not context.get('medications'): followup.append('目前正在服用哪些药物？')
        return dict(chief_complaint=question, symptoms=symptoms, followup=followup, query=text[-500:], context=context, history_turns=len(previous), mode='本地信息提取规则')

class RiskAgent(BaseAgent):
    name = '风险评估 Agent'
    def execute(self, consultation):
        text = consultation['query']
        from .risk_workflow import information,is_denied
        patterns = ['呼吸困难','意识不清','意识改变','胸口压榨','胸痛','大汗','放射左臂','昏迷','呕血']
        flags = []
        for term in patterns:
            if any(not is_denied(text,m.start()) for m in re.finditer(term,text)):
                flags.append(term)
        details=information(text)
        recommendation='出现危险信号，请立即联系急救或就近急诊。中国大陆急救电话 120。' if flags else ('目前还缺少部分信息，见下方待补充问题。' if details['followup'] else '你提供的持续时间、程度和伴随情况已整理。已有规则未匹配到危险信号关键词，仍无法仅凭文字判断实际风险等级。')
        return dict(level='紧急提示' if flags else '尚不能确定风险等级', red_flags=flags, recommendation=recommendation, mode='本地危险信号检查与信息整理',**details)

class MedicationAgent(BaseAgent):
    name = '用药 Agent'
    def execute(self, consultation):
        c = consultation['context']
        from .medication_knowledge import DrugKnowledge
        return DrugKnowledge().check(c.get('medications',''),c.get('allergies',''))

class EducationAgent(BaseAgent):
    name = '资料解读 Agent'
    def execute(self, evidence):
        return dict(summary='以下为输入资料的原文摘录与来源整理，不新增诊断结论。',count=len(evidence),sources=[r['doc_id'] for r in evidence],points=[dict(name=r.get('name','资料'),excerpt=r.get('content','')[:300],doc_id=r['doc_id']) for r in evidence])

class Coordinator:
    def __init__(self, retrieval):
        self.retrieval = retrieval

    def search(self, query):
        service=self.retrieval() if callable(self.retrieval) else self.retrieval
        if service is None: raise RuntimeError('retrieval_unavailable')
        return service.search(query)

    async def run(self, question, context, history: InMemoryChatMessageHistory, session, config=None,on_event=None,request_id=None):
        def notify(agent,status,**details):
            if on_event:
                try: on_event(copy.deepcopy(dict(agent=agent,status=status,**details)))
                except Exception: pass
        request = request_id or uuid.uuid4().hex[:12]; started = time.perf_counter(); trace=[]; conflicts=[]
        notify('问诊 Agent','执行中')
        consultation = await ConsultationAgent().run(question, context, history); trace.append(consultation)
        notify('问诊 Agent',consultation.status,duration_ms=consultation.duration_ms,error=consultation.error)
        if consultation.status == '失败': raise RuntimeError('问诊信息处理失败')
        notify('风险评估 Agent','执行中')
        risk = await RiskAgent().run(consultation.output); trace.append(risk)
        notify('风险评估 Agent',risk.status,output=risk.output,duration_ms=risk.duration_ms,error=risk.error)
        if risk.status == '失败': raise RuntimeError('风险检查不可用，请稍后重试或线下咨询')
        urgent=bool(risk.output['red_flags'])
        consultation.output['risk_alert']=dict(red_flags=risk.output['red_flags'],recommendation=risk.output['recommendation'])
        llm = LLMClient(config) if config and config.api_key else None
        if llm and not risk.output['red_flags']:
            llm_start=time.perf_counter()
            notify('问诊 LLM','执行中')
            try:
                enriched=await llm.structured('你是问诊信息整理助手。只提取用户明确描述的症状，提出缺失信息的追问；不能诊断、给概率或处方。',dict(question=question,context=context,history=[dict(role=m.type,content=m.content) for m in history.messages[-6:]]),ConsultationSummary,session,request,'问诊 Agent')
                consultation.output.update(enriched.model_dump(),mode='在线 LLM 结构化信息整理')
                trace.append(AgentResult('问诊 LLM','完成',(time.perf_counter()-llm_start)*1000,enriched.model_dump()))
            except LLMError as exc:
                record(session,request,'failure',agent='问诊 LLM',error=str(exc))
                trace.append(AgentResult('问诊 LLM','失败',(time.perf_counter()-llm_start)*1000,error=str(exc)))
            notify('问诊 LLM',trace[-1].status,duration_ms=trace[-1].duration_ms,error=trace[-1].error)
        evidence = []
        if urgent:
            conflicts.append('风险提醒已优先展示；继续提供相关资料与用药信息核对，不能据此延迟就医或自行用药。')
        start = time.perf_counter()
        notify('检索 Agent','执行中'); notify('用药 Agent','执行中')
        retrieval, medication = await asyncio.gather(asyncio.to_thread(self.search, consultation.output['query']), MedicationAgent().run(consultation.output),return_exceptions=True)
        if isinstance(medication,Exception):
            medication=AgentResult('用药 Agent','失败',(time.perf_counter()-start)*1000,error=type(medication).__name__)
        trace.append(medication); notify('用药 Agent',medication.status,duration_ms=medication.duration_ms,error=medication.error)
        if medication.status=='完成': risk.output['medication_check']=medication.output
        if isinstance(retrieval,Exception):
            risk.output.update(retrieval_status='failed',retrieval_error=type(retrieval).__name__)
            trace.append(AgentResult('检索 Agent','失败',(time.perf_counter()-start)*1000,error=type(retrieval).__name__))
            notify('检索 Agent','失败',duration_ms=trace[-1].duration_ms,error=trace[-1].error)
        else:
            start = time.perf_counter()
            try:
                evidence = retrieval['evidences']
                notify('检索 Agent','完成',duration_ms=retrieval['latency_ms'])
                trace.append(AgentResult('检索 Agent','完成',retrieval['latency_ms'],retrieval))
                record(session,request,'retrieval', latency_ms=retrieval['latency_ms'],no_hit=not evidence,cache_hit=retrieval['cache_hit'])
                risk.output['retrieval_status']='completed' if evidence else 'no_hit'
                if llm and config.enable_rerank and len(evidence)>1:
                    from .specialists import rerank
                    tick=time.perf_counter(); notify('检索重排 Agent','执行中')
                    try:
                        evidence=await rerank(llm,question,evidence,session,request)
                        trace.append(AgentResult('检索重排 Agent','完成',(time.perf_counter()-tick)*1000,dict(evidences=evidence)))
                    except LLMError as exc:
                        trace.append(AgentResult('检索重排 Agent','失败',(time.perf_counter()-tick)*1000,error=str(exc)))
                    notify('检索重排 Agent',trace[-1].status,duration_ms=trace[-1].duration_ms,error=trace[-1].error)
                if llm and config.enable_specialist_review:
                    from .specialists import review
                    for role in ('风险复核 Agent','用药复核 Agent'):
                        tick=time.perf_counter(); notify(role,'执行中')
                        try:
                            review_evidence=medication.output.get('drug_evidences',[]) if role=='用药复核 Agent' else evidence
                            review_context=dict(consultation.output)
                            if role=='用药复核 Agent':
                                review_context['medication_findings']=dict(interactions=medication.output.get('interactions',[]),duplicates=medication.output.get('duplicates',[]),coverage=medication.output.get('knowledge_info',{}).get('coverage',{}))
                            output=await review(llm,role,review_context,review_evidence,session,request)
                            trace.append(AgentResult(role,'完成',(time.perf_counter()-tick)*1000,output))
                            if role=='风险复核 Agent': risk.output.update(model_review=output,online_status='completed')
                        except LLMError as exc:
                            trace.append(AgentResult(role,'失败',(time.perf_counter()-tick)*1000,error=str(exc)))
                            if role=='风险复核 Agent': risk.output.update(online_status='failed',review_error=str(exc))
                        notify(role,trace[-1].status,duration_ms=trace[-1].duration_ms,error=trace[-1].error)
                notify('资料解读 Agent','执行中')
                trace.append(await EducationAgent().run(evidence))
                notify('资料解读 Agent',trace[-1].status,duration_ms=trace[-1].duration_ms,error=trace[-1].error)
            except Exception as exc:
                trace.append(AgentResult('检索 Agent','失败',(time.perf_counter()-start)*1000,error=type(exc).__name__))
                risk.output.update(retrieval_status='failed',retrieval_error=type(exc).__name__)
        risk.output['evidences']=evidence
        answer = risk.output['recommendation']
        if evidence:
            answer += '\n\n相关资料（仅供查阅，不代表诊断）'+('，不能替代前述就医提醒' if urgent else '')+'：\n' + '\n'.join(f"- [{i}] {r['name']}：{r['content'][:160]}" for i,r in enumerate(evidence[:3],1))
        else: answer += '\n\n'+('资料检索暂不可用，已保留风险提醒与用药信息核对。' if risk.output.get('retrieval_status')=='failed' else '本次没有找到相关资料，不代表没有风险或无需就医。')
        if consultation.output['followup']:
            answer += '\n\n可补充的问诊信息'+('（不必等待补充或回复再就医）' if urgent else '')+'：\n' + '\n'.join('- '+x for x in consultation.output['followup'])
        answer += '\n\n用药信息核对：'+('已提供当前用药。' if context.get('medications') else '尚未提供当前用药。')+('已提供过敏史。' if context.get('allergies') else '尚未提供过敏史。')+'需要医生或药师核实；系统不生成处方或剂量。'
        for pair in medication.output.get('interactions',[]):
            if pair['records']:
                answer+='\n- '+' / '.join(pair['drugs'])+'：DDInter 记录等级 '+'、'.join(dict.fromkeys(row['level_label'] for row in pair['records']))+'；仅为现有资料匹配，需医生或药师核实。'
            else: answer+='\n- '+' / '.join(pair['drugs'])+'：未完成相互作用确认；当前子集未覆盖或药名尚未识别，不代表安全。'
        if medication.output.get('duplicates'): answer+='\n- 检测到输入药名涉及重复成分，请核对是否为同一用药或复方重复。'
        if llm and evidence:
            llm_start=time.perf_counter()
            notify('资料解读 LLM','执行中')
            try:
                summary=await llm.structured('你是医疗资料解读助手。仅整理给定证据，source_ids 只能选输入中的 doc_id。不能诊断或给处方剂量；说明证据局限。若存在 risk_alert 危险信号，不得降低其优先级、建议等待或以居家处理替代就医。',dict(question=question,risk_alert=consultation.output['risk_alert'],evidence=[dict(doc_id=r['doc_id'],name=r['name'],content=r['content'][:600]) for r in evidence]),EvidenceSummary,session,request,'资料解读 Agent',stream=True)
                if not set(summary.source_ids).issubset({r['doc_id'] for r in evidence}):
                    raise LLMError('invalid_citation')
                answer += '\n\n资料解读（AI 生成，需核对原文）：\n'+summary.summary
                if summary.limitations: answer += '\n\n证据局限：'+'；'.join(summary.limitations)
                trace.append(AgentResult('资料解读 LLM','完成',(time.perf_counter()-llm_start)*1000,summary.model_dump()))
            except LLMError as exc:
                record(session,request,'failure',agent='资料解读 LLM',error=str(exc))
                trace.append(AgentResult('资料解读 LLM','失败',(time.perf_counter()-llm_start)*1000,error=str(exc)))
                answer += '\n\n在线资料解读未完成，已保留本地检索结果。'
            notify('资料解读 LLM',trace[-1].status,duration_ms=trace[-1].duration_ms,error=trace[-1].error)
        for item in trace:
            notify(item.agent,item.status,duration_ms=item.duration_ms,error=item.error)
            record(session,request,'agent',agent=item.agent,status=item.status,latency_ms=item.duration_ms,error=item.error)
        duration_ms=(time.perf_counter()-started)*1000
        record(session,request,'request',latency_ms=duration_ms,mode='llm' if config and config.api_key else 'local')
        history.add_user_message(question); history.add_ai_message(answer)
        history.messages = history.messages[-12:]
        return dict(request=request,answer=answer,evidences=evidence,trace=[vars(x) for x in trace],conflicts=conflicts,duration_ms=duration_ms)
