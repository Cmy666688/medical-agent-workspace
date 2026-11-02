"""独立站内提醒调度进程；仅在本机进程运行时产生待办。"""
import logging
import time
from agents.family import tick,worker_heartbeat,DB
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    DB.parent.mkdir(exist_ok=True)
    lock=(DB.parent/'reminder_worker.lock').open('a+b')
    if lock.tell()==0: lock.write(b'0'); lock.flush()
    lock.seek(0)
    import msvcrt
    waiting=False
    while True:
        try:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            break
        except OSError:
            if not waiting: logging.info('共享提醒已有工作进程，本进程待命。')
            waiting=True
            time.sleep(5)
    while True:
        try: tick(); worker_heartbeat()
        except Exception: logging.exception('提醒调度失败')
        time.sleep(15)
