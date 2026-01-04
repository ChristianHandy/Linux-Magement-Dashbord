# Linux Update Dashboard

(Existing README content kept here...)

## Managing hosts (via web UI)

This project includes a small web UI to manage the list of hosts (PCs) the dashboard updates. You can add, edit, delete hosts and install an SSH public key on remote accounts using a password.

Important: The UI stores hosts in `hosts.json` (in the repository root). Make a backup before editing.

Routes
- Dashboard: `/dashboard`
- Manage hosts (list + add): `/hosts`
- Edit host: `/hosts/edit/<name>`
- Delete host (POST): `/hosts/delete/<name>`
- Install SSH public key (password auth): `/hosts/install_key/<name>`
- Update a host (starts update thread): `/update/<name>`
- Update progress: `/progress/<name>`

Default credentials (change before exposing publicly)
- Username: `admin`
- Password: `password`
- Secret (session): `app.secret_key = "change_me"` in `app.py`

Add a host (via web)
1. Log in to the dashboard (`/`) with the configured username/password.
2. Open `/hosts` (or click "Manage Hosts" on the dashboard).
3. Fill in:
   - Display name: a friendly name used by the dashboard (this becomes the key in `hosts.json`).
   - Host: IP address or hostname (used for SSH).
   - User: remote account username.
4. Click Save. The host will appear in the list and on the dashboard.

Edit a host
- Click "Edit" next to the host in `/hosts`, modify fields, then Save. If you change the Display name, the old entry will be removed and a new one created.

Delete a host
- Click the Delete button next to the host in `/hosts`. Deletion is performed with a POST request.

Install SSH public key on a remote host
- Click "Install SSH key" next to the host on `/hosts`.
- Enter the remote account password once and submit.
  - The server will:
    - Use your dashboard host's public key (`~/.ssh/id_rsa.pub`) if present, or
    - Generate an SSH keypair on the dashboard host (`~/.ssh/id_rsa` + `id_rsa.pub`) and use the public key.
    - Connect to the remote host over SSH with the provided password and append the public key to `~/.ssh/authorized_keys` (creating `~/.ssh` and setting permissions if necessary).
- On success, you will be able to SSH to the remote host from the dashboard host without a password (for that user).

hosts.json format
- The file is a simple JSON object mapping display name to host details:
```json
{
  "my-pc": { "host": "192.168.1.50", "user": "user" },
  "server-1": { "host": "server.example.local", "user": "admin" }
}
```
- You can edit `hosts.json` by hand, but the web UI will overwrite the file when hosts are added/edited/deleted. Back it up before manual edits.

Backup and restore hosts.json
- Backup:
  - cp hosts.json hosts.json.bak
- Restore:
  - mv hosts.json.bak hosts.json

Security notes (read before using publicly)
- Use HTTPS/TLS if the dashboard is reachable over an untrusted network, otherwise passwords and session cookies travel unencrypted.
- The "Install SSH key" flow requires you to enter the remote account password; that password is sent to the dashboard server and used transiently. Do not expose the dashboard without TLS and strong authentication.
- The dashboard may generate and store a private key under `~/.ssh` on the dashboard host. Protect that machine and its filesystem.
- Add CSRF protection (Flask-WTF) and stronger authentication before exposing publicly.
- Consider moving credentials and the `app.secret_key` into environment variables instead of hardcoding them.

Running & testing
1. Ensure dependencies are installed:
   - paramiko (see `requirements.txt`)
2. Start the app:
   - python3 app.py
3. Open a browser to the server's address (e.g. `http://localhost:5000`).
4. Log in and visit `/hosts` to manage hosts.

Troubleshooting
- Template errors: ensure `templates/` contains `dashboard.html`, `hosts.html`, `edit_host.html`, `install_key.html`, and `progress.html`.
- If `hosts.json` is malformed, the app will fall back to an empty hosts list. Check JSON syntax if hosts are missing.
- If SSH key installation fails, examine the error message shown on the `/hosts/install_key/<name>` page and check connectivity and credentials.

If you want, I can:
- Commit and push this README update to `main`.
- Open a small PR instead.
- Add example screenshots or a short screencast showing the flow.

Would you like me to push this README update to `main` now? If so, confirm and I will apply the change.  
