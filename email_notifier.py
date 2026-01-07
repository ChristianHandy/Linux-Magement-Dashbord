"""
Email notification system for the Linux Management Dashboard.
Sends scheduled reports and error notifications via SMTP.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import json
import logging
import email_config

logger = logging.getLogger(__name__)

def send_email(subject, body, html_body=None):
    """
    Send an email using configured SMTP settings.
    
    Args:
        subject: Email subject line
        body: Plain text email body
        html_body: Optional HTML email body
        
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    settings = email_config.load_email_settings()
    
    if not settings.get("email_enabled", False):
        return False, "Email notifications are disabled"
    
    # Validate required settings
    required_fields = ["smtp_server", "smtp_port", "sender_email", "recipient_emails"]
    for field in required_fields:
        if not settings.get(field):
            return False, f"Email configuration incomplete: {field} not set"
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = settings['sender_email']
        msg['To'] = ', '.join(settings['recipient_emails'])
        
        # Attach plain text body
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach HTML body if provided
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))
        
        # Connect to SMTP server and send
        if settings.get("smtp_use_tls", True):
            server = smtplib.SMTP(settings['smtp_server'], settings['smtp_port'])
            server.starttls()
        else:
            server = smtplib.SMTP(settings['smtp_server'], settings['smtp_port'])
        
        # Login if credentials provided
        if settings.get("smtp_username") and settings.get("smtp_password"):
            server.login(settings['smtp_username'], settings['smtp_password'])
        
        # Send email
        server.send_message(msg)
        server.quit()
        
        logger.info(f"Email sent successfully: {subject}")
        return True, None
        
    except smtplib.SMTPAuthenticationError:
        error_msg = "SMTP authentication failed. Check username and password."
        logger.error(error_msg)
        return False, error_msg
    except smtplib.SMTPException as e:
        error_msg = f"SMTP error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def send_update_report(hosts_status, history):
    """
    Send a scheduled update report with system status.
    
    Args:
        hosts_status: Dictionary of host statuses
        history: Update history data
        
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    if not email_config.get_report_enabled():
        return False, "Scheduled reports are disabled"
    
    # Generate report content
    subject = f"Linux Management Dashboard - System Report ({datetime.now().strftime('%Y-%m-%d')})"
    
    # Plain text body
    body = f"""Linux Management Dashboard - System Status Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

=== HOST STATUS ===
"""
    
    for hostname, status in hosts_status.items():
        status_text = "ONLINE" if status else "OFFLINE"
        body += f"  {hostname}: {status_text}\n"
    
    body += f"""
=== RECENT UPDATE HISTORY ===
"""
    
    if history:
        recent_updates = list(history.items())[-10:]  # Last 10 updates
        for host, updates in recent_updates:
            body += f"\n{host}:\n"
            if updates:
                latest = updates[-1] if isinstance(updates, list) else updates
                body += f"  Last update: {latest}\n"
    else:
        body += "  No update history available\n"
    
    body += """
---
This is an automated report from Linux Management Dashboard
"""
    
    # HTML body
    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #2c3e50;">Linux Management Dashboard - System Status Report</h2>
    <p style="color: #7f8c8d;">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <h3 style="color: #34495e; margin-top: 30px;">Host Status</h3>
    <table style="border-collapse: collapse; width: 100%; max-width: 600px;">
        <thead>
            <tr style="background-color: #34495e; color: white;">
                <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">Hostname</th>
                <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">Status</th>
            </tr>
        </thead>
        <tbody>
"""
    
    for hostname, status in hosts_status.items():
        status_text = "ONLINE" if status else "OFFLINE"
        status_color = "#27ae60" if status else "#e74c3c"
        html_body += f"""
            <tr>
                <td style="padding: 10px; border: 1px solid #ddd;">{hostname}</td>
                <td style="padding: 10px; border: 1px solid #ddd; color: {status_color}; font-weight: bold;">{status_text}</td>
            </tr>
"""
    
    html_body += """
        </tbody>
    </table>
    
    <h3 style="color: #34495e; margin-top: 30px;">Recent Update History</h3>
"""
    
    if history:
        recent_updates = list(history.items())[-10:]
        html_body += "<ul>"
        for host, updates in recent_updates:
            html_body += f"<li><strong>{host}</strong>: "
            if updates:
                latest = updates[-1] if isinstance(updates, list) else updates
                html_body += f"{latest}</li>"
            else:
                html_body += "No updates</li>"
        html_body += "</ul>"
    else:
        html_body += "<p>No update history available</p>"
    
    html_body += """
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="color: #7f8c8d; font-size: 0.9em;">This is an automated report from Linux Management Dashboard</p>
</body>
</html>
"""
    
    return send_email(subject, body, html_body)

def send_error_notification(hostname, error_message):
    """
    Send an error notification when a system update fails.
    
    Args:
        hostname: Name of the host that encountered an error
        error_message: Description of the error
        
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    if not email_config.get_error_notifications_enabled():
        return False, "Error notifications are disabled"
    
    subject = f"⚠️ Linux Management Dashboard - Update Error: {hostname}"
    
    # Plain text body
    body = f"""ALERT: System Update Error

Host: {hostname}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Error Details:
{error_message}

Please check the dashboard for more information and take appropriate action.

---
This is an automated alert from Linux Management Dashboard
"""
    
    # HTML body
    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="background-color: #e74c3c; color: white; padding: 20px; border-radius: 5px;">
        <h2 style="margin: 0;">⚠️ System Update Error</h2>
    </div>
    
    <div style="padding: 20px; background-color: #f8f9fa; margin-top: 20px; border-radius: 5px;">
        <p><strong>Host:</strong> {hostname}</p>
        <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div style="margin-top: 20px;">
        <h3 style="color: #e74c3c;">Error Details:</h3>
        <pre style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto;">{error_message}</pre>
    </div>
    
    <p style="margin-top: 30px;">Please check the dashboard for more information and take appropriate action.</p>
    
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="color: #7f8c8d; font-size: 0.9em;">This is an automated alert from Linux Management Dashboard</p>
</body>
</html>
"""
    
    return send_email(subject, body, html_body)

def test_email_configuration():
    """
    Send a test email to verify configuration.
    
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    subject = "Linux Management Dashboard - Test Email"
    body = f"""This is a test email from Linux Management Dashboard.

If you received this email, your email configuration is working correctly.

Test sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
Linux Management Dashboard
"""
    
    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="background-color: #3498db; color: white; padding: 20px; border-radius: 5px;">
        <h2 style="margin: 0;">✓ Email Configuration Test</h2>
    </div>
    
    <p style="margin-top: 20px;">This is a test email from Linux Management Dashboard.</p>
    
    <div style="background-color: #d4edda; border-left: 4px solid #28a745; padding: 15px; margin-top: 20px;">
        <p style="margin: 0;"><strong>Success!</strong> If you received this email, your email configuration is working correctly.</p>
    </div>
    
    <p style="margin-top: 20px; color: #7f8c8d;">Test sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="color: #7f8c8d; font-size: 0.9em;">Linux Management Dashboard</p>
</body>
</html>
"""
    
    return send_email(subject, body, html_body)
