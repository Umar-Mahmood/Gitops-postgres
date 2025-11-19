# Gitops-postgres

This repository contains Postgres Operator configurations and GitOps workflows.

## Initial Setup

After cloning this repository, **you must run the setup script** to enable Git hooks:

```bash
./setup-hooks.sh
```

This installs the pre-commit hook that automatically seals user secrets. See [HOOKS.md](HOOKS.md) for more details.

## Project Structure

- `postgres-operator/` - Postgres Operator source code and manifests
- `zilando-CRDs/` - Custom Resource Definitions and user management
- `hooks/` - Git hooks (tracked in version control)

## Git Hooks

This repository uses Git hooks to automate secret sealing. **Important:** After cloning, you must run `./setup-hooks.sh` to install these hooks locally.

For detailed information about the hooks, see [HOOKS.md](HOOKS.md).
