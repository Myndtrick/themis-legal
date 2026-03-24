"""Shared APScheduler instance — importable from any module without circular deps."""

from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
