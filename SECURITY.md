# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it by:

1. **DO NOT** create a public GitHub issue
2. Email the maintainers or use GitHub's private vulnerability reporting feature
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if available)

We will respond to security reports within 48 hours and work to address critical issues promptly.

## Supported Versions

We recommend always using the latest version of this software, as it contains the most recent security updates.

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| Older   | :x:                |

## Security Best Practices

### For Deployment

1. **Never use default credentials in production**
   - Set `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` environment variables
   - Use strong, unique passwords

2. **Always use HTTPS/TLS**
   - Deploy behind a reverse proxy (nginx, Apache) with TLS certificates
   - Never transmit credentials over plain HTTP

3. **Restrict network access**
   - Run on isolated networks or VPN
   - Use firewall rules to limit access
   - Never expose directly to the internet

4. **Use a production WSGI server**
   - Don't use Flask's development server in production
   - Use gunicorn, uWSGI, or similar

5. **Keep dependencies updated**
   - Regularly update Python packages: `pip install --upgrade -r requirements.txt`
   - Monitor for security advisories

6. **Root access considerations**
   - Disk management features require root/sudo
   - Run in isolated VM or container
   - Audit all disk operations
   - Consider separating disk tools from web interface

### Environment Variables

Required environment variables for secure operation:

```bash
# Generate a secure secret key
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Set secure credentials
export DASHBOARD_USERNAME=your_username
export DASHBOARD_PASSWORD=your_secure_password

# Disable debug mode (default)
export FLASK_DEBUG=false
```

### Known Limitations

1. **SSH Host Key Validation**: ~~The application uses `AutoAddPolicy` which accepts any SSH host key. This is vulnerable to man-in-the-middle attacks.~~ **FIXED** - The application now uses `RejectPolicy` with proper known_hosts validation. Add remote hosts to known_hosts before connection: `ssh-keyscan -H hostname >> ~/.ssh/known_hosts`

2. **CSRF Protection**: The application does not currently implement CSRF tokens. Consider adding Flask-WTF for CSRF protection in production.

3. **Rate Limiting**: No rate limiting is implemented. Consider adding Flask-Limiter to prevent brute force attacks.

4. **Session Security**: Sessions use cookies without `secure` flag by default. Ensure `SESSION_COOKIE_SECURE=True` when using HTTPS.

### Security Features Implemented

- ✅ No hardcoded credentials (environment variables required)
- ✅ Secure session key generation
- ✅ Input validation and sanitization (command injection prevention)
- ✅ Security headers (X-Frame-Options, X-Content-Type-Options, etc.)
- ✅ Debug mode disabled by default
- ✅ SQL parameterized queries (SQL injection prevention)
- ✅ Template injection protection
- ✅ SFTP for secure file operations
- ✅ SSH host key verification (prevents MITM attacks)

## Security Checklist for Production

Before deploying to production, ensure:

- [ ] Environment variables set with secure credentials
- [ ] SECRET_KEY is a random 32+ byte value
- [ ] HTTPS/TLS configured on reverse proxy
- [ ] Debug mode disabled (FLASK_DEBUG=false)
- [ ] Running behind a firewall with restricted access
- [ ] Regular security updates scheduled
- [ ] Audit logging enabled
- [ ] Backups configured
- [ ] Monitoring and alerting set up
- [ ] Documentation reviewed by security team

## Update Policy

We regularly review and update security measures. To stay informed:

1. Watch this repository for security updates
2. Subscribe to security advisories for dependencies:
   - Flask: https://github.com/pallets/flask/security
   - Paramiko: https://github.com/paramiko/paramiko/security
   - APScheduler: https://github.com/agronholm/apscheduler/security

## Disclaimer

This software requires root access for disk operations, which inherently poses security risks. Use at your own risk and only in trusted, isolated environments. The maintainers are not responsible for any damage or security breaches resulting from the use of this software.
