# constants.py - Shared constants for the Linux Management Dashboard

# Localhost detection
LOCALHOST_IDENTIFIERS = ['localhost', '127.0.0.1', '::1', '0.0.0.0']

def is_localhost(host):
    """Check if the given host is localhost"""
    if not host:
        return False
    return host.lower() in LOCALHOST_IDENTIFIERS
