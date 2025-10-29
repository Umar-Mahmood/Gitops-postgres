# Pre-commit Hook for User Secret Sealing

## Overview

This repository uses a Git pre-commit hook to automatically seal user secrets when `edit-users.yaml` is modified.

## Installation

After cloning the repository, run the setup script:

```bash
cd /home/ncl-admin/Desktop/conf-paper
./zilando-CRDs/UserManifests/setup-hook.sh
```

This will install the pre-commit hook in `.git/hooks/pre-commit`.

## How It Works

1. **Edit Phase**: You edit `zilando-CRDs/UserManifests/edit-users.yaml` with user credentials (including passwords)
2. **Commit Phase**: When you try to commit changes to `edit-users.yaml`, the pre-commit hook:
   - Detects the staged changes
   - Runs `seal_users.py` to generate sealed secrets
   - Stages the generated files: `users.yaml` and `sealed-users.yaml`
   - **Unstages** `edit-users.yaml` (keeps your local changes)
   - Commits only the sealed files

## Workflow

```bash
# 1. Edit the users file with passwords
vim zilando-CRDs/UserManifests/edit-users.yaml

# 2. Stage the file
git add zilando-CRDs/UserManifests/edit-users.yaml

# 3. Try to commit
git commit -m "Add new user"

# The pre-commit hook will:
# - Run seal_users.py automatically
# - Unstage edit-users.yaml
# - Stage users.yaml and sealed-users.yaml instead
# - Complete the commit with the sealed files

# 4. Your edit-users.yaml remains locally with passwords (not committed)
```

## Benefits

- **Security**: Passwords are never committed to the repository
- **Automation**: No need to manually run `seal_users.py`
- **Consistency**: Ensures sealed secrets are always in sync with user definitions
- **Safety**: The source file with passwords stays local only

## Requirements

- Python 3
- `kubeseal` CLI tool installed and available in PATH
- Certificate file at `zilando-CRDs/pub-cert.pem`
- PyYAML library: `pip install pyyaml`

## Hook Location

The pre-commit hook is located at: `.git/hooks/pre-commit`

## Troubleshooting

If the hook fails:

1. **Check certificate exists**: `ls zilando-CRDs/pub-cert.pem`
2. **Check kubeseal is installed**: `kubeseal --version`
3. **Check Python dependencies**: `python3 -c "import yaml"`
4. **Check hook is executable**: `ls -l .git/hooks/pre-commit`

## Bypassing the Hook (Not Recommended)

If you need to bypass the hook temporarily:

```bash
git commit --no-verify -m "message"
```

⚠️ **Warning**: This will commit `edit-users.yaml` with passwords if staged!

## Manual Sealing

You can also run the sealing process manually:

```bash
cd zilando-CRDs/UserManifests
python3 seal_users.py
```
