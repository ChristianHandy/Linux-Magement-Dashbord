"""
Email configuration management for the Linux Management Dashboard.
Handles email settings for scheduled reports and error notifications.
"""
import json
import os

EMAIL_CONFIG_FILE = "email_settings.json"

def load_email_settings():
    """Load email settings from configuration file"""
    try:
        if os.path.exists(EMAIL_CONFIG_FILE):
            with open(EMAIL_CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "email_enabled": False,
        "smtp_server": "",
        "smtp_port": 587,
        "smtp_use_tls": True,
        "smtp_username": "",
        "smtp_password": "",
        "sender_email": "",
        "recipient_emails": [],
        "report_enabled": False,
        "report_interval": "weekly",
        "error_notifications_enabled": True
    }

def save_email_settings(settings):
    """Save email settings to configuration file"""
    with open(EMAIL_CONFIG_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def get_email_enabled():
    """Check if email notifications are enabled"""
    settings = load_email_settings()
    return settings.get("email_enabled", False)

def get_report_enabled():
    """Check if scheduled reports are enabled"""
    settings = load_email_settings()
    return settings.get("email_enabled", False) and settings.get("report_enabled", False)

def get_error_notifications_enabled():
    """Check if error notifications are enabled"""
    settings = load_email_settings()
    return settings.get("email_enabled", False) and settings.get("error_notifications_enabled", False)
