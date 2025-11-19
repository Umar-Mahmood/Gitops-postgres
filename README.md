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

## Usage 1 - config changes

If you wan to chenge he configration of the cluster. you can go to the `zilando-CRDs/postgres-config/postgres-cluster.yaml` and make changes and commit/push the changes. Your changes will be reflected in the next sync.

## Usage 2 - User Management

If you want to make changes to the users in the database. you can go to `zilando-CRDs/UserManifests/edit-users.yaml` and make your changes. In start there should only be one demo user. you can delete or add more users as you want and commit/push. your changes will be reflected in the databse on the next sync.
