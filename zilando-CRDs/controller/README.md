# PostgreSQL User and Role Management Controller

A robust, intelligent Kubernetes controller for managing PostgreSQL users and roles based on ConfigMaps and Secrets.

## 🌟 Features

### Core Functionality

- ✅ **Full CRUD Operations**: Create, Read, Update, and Delete PostgreSQL users and roles
- 🔄 **Automatic Role Management**: Dynamically creates roles before assigning to users
- 🎯 **Intelligent Reconciliation**: Compares desired vs actual state and applies only necessary changes
- 🔐 **Secure Password Management**: Retrieves passwords from Kubernetes Secrets

### Advanced Capabilities

- 📊 **Drift Detection**: Maintains local state file to detect configuration drift
- 🔁 **Exponential Backoff Retry**: Handles transient errors with intelligent retry logic
- 🏊 **Connection Pooling**: Efficient database connection management
- 💾 **State Persistence**: Tracks last applied configuration in `/tmp/users_state.json`
- 🧪 **Dry-Run Mode**: Preview changes without applying them
- 📈 **Prometheus Metrics**: Built-in metrics for monitoring and observability
- 🔒 **Transaction Safety**: All multi-step operations wrapped in transactions
- 🛡️ **SQL Injection Protection**: Uses parameterized queries with `psycopg2.sql`

### Reliability Features

- 🔄 Exponential backoff for API and database errors
- 📝 Structured JSON logging with severity levels
- 🎯 Idempotent operations (safe to run repeatedly)
- ⚡ Graceful error handling and recovery
- 🧹 Proper resource cleanup on shutdown

## 📋 Prerequisites

- Kubernetes cluster with appropriate RBAC permissions
- PostgreSQL database (Zalando Postgres Operator recommended)
- Python 3.8+
- Kubernetes Secrets for user passwords
- ConfigMap with user specifications

## 🚀 Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

The controller supports the following environment variables:

| Variable             | Default                                          | Description                          |
| -------------------- | ------------------------------------------------ | ------------------------------------ |
| `NAMESPACE`          | `postgres`                                       | Kubernetes namespace                 |
| `CONFIGMAP_NAME`     | `postgres-users-config`                          | ConfigMap name containing users.yaml |
| `DB_HOST`            | `acid-minimal-cluster.default.svc.cluster.local` | PostgreSQL host                      |
| `DB_PORT`            | `5432`                                           | PostgreSQL port                      |
| `DB_NAME`            | `postgres`                                       | PostgreSQL database name             |
| `DB_USER`            | `postgres`                                       | PostgreSQL admin user                |
| `DB_PASS`            | `postgres`                                       | PostgreSQL admin password            |
| `SYNC_INTERVAL`      | `30`                                             | Reconciliation interval (seconds)    |
| `STATE_FILE`         | `/tmp/users_state.json`                          | Path to state file                   |
| `DRY_RUN`            | `false`                                          | Enable dry-run mode                  |
| `MAX_RETRIES`        | `5`                                              | Maximum retry attempts               |
| `RETRY_BACKOFF_BASE` | `2.0`                                            | Exponential backoff base             |
| `DB_POOL_MIN_CONN`   | `1`                                              | Minimum database connections         |
| `DB_POOL_MAX_CONN`   | `5`                                              | Maximum database connections         |

### 3. Create ConfigMap

Create a ConfigMap with your user specifications:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-users-config
  namespace: postgres
data:
  users.yaml: |
    users:
      - username: alice
        database: myapp
        roles:
          - read_only
          - analyst
      - username: bob
        database: myapp
        roles:
          - read_write
          - developer
```

### 4. Create User Secrets

Each user needs a corresponding secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: user-alice-secret
  namespace: postgres
type: Opaque
data:
  password: <base64-encoded-password>
```

### 5. Deploy Controller

#### Local Testing

```bash
python controller.py
```

#### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres-user-controller
  namespace: postgres
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres-user-controller
  template:
    metadata:
      labels:
        app: postgres-user-controller
    spec:
      serviceAccountName: postgres-controller
      containers:
        - name: controller
          image: your-registry/postgres-controller:latest
          env:
            - name: DB_HOST
              value: "acid-minimal-cluster.postgres.svc.cluster.local"
            - name: DB_USER
              valueFrom:
                secretKeyRef:
                  name: postgres-admin-credentials
                  key: username
            - name: DB_PASS
              valueFrom:
                secretKeyRef:
                  name: postgres-admin-credentials
                  key: password
          volumeMounts:
            - name: state
              mountPath: /tmp
      volumes:
        - name: state
          emptyDir: {}
```

## 🎮 Usage

### Basic Operation

The controller runs continuously and reconciles state every `SYNC_INTERVAL` seconds:

1. Fetches desired state from ConfigMap
2. Compares with actual database state
3. Detects drift
4. Applies necessary changes:
   - Creates missing roles
   - Creates new users
   - Updates user role memberships
   - Deletes removed users
5. Saves state to local file
6. Reports metrics

### Dry-Run Mode

Preview changes without applying them:

```bash
export DRY_RUN=true
python controller.py
```

Output example:

```
[DRY-RUN] Would create role: analyst
[DRY-RUN] Would create user: alice with roles ['read_only', 'analyst']
[DRY-RUN] Would grant roles to bob: {'developer'}
```

### Monitoring

#### Logs

The controller outputs structured JSON logs:

```json
{
  "timestamp": "2025-10-29T10:30:45.123456",
  "level": "INFO",
  "module": "postgres-controller",
  "message": "✅ Created user: alice"
}
```

#### Metrics

Access Prometheus metrics via the `Metrics` class:

```python
controller.metrics.export_prometheus()
```

Available metrics:

- `postgres_controller_reconciliations_total` - Total reconciliation cycles
- `postgres_controller_last_reconciliation_timestamp` - Last reconciliation timestamp
- `postgres_controller_drift_total` - Total drift detections
- `postgres_controller_users_managed` - Current managed users
- `postgres_controller_roles_managed` - Current managed roles
- `postgres_controller_errors_total` - Total errors
- `postgres_controller_last_error_timestamp` - Last error timestamp

#### Reconciliation Summary

After each cycle, the controller prints a summary:

```
============================================================
📊 Reconciliation Summary:
  • Users created: 2
  • Users updated: 1
  • Users deleted: 0
  • Roles created: 3
  • Roles deleted: 0
  • Drift detected: 3
  • Errors: 0
  • Duration: 1.23s
============================================================
```

## 🏗️ Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────┐
│           PostgresUserController                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  Kubernetes  │  │   Database   │  │    State     │ │
│  │    Client    │  │    Client    │  │   Manager    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│         │                  │                  │         │
│         ▼                  ▼                  ▼         │
│  ┌──────────────────────────────────────────────────┐  │
│  │         Reconciliation Loop                      │  │
│  │  1. Fetch ConfigMap                              │  │
│  │  2. Load previous state                          │  │
│  │  3. Fetch database state                         │  │
│  │  4. Detect drift                                 │  │
│  │  5. Reconcile roles                              │  │
│  │  6. Reconcile users                              │  │
│  │  7. Save new state                               │  │
│  │  8. Update metrics                               │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Key Classes

- **`Config`**: Centralized configuration from environment variables
- **`UserSpec`**: Data model for user specifications
- **`ReconciliationStats`**: Tracks statistics for each reconciliation cycle
- **`Metrics`**: Prometheus-compatible metrics collection
- **`KubernetesClient`**: All Kubernetes API interactions
- **`DatabaseClient`**: All PostgreSQL operations with connection pooling
- **`StateManager`**: Persistent state management for drift detection
- **`PostgresUserController`**: Main reconciliation logic

### State Management

The controller maintains state in `/tmp/users_state.json`:

```json
{
  "alice": {
    "username": "alice",
    "database": "myapp",
    "roles": ["read_only", "analyst"],
    "privileges": null
  },
  "bob": {
    "username": "bob",
    "database": "myapp",
    "roles": ["read_write", "developer"],
    "privileges": null
  }
}
```
