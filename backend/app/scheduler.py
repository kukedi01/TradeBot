from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.database import SessionLocal
from app.db.models import TradingSession
from app.session.loop import run_tick

scheduler = AsyncIOScheduler()


def _tick_all_running_sessions():
    db = SessionLocal()
    try:
        running_sessions = db.query(TradingSession).filter(TradingSession.status == "running").all()
        for session in running_sessions:
            executed = run_tick(db, session.id)
            for line in executed:
                print(f"[session {session.id}] {line}")
    finally:
        db.close()


def start_scheduler():
    scheduler.add_job(_tick_all_running_sessions, "interval", seconds=30, id="bot_tick")
    scheduler.start()
