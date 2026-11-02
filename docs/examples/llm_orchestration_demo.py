r"""Offline learning example for the real Coordinator; not a clinical demo.

Run from the project root:
    .venv\Scripts\python.exe docs/examples/llm_orchestration_demo.py
No provider API is called. The retrieval record is explicitly synthetic.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class DemoRetrieval:
    def search(self, query):
        return dict(
            evidences=[dict(
                doc_id='learning-source-01', name='课程流程验证资料',
                content='这是人工构造的流程测试记录，不提供医学判断或建议。',
                source='learning-demo', score=1.0,
            )],
            cache_hit=False, latency_ms=0.0,
        )


async def demonstrate():
    # Import only after assigning the isolated runtime in main().
    from agents.coordinator import Coordinator
    from agents.llm import LLMConfig
    from langchain_core.chat_history import InMemoryChatMessageHistory

    history = InMemoryChatMessageHistory()
    timeline = []

    def progress(event):
        timeline.append((event['agent'], event['status']))
        print(f"进度：{event['agent']} / {event['status']}")

    result = await Coordinator(DemoRetrieval()).run(
        question='课程示例：我咳嗽3天了',
        context=dict(allergies='无已知药物过敏', medications='目前未用药'),
        history=history,
        session='learning-session',
        config=LLMConfig(api_key=''),  # Explicitly disable all online LLM branches.
        on_event=progress,
        request_id='learning-request-01',
    )
    assert result['request'] == 'learning-request-01'
    assert len(history.messages) == 2
    assert len(result['evidences']) == 1
    assert not any(item['agent'].endswith('LLM') for item in result['trace'])
    print('\n最终轨迹：')
    for item in result['trace']:
        print(f"{item['agent']} / {item['status']}")
    print('请求编号：', result['request'])
    print('证据数量：', len(result['evidences']))
    print('历史消息数量：', len(history.messages))
    print('在线模型调用：0（代码已显式关闭）')
    return result


def main():
    # Do not write synthetic requests into existing user/production databases.
    with tempfile.TemporaryDirectory(prefix='medical-agent-learning-') as runtime:
        os.environ['MEDICAL_RUNTIME_DIR'] = runtime
        os.environ['MEDICAL_PUBLIC_MODE'] = '0'
        asyncio.run(demonstrate())


if __name__ == '__main__':
    main()
