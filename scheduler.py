from apscheduler.schedulers.background import BackgroundScheduler
from updater import run_update
import json
import os
import email_config
import email_notifier

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
    
    # Load hosts with error handling
    try:
        with open("hosts.json", "r") as f:
            hosts = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # No hosts configured or file is corrupted
        return
    
    for name, h in hosts.items():
        run_update(h["host"], h["user"], name, [])
    
    # Update last run time
    import time
    settings["last_auto_update"] = time.ctime()
    save_update_settings(settings)

def scheduled_email_report():
    """Send scheduled email report with system status"""
    if not email_config.get_report_enabled():
        return
    
    try:
        # Load hosts
        with open("hosts.json", "r") as f:
            hosts = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        hosts = {}
    
    # Load history
    try:
        with open("history.json", "r") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {}
    
    # Check host status (simplified - just check if host exists in config)
    hosts_status = {name: True for name in hosts.keys()}
    
    # Send the report
    success, error = email_notifier.send_update_report(hosts_status, history)
    if not success:
        print(f"Failed to send scheduled email report: {error}")

def configure_scheduler():
    """Configure the scheduler based on update settings"""
    settings = load_update_settings()
    email_settings = email_config.load_email_settings()
    
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
    
    # Schedule email reports if enabled
    if email_config.get_report_enabled():
        report_interval = email_settings.get("report_interval", "weekly")
        
        if report_interval == "daily":
            scheduler.add_job(scheduled_email_report, "interval", days=1, id="email_report")
        elif report_interval == "weekly":
            scheduler.add_job(scheduled_email_report, "interval", weeks=1, id="email_report")
        elif report_interval == "monthly":
            scheduler.add_job(scheduled_email_report, "interval", days=30, id="email_report")

# Start scheduler
scheduler.start()

