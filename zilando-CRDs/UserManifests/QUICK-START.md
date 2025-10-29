# Quick Reference: User Management Workflow

## 🚀 Quick Start

### First Time Setup
```bash
# After cloning the repository
./zilando-CRDs/UserManifests/setup-hook.sh
```

## 📝 Daily Workflow

### Adding/Modifying Users

1. **Edit the user file** (passwords included):
   ```bash
   vim zilando-CRDs/UserManifests/edit-users.yaml
   ```

2. **Stage and commit**:
   ```bash
   git add zilando-CRDs/UserManifests/edit-users.yaml
   git commit -m "Update users"
   ```

3. **What happens automatically**:
   - ✅ `seal_users.py` runs
   - ✅ `users.yaml` is generated (no passwords)
   - ✅ `sealed-users.yaml` is created
   - ✅ Both files are staged and committed
   - ✅ `edit-users.yaml` is unstaged (stays local)

4. **Push changes**:
   ```bash
   git push
   ```

## 📂 File Purposes

| File | Purpose | Contains Passwords? | Committed? |
|------|---------|-------------------|------------|
| `edit-users.yaml` | Source file you edit | ✅ YES | ❌ NO |
| `users.yaml` | ConfigMap for controller | ❌ NO | ✅ YES |
| `sealed-users.yaml` | Encrypted secrets | 🔐 Encrypted | ✅ YES |

## 🔧 Commands

### Manual seal (if needed):
```bash
cd zilando-CRDs/UserManifests
python3 seal_users.py
```

### Check what will be committed:
```bash
git status
git diff --cached
```

### Bypass hook (⚠️ NOT RECOMMENDED):
```bash
git commit --no-verify -m "message"
```

## ✅ Verification

### After committing, verify:
```bash
# Check what was committed
git log -1 --stat

# Verify edit-users.yaml is not staged
git status

# Your edit-users.yaml should still have passwords locally
cat zilando-CRDs/UserManifests/edit-users.yaml
```

## 🆘 Troubleshooting

### Hook not running?
```bash
# Check hook exists and is executable
ls -la .git/hooks/pre-commit

# Re-run setup
./zilando-CRDs/UserManifests/setup-hook.sh
```

### Seal script fails?
```bash
# Check dependencies
python3 -c "import yaml"
kubeseal --version

# Check certificate exists
ls -la zilando-CRDs/pub-cert.pem
```

## 🎯 Example User Entry

```yaml
apiVersion: v1
data:
  users.yaml: |
    users:
      - username: new_user
        database: postgres
        password: secure_password_123
        roles:
          - writer
kind: ConfigMap
metadata:
  name: postgres-users-config
  namespace: postgres
```

## 💡 Tips

- Edit `edit-users.yaml` freely - it won't be committed
- The hook ensures passwords never reach the repository
- Generated files are always in sync with your edits
- Your local `edit-users.yaml` is your source of truth
