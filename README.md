# Gitops-postgres

This repository contains Postgres Operator configurations and GitOps workflows.

## Initial Setup

After cloning this repository, **you must run the setup and requirements check scripts**:

1-

```bash
./setup-hooks.sh
```

This installs the pre-commit hook that automatically seals user secrets. See [HOOKS.md](HOOKS.md) for more details.

2-

```bash
./check-requirements.sh
```

This checks the required packages that are needed to run the basic edit users functions as a manager.If something is missing, you can insall and check again.

## Project Structure

- `postgres-operator/` - Postgres Operator source code and manifests
- `zilando-CRDs/` - Custom Resource Definitions and user management
- `hooks/` - Git hooks (tracked in version control)
- `failover_test.txt` - Gives simple steps to test the failover mechanism in the operator.
- `steps_to_deploy_controller.txt` - gives the detailed steps to setup the database operator and the controller from scratch in the kuberneetes cluster.
- `usefull_commands.txt` - gives out some of the most commen commands that you can use to connec to the database and also check the conroller logs etc.
