# GitOps PostgreSQL Operator System

A comprehensive GitOps-based PostgreSQL database management system running on Kubernetes, featuring automated user management, high availability with Patroni, and infrastructure-as-code practices using ArgoCD.

## Table of Contents

- [System Overview](#system-overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Repository Structure](#repository-structure)
- [GitOps Workflow](#gitops-workflow)
- [User Management](#user-management)
- [Cluster Configuration](#cluster-configuration)
- [Accessing the Database](#accessing-the-database)
- [Monitoring and Operations](#monitoring-and-operations)
- [Failover Testing](#failover-testing)
- [Troubleshooting](#troubleshooting)
- [Common Commands](#common-commands)

---

## System Overview

This system provides a production-ready PostgreSQL deployment on Kubernetes with:

- **Postgres Operator**: Manages PostgreSQL clusters using Custom Resource Definitions (CRDs)
- **Patroni**: Provides high availability with automatic failover
- **ArgoCD**: Implements GitOps workflows for configuration management
- **Sealed Secrets**: Enables secure storage of encrypted credentials in Git
- **User Controller**: Custom Kubernetes controller for automated user and role management
- **Spilo**: PostgreSQL container image with Patroni integration

### Key Features

- ✅ Automated PostgreSQL cluster deployment and management
- ✅ High availability with automatic failover (typically 10-30 seconds)
- ✅ GitOps-based configuration management
- ✅ Secure password management with sealed secrets
- ✅ Automated user and role synchronization
- ✅ Rolling updates for configuration changes
- ✅ Point-in-time recovery capabilities
- ✅ Support for PostgreSQL versions 13-17

---

## Architecture

### Components

1. **Postgres Operator** (namespace: `postgres-operator`)

   - Watches for PostgreSQL CRD changes
   - Manages cluster lifecycle (create, update, scale, delete)
   - Handles rolling updates and version upgrades

2. **PostgreSQL Cluster** (namespace: `default`)

   - Highly available PostgreSQL instances with Patroni
   - Configured via `postgresql` CRD
   - Default cluster name: `acid-minimal-cluster`

3. **User Controller** (namespace: `postgres`)

   - Custom Python-based controller
   - Watches ConfigMap and Secrets for user definitions
   - Synchronizes database users and roles
   - Features drift detection and reconciliation

4. **ArgoCD** (namespace: `argocd`)

   - Monitors Git repository for changes
   - Automatically syncs configurations to cluster
   - Manages two applications:
     - `postgres-cluster`: Database cluster configuration
     - `postgres-users`: User management

5. **Sealed Secrets Controller** (namespace: `kube-system`)
   - Encrypts secrets for safe storage in Git
   - Decrypts secrets in the cluster

### Data Flow

```
Developer → Git Push → ArgoCD → Kubernetes → Postgres Operator → PostgreSQL Cluster
                         ↓
                    User Controller → Database Users/Roles
```

---

## Prerequisites

Before using this system, ensure you have:

- Access to a Kubernetes cluster (v1.27+)
- `kubectl` installed and configured
- `kubeseal` CLI tool for sealing secrets
- Python 3.8+ (for user management)
- Git installed
- Docker (if building custom controller images)

---

## Initial Setup

After cloning this repository, **you must run the setup and requirements check scripts**:

### Step 1: Check Requirements

```bash
./check-requirements.sh
```

This verifies that Python 3 and `kubeseal` are installed. If any are missing, install them before proceeding.

### Step 2: Setup Git Hooks

```bash
./setup-hooks.sh
```

This installs the pre-commit hook that automatically seals user secrets before committing, ensuring passwords are never stored in plaintext in Git.

**What the hook does:**

- Detects changes to `zilando-CRDs/UserManifests/edit-users.yaml`
- Runs `seal_users.py` to generate encrypted secrets
- Generates `users.yaml` (ConfigMap without passwords)
- Generates `sealed-users.yaml` (encrypted secrets)
- Stages the generated files and unstages `edit-users.yaml`

---

## Repository Structure

```
.
├── postgres-operator/              # Zalando Postgres Operator source code
│   ├── manifests/                  # Operator deployment manifests
│   ├── charts/                     # Helm charts
│   ├── cmd/                        # Operator main code
│   └── pkg/                        # Operator packages
│
├── zilando-CRDs/                   # PostgreSQL configurations
│   ├── postgres-config/            # Database cluster configurations
│   │   ├── postgres-cluster.yaml   # Main cluster definition
│   │   └── sample-config.yaml      # Configuration examples
│   │
│   ├── UserManifests/              # User management files
│   │   ├── edit-users.yaml         # User definitions (local only)
│   │   ├── users.yaml              # ConfigMap (committed)
│   │   ├── sealed-users.yaml       # Encrypted secrets (committed)
│   │   └── seal_users.py           # Secret sealing script
│   │
│   ├── controller/                 # User controller source
│   │   ├── controller.py           # Main controller logic
│   │   ├── deployment.yaml         # Controller deployment
│   │   ├── rbac.yaml               # RBAC permissions
│   │   ├── Dockerfile              # Container image definition
│   │   └── requirements.txt        # Python dependencies
│   │
│   ├── manifests/                  # ArgoCD application manifests
│   └── pub-cert.pem                # Sealed Secrets public certificate
│
├── hooks/                          # Git hooks (tracked in repo)
│   └── pre-commit                  # Pre-commit hook script
│
├── setup-hooks.sh                  # Hook installation script
├── check-requirements.sh           # Requirements verification script
│
└── Documentation Files:
    ├── guide.md                    # Comprehensive guide
    ├── failover_test.txt           # Failover testing steps
    ├── steps_to_deploy_controller.txt  # Initial deployment steps
    ├── usefull_commands.txt        # Common command reference
    ├── Complete_demo.txt           # Full demo walkthrough
    └── Summary_demo.txt            # Quick demo reference
```

---

## GitOps Workflow

### How GitOps Works in This System

All infrastructure and configuration is defined as code in Git. Changes are made by:

1. **Edit configuration files** in your local repository
2. **Commit and push** changes to Git
3. **ArgoCD detects** changes automatically
4. **ArgoCD synchronizes** the desired state to Kubernetes
5. **Operators apply** changes to the actual resources

### Managed Resources

ArgoCD manages two applications:

2. **postgres-cluster**: Manages PostgreSQL cluster configuration

   - Path: `zilando-CRDs/postgres-config/`
   - Namespace: `default`

3. **postgres-users**: Manages user definitions and secrets
   - Path: `zilando-CRDs/UserManifests/`
   - Namespace: `postgres`

### Accessing ArgoCD

```bash
# Port forward to access ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo
```

Access at: `https://localhost:8080`

- Username: `admin`
- Password: (from command above)

---

## User Management

### Overview

The user management system uses a custom controller that automatically synchronizes database users based on Kubernetes ConfigMaps and Secrets.

### User Definition Structure

Users are defined in `zilando-CRDs/UserManifests/edit-users.yaml`:

```yaml
apiVersion: v1
data:
  users.yaml: |
    users:
      - username: alice
        database: postgres
        password: secure_password_123
        roles:
          - read_only
          - analyst
      - username: bob
        database: postgres
        password: another_password_456
        roles:
          - read_write
kind: ConfigMap
metadata:
  name: postgres-users-config
  namespace: postgres
```

### Adding a New User

1. **Edit the user file:**

   ```bash
   nano zilando-CRDs/UserManifests/edit-users.yaml
   ```

2. **Add user definition:**

   ```yaml
   - username: new_user
     database: postgres
     password: secure_password
     roles:
       - custom_role
   ```

3. **Commit and push:**

   ```bash
   git add zilando-CRDs/UserManifests/edit-users.yaml
   git commit -m "Add new user: new_user"
   git push
   ```

4. **The pre-commit hook automatically:**

   - Generates `users.yaml` (ConfigMap without passwords)
   - Generates `sealed-users.yaml` (encrypted secrets)
   - Stages both files for commit
   - Unstages `edit-users.yaml` (keeps it local only)

5. **Verify user creation:**

   ```bash
   # Watch controller logs
   kubectl logs -f deployment/user-controller -n postgres

   # Check database
   kubectl exec -it acid-minimal-cluster-0 -- psql -U postgres -c "\du"
   ```

### Modifying User Permissions

1. Edit `edit-users.yaml` and change the roles
2. Commit and push changes
3. Controller automatically updates permissions

### Removing a User

1. Remove user entry from `edit-users.yaml`
2. Commit and push
3. Controller automatically deletes the user from the database

### Important Notes

- `edit-users.yaml` is **NOT committed** to Git (contains plaintext passwords)
- `users.yaml` is committed (ConfigMap without passwords)
- `sealed-users.yaml` is committed (encrypted secrets safe for Git)
- User controller runs every 30 seconds to reconcile state

---

## Cluster Configuration

### Cluster Definition

PostgreSQL clusters are defined in `zilando-CRDs/postgres-config/postgres-cluster.yaml`:

```yaml
apiVersion: "acid.zalan.do/v1"
kind: postgresql
metadata:
  name: acid-minimal-cluster
  namespace: default
spec:
  teamId: "acid"
  volume:
    size: 1Gi
  numberOfInstances: 4
  users:
    zalando:
      - superuser
      - createdb
    foo_user: []
  databases:
    foo: zalando
  preparedDatabases:
    bar: {}
  postgresql:
    version: "17"
```

### Common Configuration Changes

#### Scaling the Cluster

Change `numberOfInstances`:

```yaml
numberOfInstances: 3 # Scale to 3 instances
```

Commit and push. ArgoCD will sync and Postgres Operator will add/remove replicas.

#### Adding Resource Limits

```yaml
spec:
  resources:
    requests:
      cpu: 500m
      memory: 500Mi
    limits:
      cpu: 1000m
      memory: 1Gi
```

#### Changing PostgreSQL Version

```yaml
postgresql:
  version: "16" # Downgrade/upgrade PostgreSQL version
```

**Note:** Version changes trigger rolling updates.

#### Adding PostgreSQL Parameters

```yaml
postgresql:
  version: "17"
  parameters:
    max_connections: "200"
    shared_buffers: "256MB"
    work_mem: "4MB"
```

### Making Configuration Changes

1. **Edit cluster configuration:**

   ```bash
   nano zilando-CRDs/postgres-config/postgres-cluster.yaml
   ```

2. **Commit and push:**

   ```bash
   git add zilando-CRDs/postgres-config/postgres-cluster.yaml
   git commit -m "Scale cluster to 3 instances"
   git push
   ```

3. **ArgoCD automatically syncs** (or manually sync via UI)

4. **Monitor changes:**
   ```bash
   kubectl get pods -l application=spilo -w
   ```

---

## Accessing the Database

### Get Database Credentials

```bash
# Get the password
kubectl get secret postgres.acid-minimal-cluster.credentials.postgresql.acid.zalan.do \
  -o jsonpath="{.data.password}" | base64 -d && echo
```

### Connect from Within Cluster

```bash
# Execute bash in pod
kubectl exec -it acid-minimal-cluster-0 -- bash

# Connect to PostgreSQL
psql -U postgres -d postgres
```

### Connect via Port Forward

```bash
# Port forward PostgreSQL
kubectl port-forward pod/acid-minimal-cluster-0 5432:5432

# Connect from local machine (new terminal)
psql -h localhost -p 5432 -U postgres -d postgres
```

### Connect via LoadBalancer (if configured)

```bash
# Edit service to type LoadBalancer
kubectl edit svc acid-minimal-cluster

# Get external IP
kubectl get svc acid-minimal-cluster

# Connect
psql -h <EXTERNAL-IP> -p 5432 -U postgres -d postgres
```

### Common SQL Commands

```sql
-- List all databases
\l

-- Connect to database
\c database_name

-- List all tables
\dt

-- List all users and roles
\du

-- Check permissions
SELECT roleid::regrole AS role, member::regrole AS member
FROM pg_auth_members;

-- Create table
CREATE TABLE test_table (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert data
INSERT INTO test_table (name) VALUES ('Alice'), ('Bob');

-- Query data
SELECT * FROM test_table;
```

---

## Monitoring and Operations

### Check Cluster Status

```bash
# Get all PostgreSQL pods
kubectl get pods -l application=spilo

# Check Patroni cluster status
kubectl exec -it acid-minimal-cluster-0 -- patronictl list
```

Expected output:

```
+ Cluster: acid-minimal-cluster -------+----+-----------+
| Member                | Host        | Role    | State   | TL | Lag  |
+-----------------------+-------------+---------+---------+----+------+
| acid-minimal-cluster-0| 10.244.0.10 | Leader  | running | 1  |      |
| acid-minimal-cluster-1| 10.244.0.11 | Replica | running | 1  | 0    |
| acid-minimal-cluster-2| 10.244.0.12 | Replica | running | 1  | 0    |
+-----------------------+-------------+---------+---------+----+------+
```

### View Logs

```bash
# Postgres Operator logs
kubectl logs -n postgres-operator deployment/postgres-operator --tail=50

# User Controller logs
kubectl logs -f deployment/user-controller -n postgres

# PostgreSQL pod logs
kubectl logs acid-minimal-cluster-0 --tail=100

# Follow logs in real-time
kubectl logs -f acid-minimal-cluster-0
```

### Check Replication Status

```bash
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"
```

### Check Database Sizes

```bash
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c \
  "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database;"
```

---

## Failover Testing

Test the high availability by simulating a primary failure:

### Step 1: Create Test Data

```bash
kubectl exec -i acid-minimal-cluster-0 -- bash -lc "psql -U postgres <<'SQL'
CREATE DATABASE failover_test;
\c failover_test
CREATE TABLE customers (id SERIAL PRIMARY KEY, name TEXT);
INSERT INTO customers (name) VALUES ('Alice'), ('Bob'), ('Charlie');
SQL"

# Verify data
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -d failover_test -c "TABLE customers;"
```

### Step 2: Identify Current Primary

```bash
kubectl exec -it acid-minimal-cluster-0 -- patronictl list
```

### Step 3: Delete Primary Pod

```bash
# Delete the primary (usually pod-0)
kubectl delete pod acid-minimal-cluster-0

# Watch failover happen
kubectl get pods -l application=spilo -w
```

### Step 4: Verify Failover

```bash
# Check new cluster status (wait 10-15 seconds)
kubectl exec -it acid-minimal-cluster-1 -- patronictl list

# Verify data integrity
kubectl exec -i acid-minimal-cluster-1 -- psql -U postgres -d failover_test -c "TABLE customers;"
```

All data should be intact. The replica is promoted to primary automatically.

### Step 5: Test Write on New Primary

```bash
kubectl exec -i acid-minimal-cluster-1 -- psql -U postgres -d failover_test -c \
  "INSERT INTO customers (name) VALUES ('Diana'), ('Eve'), ('Frank');"

kubectl exec -i acid-minimal-cluster-1 -- psql -U postgres -d failover_test -c "TABLE customers;"
```

### Step 6: Verify Old Primary Rejoins as Replica

```bash
# Wait for acid-minimal-cluster-0 to restart
kubectl get pods -l application=spilo

# Check it has all data
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -d failover_test -c "TABLE customers;"
```

**Expected Failover Time:** 10-30 seconds
**Data Loss:** Zero (with synchronous replication)

---

## Troubleshooting

### Git Hook Not Sealing Secrets

**Problem:** Passwords not being sealed automatically

**Solution:**

```bash
# Reinstall hook
./setup-hooks.sh

# Verify hook is executable
ls -la .git/hooks/pre-commit

# Test manually
cd zilando-CRDs/UserManifests
python3 seal_users.py
```

### User Controller Not Creating Users

**Problem:** Users defined but not appearing in database

**Solution:**

```bash
# Check controller logs
kubectl logs deployment/user-controller -n postgres

# Verify ConfigMap exists
kubectl get configmap postgres-users-config -n postgres

# Verify sealed secret exists
kubectl get sealedsecret -n postgres

# Restart controller
kubectl rollout restart deployment/user-controller -n postgres
```

### PostgreSQL Pod Not Starting

**Solution:**

```bash
# Check pod status
kubectl describe pod acid-minimal-cluster-0

# Check operator logs
kubectl logs -n postgres-operator deployment/postgres-operator

# Check PVC
kubectl get pvc

# Check events
kubectl get events --sort-by=.lastTimestamp
```

### ArgoCD Not Syncing

**Solution:**

```bash
# Check application status
kubectl get application postgres-cluster -n argocd

# View sync errors
kubectl describe application postgres-cluster -n argocd

# Manually sync
kubectl patch application postgres-cluster -n argocd \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"true"}}}' --type=merge
```

### Certificate Mismatch for Sealed Secrets

**Solution:**

```bash
# Fetch current certificate
kubeseal --fetch-cert > zilando-CRDs/pub-cert.pem

# Reseal secrets
cd zilando-CRDs/UserManifests
python3 seal_users.py
```

---

## Common Commands

### Quick Reference

```bash
# Check cluster status
kubectl exec -it acid-minimal-cluster-0 -- patronictl list

# Connect to database
kubectl exec -it acid-minimal-cluster-0 -- psql -U postgres

# Watch user controller logs
kubectl logs -f deployment/user-controller -n postgres

# Port forward ArgoCD
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Sync changes (Git workflow)
git add .
git commit -m "Your message"
git push

# Restart user controller
kubectl rollout restart deployment/user-controller -n postgres

# Check pod status
kubectl get pods -l application=spilo

# Check replication
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c \
  "SELECT * FROM pg_stat_replication;"

# Build and push controller image
docker build -t <dockerhub-user>/user-controller:latest zilando-CRDs/controller/
docker push <dockerhub-user>/user-controller:latest
kubectl rollout restart deployment/user-controller -n postgres
```

---

## Additional Resources

- **Comprehensive Guide:** See [guide.md](guide.md) for detailed instructions
- **Failover Testing:** See [failover_test.txt](failover_test.txt)
- **Deployment Steps:** See [steps_to_deploy_controller.txt](steps_to_deploy_controller.txt)
- **Command Reference:** See [usefull_commands.txt](usefull_commands.txt)
- **Demo Walkthroughs:** See [Complete_demo.txt](Complete_demo.txt) and [Summary_demo.txt](Summary_demo.txt)

### Official Documentation

- [Postgres Operator](https://postgres-operator.readthedocs.io)
- [Patroni](https://patroni.readthedocs.io)
- [ArgoCD](https://argo-cd.readthedocs.io)
- [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets)

---

## Support

For issues or questions:

1. Check this README and the comprehensive [guide.md](guide.md)
2. Review relevant logs
3. Check the troubleshooting section
4. Open an issue in the repository

---

**Repository:** Gitops-postgres  
**Owner:** Umar-Mahmood
