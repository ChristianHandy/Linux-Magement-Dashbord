from apscheduler.schedulers.background import BackgroundScheduler
from updater import run_update
import json
import os

scheduler = BackgroundScheduler()

def load_update_settings():
    """Load update settings from configuration file"""
    try:
        if os.path.exists("update_settings.json"):
            with open("update_settings.json", "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "automatic_updates_enabled": False,
        "update_frequency": "daily",
        "last_auto_update": None,
        "notification_enabled": True
    }

def save_update_settings(settings):
    """Save update settings to configuration file"""
    with open("update_settings.json", "w") as f:
        json.dump(settings, f, indent=2)

def scheduled_updates():
    """Run scheduled automatic updates"""
    settings = load_update_settings()
    if not settings.get("automatic_updates_enabled", False):
        return
    
    hosts = json.load(open("hosts.json"))
    for name, h in hosts.items():
        run_update(h["host"], h["user"], name, [])
    
    # Update last run time
    import time
    settings["last_auto_update"] = time.ctime()
    save_update_settings(settings)

def configure_scheduler():
    """Configure the scheduler based on update settings"""
    settings = load_update_settings()
    
    # Remove existing jobs
    scheduler.remove_all_jobs()
    
    if settings.get("automatic_updates_enabled", False):
        frequency = settings.get("update_frequency", "daily")
        
        if frequency == "daily":
            scheduler.add_job(scheduled_updates, "interval", days=1, id="auto_update")
        elif frequency == "weekly":
            scheduler.add_job(scheduled_updates, "interval", weeks=1, id="auto_update")
        elif frequency == "monthly":
            scheduler.add_job(scheduled_updates, "interval", days=30, id="auto_update")

# Start scheduler
scheduler.start()

