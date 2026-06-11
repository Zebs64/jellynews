"""Planificateur APScheduler : déclenche l'envoi hebdomadaire de la newsletter.

Le job est (re)construit à partir de la configuration en base à chaque
sauvegarde des réglages — pas besoin de redémarrer le conteneur.
Le fuseau horaire vient de la variable d'environnement TZ (docker-compose).
"""
import logging
import os
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import database

log = logging.getLogger("jellynews.scheduler")

JOB_ID = "weekly-newsletter"
scheduler = BackgroundScheduler(timezone=os.environ.get("TZ", "Europe/Paris"))


def _run_job() -> None:
    # Import tardif pour éviter un import circulaire newsletter -> scheduler.
    from .services import newsletter

    try:
        result = newsletter.run(trigger="scheduler")
        log.info("Envoi planifié terminé : %s", result)
    except Exception:
        log.exception("Échec de l'envoi planifié")


def reschedule() -> None:
    settings = database.get_settings()
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)
    if settings.get("schedule_enabled") != "1":
        log.info("Planification désactivée")
        return
    # Le fuseau configuré dans l'interface prime sur celui du scheduler (TZ).
    tz_name = settings.get("timezone") or os.environ.get("TZ", "Europe/Paris")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        log.warning("Fuseau %r inconnu, repli sur Europe/Paris", tz_name)
        tz = ZoneInfo("Europe/Paris")
    trigger = CronTrigger(
        day_of_week=int(settings.get("schedule_day", "4")),
        hour=int(settings.get("schedule_hour", "18")),
        minute=int(settings.get("schedule_minute", "0")),
        timezone=tz,
    )
    scheduler.add_job(_run_job, trigger, id=JOB_ID, name="Newsletter hebdomadaire")
    log.info("Newsletter planifiée : %s", trigger)


def start() -> None:
    if not scheduler.running:
        scheduler.start()
    reschedule()


def next_run_iso() -> str | None:
    job = scheduler.get_job(JOB_ID)
    if job and job.next_run_time:
        return job.next_run_time.isoformat(timespec="minutes")
    return None
