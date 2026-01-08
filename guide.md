# Complete Guide: PostgreSQL Operator with GitOps

This comprehensive guide will walk you through everything you need to know to work with the PostgreSQL Operator system, from initial setup to database management, user operations, monitoring, and failover testing.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [Repository Setup](#repository-setup)
4. [Accessing the Database](#accessing-the-database)
5. [User Management](#user-management)
6. [GitOps Workflow](#gitops-workflow)
7. [Monitoring and Logs](#monitoring-and-logs)
8. [Failover Testing](#failover-testing)
9. [ArgoCD Management](#argocd-management)
10. [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before starting, ensure you have:

- Access to a Kubernetes cluster
- `kubectl` installed and configured
- Docker installed (for building controller images)
- Python 3 installed
- `kubeseal` CLI tool installed
- Git installed
- SSH access to your VM/server

---

## Initial Setup

### Step 1: Install ArgoCD

ArgoCD manages the GitOps workflow for your PostgreSQL configurations.

```bash
# Create ArgoCD namespace and install
kubectl create ns argocd && \
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for pods to be ready
kubectl -n argocd get pods

# Get the initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo

# Port forward to access ArgoCD UI (run in a separate terminal)
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

Access ArgoCD UI at: `https://localhost:8080`
- Username: `admin`
- Password: (from the command above)

### Step 2: Install Sealed Secrets Controller

Sealed Secrets allows you to store encrypted secrets safely in Git.

```bash
# Install Bitnami Sealed Secrets
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.25.0/controller.yaml

# Fetch the public certificate for sealing secrets
kubeseal --fetch-cert > pub-cert.pem
```

### Step 3: Install PostgreSQL Operator

```bash
# Apply the operator manifests
kubectl apply -k ./postgres-operator/manifests/

# Verify the operator is running
kubectl get pods -n default
```

---

## Repository Setup

### Clone the Repository

```bash
# SSH to your VM first
ssh user@your-vm-address

# Clone the repository
git clone https://github.com/Umar-Mahmood/Gitops-postgres.git
cd Gitops-postgres
```

### Setup Git Hooks

**IMPORTANT:** After cloning, you must set up Git hooks to automatically seal secrets.

```bash
# Run the setup script from the root
./setup-hooks.sh

# Verify the hook is installed
ls -la .git/hooks/pre-commit
```

The pre-commit hook ensures that user passwords are automatically sealed before committing.

---

## Accessing the Database

### Step 1: Deploy a PostgreSQL Cluster

```bash
# Apply the PostgreSQL cluster manifest
kubectl apply -f zilando-CRDs/postgres-config/postgres-cluster.yaml

# Wait for the cluster to be ready
kubectl get pods -l application=spilo

# You should see pods like:
# acid-minimal-cluster-0
# acid-minimal-cluster-1
```

### Step 2: Get Database Credentials

```bash
# Get the secret containing database credentials
kubectl get secret postgres.acid-minimal-cluster.credentials.postgresql.acid.zalan.do -o yaml

# Decode the password
kubectl get secret postgres.acid-minimal-cluster.credentials.postgresql.acid.zalan.do -o jsonpath="{.data.password}" | base64 -d && echo
```

### Step 3: Connect to PostgreSQL

**Option A: Direct Connection via kubectl exec**

```bash
# Connect to the primary pod
kubectl exec -it acid-minimal-cluster-0 -- bash

# Once inside the pod, connect to PostgreSQL
psql -U postgres -d postgres
```

**Option B: Connect from Another Pod**

```bash
# Execute psql directly
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -d postgres
```

### Step 4: Run Basic SQL Commands

```sql
-- List all databases
\l

-- Connect to a database
\c postgres

-- List all tables
\dt

-- List all users and roles
\du

-- Create a test database
CREATE DATABASE test_db;

-- Create a test table
CREATE TABLE test_table (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert test data
INSERT INTO test_table (name) VALUES ('Alice'), ('Bob'), ('Charlie');

-- Query data
SELECT * FROM test_table;

-- Check permissions
SELECT roleid::regrole AS role, member::regrole AS member
FROM pg_auth_members;
```

### Step 5: Check Cluster Status with Patroni

```bash
# Check Patroni cluster status
kubectl exec -it acid-minimal-cluster-0 -- patronictl list
```

This shows:
- Current leader (master)
- Replica status
- Replication lag
- Timeline information

---

## User Management

### Understanding the User Management System

The system uses a custom controller that watches for user configuration changes and automatically creates/updates PostgreSQL users.

**File Structure:**
- `edit-users.yaml` - Source file with plaintext passwords (local only, not committed)
- `users.yaml` - ConfigMap without passwords (committed to Git)
- `sealed-users.yaml` - Encrypted secrets (committed to Git)

### Step 1: Setup User Controller

```bash
# Create namespace if not exists
kubectl create namespace postgres || true

# Create the initial postgres credentials secret
kubectl create secret generic postgres.credentials \
  -n postgres \
  --from-literal=password='postgres' \
  --dry-run=client -o yaml | kubectl apply -f -

# Copy the cluster credentials to postgres namespace
kubectl get secret postgres.acid-minimal-cluster.credentials.postgresql.acid.zalan.do -n default -o yaml \
  | sed 's/namespace: default/namespace: postgres/' \
  | kubectl apply -f -

# Deploy the user controller
kubectl apply -f zilando-CRDs/controller/rbac.yaml
kubectl apply -f zilando-CRDs/controller/deployment.yaml

# Verify controller is running
kubectl get pods -n postgres
```

### Step 2: Add a New User

```bash
# Navigate to user manifests directory
cd zilando-CRDs/UserManifests

# Edit the user file (this file contains passwords)
vim edit-users.yaml
```

**Example user configuration:**

```yaml
apiVersion: v1
data:
  users.yaml: |
    users:
      - username: john_doe
        database: postgres
        password: my_secure_password_123
        roles:
          - writer
      - username: jane_smith
        database: test_db
        password: another_secure_pass_456
        roles:
          - reader
kind: ConfigMap
metadata:
  name: postgres-users-config
  namespace: postgres
```

### Step 3: Commit and Push Changes

```bash
# Stage the edit file
git add edit-users.yaml

# Commit (the pre-commit hook will automatically seal secrets)
git commit -m "Add new users: john_doe and jane_smith"

# What the hook does automatically:
# 1. Runs seal_users.py
# 2. Generates users.yaml (without passwords)
# 3. Generates sealed-users.yaml (encrypted)
# 4. Stages both generated files
# 5. Unstages edit-users.yaml (keeps it local only)

# Push to repository
git push origin main
```

### Step 4: Verify User Creation

```bash
# Watch controller logs
kubectl logs -f deployment/user-controller -n postgres

# You should see logs like:
# "Created user: john_doe"
# "Granted role writer to john_doe"

# Verify in PostgreSQL
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c "\du"

# Test user connection
kubectl exec -i acid-minimal-cluster-0 -- psql -U john_doe -d postgres -c "SELECT current_user;"
```

### Step 5: Delete a User

```bash
# Edit the user file and remove the user
vim edit-users.yaml

# Remove the user entry, then commit
git add edit-users.yaml
git commit -m "Remove user john_doe"
git push origin main

# Watch controller logs
kubectl logs -f deployment/user-controller -n postgres

# Verify user is deleted
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c "\du"
```

### Step 6: Modify User Permissions

```bash
# Edit the user file and change roles
vim edit-users.yaml

# Change from 'reader' to 'writer' or vice versa
# Then commit and push

git add edit-users.yaml
git commit -m "Update user permissions"
git push origin main
```

---

## GitOps Workflow

### How GitOps Works in This System

1. **Infrastructure as Code**: All PostgreSQL configurations are stored in Git
2. **ArgoCD Sync**: ArgoCD monitors the Git repository and applies changes
3. **Automated Reconciliation**: Controllers ensure the actual state matches desired state

### Setting Up ArgoCD Applications

**Application 1: PostgreSQL Cluster Configuration**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: postgres-cluster
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/Umar-Mahmood/Gitops-postgres
    targetRevision: main
    path: zilando-CRDs/postgres-config
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Application 2: User Management**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: postgres-users
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/Umar-Mahmood/Gitops-postgres
    targetRevision: main
    path: zilando-CRDs/UserManifests
  destination:
    server: https://kubernetes.default.svc
    namespace: postgres
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Making Configuration Changes

**Example: Scaling the Cluster**

```bash
# Edit the cluster manifest
vim zilando-CRDs/postgres-config/postgres-cluster.yaml

# Change numberOfInstances from 2 to 3
# Before:
#   numberOfInstances: 2
# After:
#   numberOfInstances: 3

# Commit and push
git add zilando-CRDs/postgres-config/postgres-cluster.yaml
git commit -m "Scale cluster to 3 instances"
git push origin main

# Watch ArgoCD sync the changes
# ArgoCD will detect the change and apply it automatically
# Or manually sync via UI/CLI

# Verify new pod is created
kubectl get pods -l application=spilo
```

**Example: Changing PostgreSQL Configuration**

```bash
# Edit cluster manifest
vim zilando-CRDs/postgres-config/postgres-cluster.yaml

# Add PostgreSQL parameters
spec:
  postgresql:
    parameters:
      max_connections: "200"
      shared_buffers: "256MB"
      work_mem: "4MB"

# Commit and push
git add zilando-CRDs/postgres-config/postgres-cluster.yaml
git commit -m "Update PostgreSQL configuration"
git push origin main

# The operator will perform a rolling restart
kubectl get pods -l application=spilo -w
```

---

## Monitoring and Logs

### Checking Operator Logs

```bash
# Get postgres operator pod name
kubectl get pods -n default | grep postgres-operator

# View operator logs
kubectl logs -f postgres-operator-<pod-id> -n default

# Filter for specific cluster
kubectl logs postgres-operator-<pod-id> -n default | grep acid-minimal-cluster
```

### Checking User Controller Logs

```bash
# Watch user controller logs in real-time
kubectl logs -f deployment/user-controller -n postgres

# Get last 100 lines
kubectl logs --tail=100 deployment/user-controller -n postgres

# Filter for specific user
kubectl logs deployment/user-controller -n postgres | grep john_doe
```

### Checking PostgreSQL Logs

```bash
# View logs from the primary pod
kubectl logs acid-minimal-cluster-0

# View logs from a replica
kubectl logs acid-minimal-cluster-1

# Follow logs in real-time
kubectl logs -f acid-minimal-cluster-0

# View Patroni logs specifically
kubectl logs acid-minimal-cluster-0 | grep patroni
```

### Checking Cluster Health

```bash
# Get pod status
kubectl get pods -l application=spilo

# Check Patroni cluster health
kubectl exec -it acid-minimal-cluster-0 -- patronictl list

# Check replication status
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Check database sizes
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database;"
```

### Monitoring ArgoCD Applications

```bash
# List all applications
kubectl get applications -n argocd

# Check application status
kubectl get application postgres-cluster -n argocd -o yaml

# View sync history
kubectl describe application postgres-cluster -n argocd
```

---

## Failover Testing

Failover testing ensures that your PostgreSQL cluster can automatically recover when the primary database fails.

### Step 1: Identify the Current Primary

```bash
# Check which pod is the leader
kubectl exec -it acid-minimal-cluster-0 -- patronictl list

# Output will show something like:
# + Cluster: acid-minimal-cluster (7234567890123456789) -+----+-----------+
# | Member                | Host           | Role    | State   | TL | Lag  |
# +-----------------------+----------------+---------+---------+----+------+
# | acid-minimal-cluster-0| 10.244.0.10    | Leader  | running | 1  |      |
# | acid-minimal-cluster-1| 10.244.0.11    | Replica | running | 1  | 0    |
# +-----------------------+----------------+---------+---------+----+------+
```

### Step 2: Create Test Data

```bash
# Create a test database and populate it
kubectl exec -i acid-minimal-cluster-0 -- bash -lc "psql -U postgres <<'SQL'
CREATE DATABASE failover_test;
\c failover_test
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
INSERT INTO customers (name) VALUES ('Alice'), ('Bob'), ('Charlie');
SQL"

# Verify data was created
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -d failover_test -c "TABLE customers;"
```

Expected output:
```
 id |  name   |         created_at
----+---------+----------------------------
  1 | Alice   | 2025-11-24 10:30:00.123456
  2 | Bob     | 2025-11-24 10:30:00.123457
  3 | Charlie | 2025-11-24 10:30:00.123458
```

### Step 3: Simulate Primary Failure

```bash
# Delete the primary pod
kubectl delete pod acid-minimal-cluster-0

# Watch the failover happen
kubectl get pods -l application=spilo -w

# Check Patroni status (wait 10-15 seconds)
kubectl exec -it acid-minimal-cluster-1 -- patronictl list
```

What happens:
1. Primary pod is deleted
2. Patroni detects failure
3. Replica is promoted to primary (usually within 10-30 seconds)
4. Old primary pod is recreated as a replica

### Step 4: Verify Data Integrity

```bash
# Wait for the new primary to be ready
sleep 20

# Check data in the new primary
kubectl exec -i acid-minimal-cluster-1 -- psql -U postgres -d failover_test -c "TABLE customers;"

# All data should still be present
```

### Step 5: Test Write Operations on New Primary

```bash
# Insert new data into the new primary
kubectl exec -i acid-minimal-cluster-1 -- psql -U postgres -d failover_test -c "INSERT INTO customers (name) VALUES ('Diana'), ('Eve'), ('Frank');"

# Verify new data
kubectl exec -i acid-minimal-cluster-1 -- psql -U postgres -d failover_test -c "TABLE customers;"
```

Expected output:
```
 id |  name   |         created_at
----+---------+----------------------------
  1 | Alice   | 2025-11-24 10:30:00.123456
  2 | Bob     | 2025-11-24 10:30:00.123457
  3 | Charlie | 2025-11-24 10:30:00.123458
  4 | Diana   | 2025-11-24 10:32:15.654321
  5 | Eve     | 2025-11-24 10:32:15.654322
  6 | Frank   | 2025-11-24 10:32:15.654323
```

### Step 6: Verify Replication to Old Primary

```bash
# Wait for old primary to rejoin as replica
kubectl get pods -l application=spilo

# Once acid-minimal-cluster-0 is running again, check data
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -d failover_test -c "TABLE customers;"

# Should see all 6 rows including the new ones
```

### Step 7: Check Replication Lag

```bash
# Check replication status
kubectl exec -i acid-minimal-cluster-1 -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Should show acid-minimal-cluster-0 as a replica with minimal lag
```

### Failover Metrics to Monitor

- **Failover Time**: Time between primary failure and new primary being ready
- **Data Loss**: Should be zero with synchronous replication
- **Replica Catchup**: Time for old primary to sync after rejoining
- **Application Downtime**: Depends on connection retry logic

---

## ArgoCD Management

### Accessing ArgoCD

```bash
# Port forward to ArgoCD server
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Access at: https://localhost:8080
```

### Managing Applications via CLI

```bash
# Install ArgoCD CLI (if not installed)
# Linux:
curl -sSL -o argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x argocd
sudo mv argocd /usr/local/bin/

# Login to ArgoCD
argocd login localhost:8080

# List applications
argocd app list

# Sync an application
argocd app sync postgres-cluster

# Get application details
argocd app get postgres-cluster

# View sync history
argocd app history postgres-cluster

# Rollback to previous version
argocd app rollback postgres-cluster <revision-number>
```

### Managing Applications via UI

1. Access UI at `https://localhost:8080`
2. Login with admin credentials
3. View application status and sync state
4. Manually trigger sync if needed
5. View sync history and diff
6. Rollback to previous versions

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Git Hooks Not Working

**Problem**: Passwords not being sealed automatically

**Solution**:
```bash
# Reinstall the hook
./setup-hooks.sh

# Verify hook exists and is executable
ls -la .git/hooks/pre-commit

# Check hook contents
cat .git/hooks/pre-commit

# Test manually
cd zilando-CRDs/UserManifests
python3 seal_users.py
```

#### 2. User Controller Not Creating Users

**Problem**: Users defined but not created in PostgreSQL

**Solution**:
```bash
# Check controller logs
kubectl logs deployment/user-controller -n postgres

# Check if ConfigMap exists
kubectl get configmap postgres-users-config -n postgres

# Check if sealed secret exists
kubectl get sealedsecret postgres-users-sealed -n postgres

# Restart controller
kubectl rollout restart deployment/user-controller -n postgres

# Verify controller has correct permissions
kubectl get clusterrolebinding | grep user-controller
```

#### 3. PostgreSQL Pod Not Starting

**Problem**: Pod stuck in pending or error state

**Solution**:
```bash
# Check pod status
kubectl describe pod acid-minimal-cluster-0

# Check events
kubectl get events --sort-by=.lastTimestamp

# Check operator logs
kubectl logs postgres-operator-<pod-id> -n default

# Check PVC status
kubectl get pvc

# Check if storage class exists
kubectl get storageclass
```

#### 4. Replication Lag

**Problem**: Replica is lagging behind primary

**Solution**:
```bash
# Check replication status
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Check network connectivity
kubectl exec -it acid-minimal-cluster-1 -- ping acid-minimal-cluster-0

# Check disk performance
kubectl exec -it acid-minimal-cluster-1 -- df -h

# Check PostgreSQL logs for errors
kubectl logs acid-minimal-cluster-1 | grep ERROR
```

#### 5. ArgoCD Not Syncing

**Problem**: Changes pushed to Git but not applied

**Solution**:
```bash
# Check ArgoCD application status
kubectl get application postgres-cluster -n argocd

# Check sync errors
kubectl describe application postgres-cluster -n argocd

# Manually trigger sync
argocd app sync postgres-cluster

# Check if repository is accessible
kubectl logs -n argocd deployment/argocd-repo-server

# Refresh repository
argocd app get postgres-cluster --refresh
```

#### 6. Sealed Secret Cannot Be Decrypted

**Problem**: SealedSecret not creating actual Secret

**Solution**:
```bash
# Check sealed-secrets controller logs
kubectl logs -n kube-system -l name=sealed-secrets-controller

# Verify certificate matches
kubeseal --fetch-cert > current-cert.pem
diff pub-cert.pem current-cert.pem

# If different, update and reseal
mv current-cert.pem zilando-CRDs/pub-cert.pem
cd zilando-CRDs/UserManifests
python3 seal_users.py

# Check SealedSecret status
kubectl get sealedsecret postgres-users-sealed -n postgres -o yaml
```

#### 7. Connection Refused to Database

**Problem**: Cannot connect to PostgreSQL

**Solution**:
```bash
# Check if pod is running
kubectl get pod acid-minimal-cluster-0

# Check if PostgreSQL is listening
kubectl exec -it acid-minimal-cluster-0 -- netstat -tuln | grep 5432

# Check Patroni status
kubectl exec -it acid-minimal-cluster-0 -- patronictl list

# Test connection from within cluster
kubectl run -it --rm debug --image=postgres:15 --restart=Never -- psql -h acid-minimal-cluster -U postgres

# Check service
kubectl get svc | grep acid-minimal-cluster
```

### Debugging Commands Quick Reference

```bash
# Get all resources in namespace
kubectl get all -n postgres

# Describe any resource
kubectl describe <resource-type> <resource-name>

# Get events sorted by time
kubectl get events --sort-by=.lastTimestamp

# Get logs with timestamps
kubectl logs <pod-name> --timestamps=true

# Get previous pod logs (if crashed)
kubectl logs <pod-name> --previous

# Execute shell in pod
kubectl exec -it <pod-name> -- /bin/bash

# Port forward a service
kubectl port-forward svc/<service-name> <local-port>:<remote-port>

# Get resource YAML
kubectl get <resource-type> <resource-name> -o yaml

# Watch resources
kubectl get pods -w
```

---

## Building and Deploying Custom Controller

If you need to modify the user controller:

```bash
# Make changes to controller code
vim zilando-CRDs/controller/main.py

# Build new Docker image (replace with your Docker Hub username)
cd zilando-CRDs/controller
docker build -t <your-dockerhub-username>/user-controller:latest .

# Push to Docker Hub
docker push <your-dockerhub-username>/user-controller:latest

# Update deployment manifest
vim zilando-CRDs/controller/deployment.yaml
# Change image to: <your-dockerhub-username>/user-controller:latest

# Apply updated deployment
kubectl apply -f zilando-CRDs/controller/deployment.yaml

# Or restart existing deployment
kubectl rollout restart deployment/user-controller -n postgres

# Watch rollout status
kubectl rollout status deployment/user-controller -n postgres
```

---

## Best Practices

### Security
- Always use sealed secrets for sensitive data
- Never commit plaintext passwords to Git
- Rotate database credentials regularly
- Use RBAC to limit access to resources
- Enable network policies for pod-to-pod communication

### Operations
- Always test changes in a non-production environment first
- Monitor replication lag regularly
- Set up alerts for pod failures and high resource usage
- Perform regular backups (configure in operator)
- Document all manual interventions

### GitOps
- Use descriptive commit messages
- Review changes before pushing
- Use ArgoCD's sync windows for production changes
- Keep ArgoCD applications in sync
- Use Git tags for production releases

### Database Management
- Regular VACUUM operations for table maintenance
- Monitor connection pool usage
- Set appropriate resource limits
- Use read replicas for read-heavy workloads
- Plan for capacity before scaling

---

## Quick Command Reference

```bash
# SSH to VM
ssh user@vm-address

# Check cluster status
kubectl exec -it acid-minimal-cluster-0 -- patronictl list

# Connect to database
kubectl exec -it acid-minimal-cluster-0 -- psql -U postgres

# Watch user controller logs
kubectl logs -f deployment/user-controller -n postgres

# Port forward ArgoCD
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Sync configuration changes
git add . && git commit -m "message" && git push

# Restart controller
kubectl rollout restart deployment/user-controller -n postgres

# Check pod status
kubectl get pods -l application=spilo

# Trigger failover (delete primary)
kubectl delete pod acid-minimal-cluster-0

# Check replication status
kubectl exec -i acid-minimal-cluster-0 -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"
```

---

## Additional Resources

- [Postgres Operator Documentation](https://postgres-operator.readthedocs.io)
- [Patroni Documentation](https://patroni.readthedocs.io)
- [ArgoCD Documentation](https://argo-cd.readthedocs.io)
- [Sealed Secrets Documentation](https://github.com/bitnami-labs/sealed-secrets)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

---

## Support and Contribution

For issues or questions:
1. Check this guide first
2. Review logs for error messages
3. Check operator documentation
4. Open an issue in the repository

When reporting issues, include:
- Description of the problem
- Steps to reproduce
- Relevant logs
- Kubernetes version
- Operator version

---

**Last Updated**: November 24, 2025
