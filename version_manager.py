"""
Version Manager Module
Handles checking for new dashboard versions from GitHub and managing update notifications.
"""

import json
import os
import re
import time
import shutil
import subprocess
import requests
from datetime import datetime, timedelta

VERSION_CHECK_FILE = "version_check.json"
GITHUB_REPO = "ChristianHandy/Linux-Magement-Dashbord"
GITHUB_API_BASE = "https://api.github.com"

def load_version_data():
    """Load version check data from file"""
    try:
        if os.path.exists(VERSION_CHECK_FILE):
            with open(VERSION_CHECK_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "last_check": None,
        "current_version": None,
        "latest_version": None,
        "update_available": False,
        "update_type": None,  # "release" or "commit"
        "update_url": None,
        "update_description": None,
        "notification_dismissed": False,
        "last_notified": None
    }

def save_version_data(data):
    """Save version check data to file"""
    with open(VERSION_CHECK_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_current_commit_sha():
    """Get the current commit SHA of the local repository"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None

def sanitize_branch_name(branch):
    """
    Security: Validate and sanitize git branch names to prevent command injection.
    Only allows alphanumeric characters, hyphens, underscores, and dots in branch segments,
    with forward slashes as path separators for hierarchical branch names.
    Branch names must start with alphanumeric characters to prevent flag injection.
    Branch names are limited to 255 characters.
    """
    if not branch or not isinstance(branch, str):
        raise ValueError("Branch name cannot be empty or non-string")
    # Only allow safe characters for branch names with reasonable length limit
    # Pattern requires alphanumeric start to prevent flag injection (e.g., -rf)
    # Allows dots for version tags (e.g., release/v1.2.3) but prevents path traversal
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*(?:/[a-zA-Z0-9][a-zA-Z0-9._-]*)*$', branch):
        raise ValueError("Branch name contains invalid characters or format")
    # Additional safety check: prevent path traversal attempts
    if '..' in branch or branch.startswith('.') or branch.endswith('.'):
        raise ValueError("Branch name contains invalid path traversal patterns")
    # Additional safety check: limit total length
    if len(branch) > 255:
        raise ValueError("Branch name exceeds maximum length of 255 characters")
    return branch

def get_current_branch():
    """Get the current git branch"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            # Sanitize the branch name before returning
            try:
                return sanitize_branch_name(branch)
            except ValueError:
                # If sanitization fails, fall back to main
                return "main"
    except Exception:
        pass
    return "main"

def check_for_updates():
    """
    Check GitHub for new versions (releases or commits).
    Returns updated version data.
    """
    data = load_version_data()
    current_sha = get_current_commit_sha()
    branch = get_current_branch()
    
    data["current_version"] = current_sha
    data["last_check"] = datetime.now().isoformat()
    
    try:
        # First, check for latest release
        release_url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(release_url, timeout=10)
        
        if response.status_code == 200:
            release = response.json()
            latest_release_sha = release.get("target_commitish", "")
            
            # Check if release is newer than current
            if latest_release_sha and current_sha and latest_release_sha != current_sha:
                data["update_available"] = True
                data["update_type"] = "release"
                data["latest_version"] = release.get("tag_name", "Unknown")
                data["update_url"] = release.get("html_url")
                data["update_description"] = release.get("name", "New release available")
                data["notification_dismissed"] = False
                save_version_data(data)
                return data
        
        # If no newer release, check for latest commit on current branch
        commit_url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/commits/{branch}"
        response = requests.get(commit_url, timeout=10)
        
        if response.status_code == 200:
            commit = response.json()
            latest_sha = commit.get("sha", "")
            
            if latest_sha and current_sha and latest_sha != current_sha:
                data["update_available"] = True
                data["update_type"] = "commit"
                data["latest_version"] = latest_sha[:7]  # Short SHA
                data["update_url"] = commit.get("html_url")
                commit_msg = commit.get("commit", {}).get("message", "").split("\n")[0]
                data["update_description"] = f"New commit: {commit_msg}"
                data["notification_dismissed"] = False
                save_version_data(data)
                return data
            else:
                # No update available
                data["update_available"] = False
                data["update_type"] = None
                
    except Exception as e:
        # Log error but don't crash
        print(f"Error checking for updates: {e}")
    
    save_version_data(data)
    return data

def should_check_for_updates(check_interval_hours=24):
    """
    Determine if we should check for updates based on last check time.
    Default: check every 24 hours.
    """
    data = load_version_data()
    last_check = data.get("last_check")
    
    if not last_check:
        return True
    
    try:
        last_check_dt = datetime.fromisoformat(last_check)
        if datetime.now() - last_check_dt > timedelta(hours=check_interval_hours):
            return True
    except Exception:
        return True
    
    return False

def dismiss_notification():
    """Mark the current update notification as dismissed"""
    data = load_version_data()
    data["notification_dismissed"] = True
    data["last_notified"] = datetime.now().isoformat()
    save_version_data(data)

def get_update_notification():
    """
    Get update notification data if an update is available and not dismissed.
    Returns None if no notification should be shown.
    """
    data = load_version_data()
    
    if data.get("update_available") and not data.get("notification_dismissed"):
        return {
            "type": data.get("update_type"),
            "version": data.get("latest_version"),
            "description": data.get("update_description"),
            "url": data.get("update_url")
        }
    
    return None

def perform_self_update(preserve_configs=True):
    """
    Update the dashboard to the latest version while preserving configurations.
    Returns (success, message)
    """
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Files and directories to preserve
        preserve_files = [
            "hosts.json",
            "history.json",
            "update_settings.json",
            "version_check.json",
            "users.db",
            "disks.db",
            ".env",
            "operations.db",
            "smart.db"
        ]
        
        backup_dir = "/tmp/dashboard_backup_" + str(int(time.time()))
        
        if preserve_configs:
            # Create backup directory
            os.makedirs(backup_dir, exist_ok=True)
            
            # Backup configuration files
            for filename in preserve_files:
                filepath = os.path.join(repo_dir, filename)
                if os.path.exists(filepath):
                    backup_path = os.path.join(backup_dir, filename)
                    shutil.copy2(filepath, backup_path)
        
        # Fetch latest changes
        result = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return False, f"Failed to fetch updates: {result.stderr}"
        
        # Get current branch (already sanitized by get_current_branch)
        branch = get_current_branch()
        
        # Pull latest changes
        result = subprocess.run(
            ["git", "reset", "--hard", f"origin/{branch}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return False, f"Failed to update: {result.stderr}"
        
        if preserve_configs:
            # Restore configuration files
            for filename in preserve_files:
                backup_path = os.path.join(backup_dir, filename)
                if os.path.exists(backup_path):
                    filepath = os.path.join(repo_dir, filename)
                    shutil.copy2(backup_path, filepath)
            
            # Clean up backup
            shutil.rmtree(backup_dir, ignore_errors=True)
        
        # Update version data
        data = load_version_data()
        data["current_version"] = get_current_commit_sha()
        data["update_available"] = False
        data["notification_dismissed"] = False
        save_version_data(data)
        
        return True, "Dashboard updated successfully. Please restart the application."
        
    except Exception as e:
        return False, f"Update failed: {str(e)}"
