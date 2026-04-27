import os
from celery import Celery
from celery.schedules import schedule

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("payout_engine")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "recover-stuck-payouts-every-30s": {
        "task": "apps.payouts.tasks.recover_stuck_payouts",
        "schedule": schedule(run_every=30.0),
    },
}
