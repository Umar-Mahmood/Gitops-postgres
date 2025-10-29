"""
PostgreSQL User and Role Management Controller for Kubernetes

This controller manages PostgreSQL users and roles based on Kubernetes ConfigMaps and Secrets.
It provides automatic reconciliation, drift detection, and comprehensive error handling.

Features:
- CRUD operations for users and roles
- Drift detection and automatic reconciliation
- State persistence for change tracking
- Exponential backoff retry logic
- Structured logging with severity levels
- Dry-run mode support
- Prometheus metrics exposure
- Transaction-based updates for consistency
"""

import os
import sys
import time
import yaml
import json
import base64
import logging
import psycopg2
from psycopg2 import sql, pool
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from datetime import datetime
from typing import Dict, Set, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib

# ANSI color codes
BLUE = "\033[94m"
RED = "\033[91m"
WHITE = "\033[97m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("postgres-controller")


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Controller configuration loaded from environment variables"""
    
    # Kubernetes settings
    NAMESPACE = os.getenv("NAMESPACE", "postgres")
    CONFIGMAP_NAME = os.getenv("CONFIGMAP_NAME", "postgres-users-config")
    
    # PostgreSQL settings
    DB_HOST = os.getenv("DB_HOST", "acid-minimal-cluster.default.svc.cluster.local")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "postgres")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS", "postgres")
    
    # Controller settings
    SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "30"))
    STATE_FILE = os.getenv("STATE_FILE", "/tmp/users_state.json")
    DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
    RETRY_BACKOFF_BASE = float(os.getenv("RETRY_BACKOFF_BASE", "2.0"))
    
    # Connection pool settings
    DB_POOL_MIN_CONN = int(os.getenv("DB_POOL_MIN_CONN", "1"))
    DB_POOL_MAX_CONN = int(os.getenv("DB_POOL_MAX_CONN", "5"))
    
    # System roles to exclude from management
    SYSTEM_ROLES = {
        'postgres', 'pg_monitor', 'pg_read_all_settings', 'pg_read_all_stats',
        'pg_stat_scan_tables', 'pg_read_server_files', 'pg_write_server_files',
        'pg_execute_server_program', 'pg_signal_backend', 'rds_superuser'
    }


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class UserSpec:
    """User specification from ConfigMap"""
    username: str
    database: str
    roles: List[str]
    privileges: Optional[Dict[str, List[str]]] = None
    
    def __hash__(self):
        """Generate hash for change detection"""
        content = f"{self.username}:{self.database}:{sorted(self.roles)}"
        if self.privileges:
            content += f":{sorted(self.privileges.items())}"
        return int(hashlib.sha256(content.encode()).hexdigest(), 16)


@dataclass
class ReconciliationStats:
    """Statistics for a reconciliation cycle"""
    users_created: int = 0
    users_updated: int = 0
    users_deleted: int = 0
    roles_created: int = 0
    roles_deleted: int = 0
    drift_detected: int = 0
    errors: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    def to_dict(self) -> dict:
        return {
            **asdict(self),
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': self.duration_seconds()
        }


# ============================================================================
# METRICS (Prometheus-compatible)
# ============================================================================

class Metrics:
    """Simple in-memory metrics for Prometheus exposition"""
    
    def __init__(self):
        self.reconciliation_count = 0
        self.last_reconciliation_timestamp = 0
        self.drift_count = 0
        self.users_managed = 0
        self.roles_managed = 0
        self.last_error_timestamp = 0
        self.error_count = 0
        
    def record_reconciliation(self, stats: ReconciliationStats):
        """Record metrics from a reconciliation cycle"""
        self.reconciliation_count += 1
        self.last_reconciliation_timestamp = time.time()
        self.drift_count += stats.drift_detected
        self.error_count += stats.errors
        if stats.errors > 0:
            self.last_error_timestamp = time.time()
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format"""
        return f"""# HELP postgres_controller_reconciliations_total Total number of reconciliation cycles
# TYPE postgres_controller_reconciliations_total counter
postgres_controller_reconciliations_total {self.reconciliation_count}

# HELP postgres_controller_last_reconciliation_timestamp Timestamp of last reconciliation
# TYPE postgres_controller_last_reconciliation_timestamp gauge
postgres_controller_last_reconciliation_timestamp {self.last_reconciliation_timestamp}

# HELP postgres_controller_drift_total Total drift detections
# TYPE postgres_controller_drift_total counter
postgres_controller_drift_total {self.drift_count}

# HELP postgres_controller_users_managed Current number of managed users
# TYPE postgres_controller_users_managed gauge
postgres_controller_users_managed {self.users_managed}

# HELP postgres_controller_roles_managed Current number of managed roles
# TYPE postgres_controller_roles_managed gauge
postgres_controller_roles_managed {self.roles_managed}

# HELP postgres_controller_errors_total Total errors encountered
# TYPE postgres_controller_errors_total counter
postgres_controller_errors_total {self.error_count}

# HELP postgres_controller_last_error_timestamp Timestamp of last error
# TYPE postgres_controller_last_error_timestamp gauge
postgres_controller_last_error_timestamp {self.last_error_timestamp}
"""


# ============================================================================
# KUBERNETES CLIENT
# ============================================================================

class KubernetesClient:
    """Handles all Kubernetes API interactions"""
    
    def __init__(self):
        try:
            config.load_incluster_config()
        except config.ConfigException:
            logger.warning("Failed to load in-cluster config, trying local kubeconfig")
            config.load_kube_config()
        
        self.v1 = client.CoreV1Api()
    
    def fetch_configmap(self, name: str, namespace: str, retry_count: int = 0) -> Optional[str]:
        """
        Fetch ConfigMap with exponential backoff retry logic
        
        Args:
            name: ConfigMap name
            namespace: Kubernetes namespace
            retry_count: Current retry attempt
            
        Returns:
            ConfigMap data as string or None if not found
        """
        try:
            cm = self.v1.read_namespaced_config_map(name, namespace)
            return cm.data.get("users.yaml", "")
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"ConfigMap {name} not found in namespace {namespace}")
                return None
            elif retry_count < Config.MAX_RETRIES:
                sleep_time = Config.RETRY_BACKOFF_BASE ** retry_count
                logger.warning(f"Error fetching ConfigMap (attempt {retry_count + 1}/{Config.MAX_RETRIES}), "
                             f"retrying in {sleep_time}s: {e}")
                time.sleep(sleep_time)
                return self.fetch_configmap(name, namespace, retry_count + 1)
            else:
                logger.error(f"Failed to fetch ConfigMap after {Config.MAX_RETRIES} retries: {e}")
                raise
    
    def get_user_password(self, username: str, namespace: str, retry_count: int = 0) -> Optional[str]:
        """
        Retrieve user password from Kubernetes Secret with retry logic
        
        Args:
            username: Username for which to fetch password
            namespace: Kubernetes namespace
            retry_count: Current retry attempt
            
        Returns:
            Decoded password string or None if not found
        """
        secret_name = f"user-{username.replace('_', '-')}-secret"
        
        try:
            secret = self.v1.read_namespaced_secret(secret_name, namespace)
            encoded_pw = secret.data.get("password")
            if not encoded_pw:
                logger.error(f"Secret {secret_name} exists but has no 'password' field")
                return None
            return base64.b64decode(encoded_pw).decode()
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Secret {secret_name} not found in namespace {namespace}")
                return None
            elif retry_count < Config.MAX_RETRIES:
                sleep_time = Config.RETRY_BACKOFF_BASE ** retry_count
                logger.warning(f"Error fetching Secret (attempt {retry_count + 1}/{Config.MAX_RETRIES}), "
                             f"retrying in {sleep_time}s: {e}")
                time.sleep(sleep_time)
                return self.get_user_password(username, namespace, retry_count + 1)
            else:
                logger.error(f"Failed to fetch Secret after {Config.MAX_RETRIES} retries: {e}")
                raise


# ============================================================================
# DATABASE CLIENT
# ============================================================================

class DatabaseClient:
    """Handles all PostgreSQL database interactions"""
    
    def __init__(self):
        self.connection_pool = None
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize connection pool with retry logic"""
        for attempt in range(Config.MAX_RETRIES):
            try:
                self.connection_pool = psycopg2.pool.SimpleConnectionPool(
                    Config.DB_POOL_MIN_CONN,
                    Config.DB_POOL_MAX_CONN,
                    host=Config.DB_HOST,
                    port=Config.DB_PORT,
                    dbname=Config.DB_NAME,
                    user=Config.DB_USER,
                    password=Config.DB_PASS,
                    connect_timeout=10
                )
                logger.info("Database connection pool initialized successfully")
                return
            except psycopg2.Error as e:
                sleep_time = Config.RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Failed to initialize connection pool (attempt {attempt + 1}/{Config.MAX_RETRIES}), "
                             f"retrying in {sleep_time}s: {e}")
                time.sleep(sleep_time)
        
        raise RuntimeError("Failed to initialize database connection pool")
    
    def get_connection(self):
        """Get a connection from the pool"""
        if not self.connection_pool:
            self._initialize_pool()
        return self.connection_pool.getconn()
    
    def return_connection(self, conn):
        """Return a connection to the pool"""
        if self.connection_pool:
            self.connection_pool.putconn(conn)
    
    def fetch_existing_users(self) -> Set[str]:
        """
        Fetch all non-system users from the database
        
        Returns:
            Set of usernames currently in the database
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                # Exclude system roles
                system_roles_list = ",".join([f"'{role}'" for role in Config.SYSTEM_ROLES])
                cur.execute(f"SELECT rolname FROM pg_roles WHERE rolname NOT IN ({system_roles_list});")
                return {r[0] for r in cur.fetchall()}
        except psycopg2.Error as e:
            logger.error(f"Error fetching existing users: {e}")
            raise
        finally:
            if conn:
                self.return_connection(conn)
    
    def fetch_existing_roles(self) -> Set[str]:
        """
        Fetch all custom roles from the database (excluding system roles and users)
        
        Returns:
            Set of role names
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                system_roles_list = ",".join([f"'{role}'" for role in Config.SYSTEM_ROLES])
                # Get roles that can't login (roles vs users)
                cur.execute(f"""
                    SELECT rolname FROM pg_roles 
                    WHERE rolname NOT IN ({system_roles_list})
                    AND NOT rolcanlogin;
                """)
                return {r[0] for r in cur.fetchall()}
        except psycopg2.Error as e:
            logger.error(f"Error fetching existing roles: {e}")
            raise
        finally:
            if conn:
                self.return_connection(conn)
    
    def fetch_user_roles(self, username: str) -> Set[str]:
        """
        Fetch all roles granted to a specific user
        
        Args:
            username: The username to query
            
        Returns:
            Set of role names granted to the user
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                # Query role membership
                cur.execute("""
                    SELECT r.rolname
                    FROM pg_roles r
                    JOIN pg_auth_members m ON r.oid = m.roleid
                    JOIN pg_roles u ON u.oid = m.member
                    WHERE u.rolname = %s;
                """, (username,))
                return {r[0] for r in cur.fetchall()}
        except psycopg2.Error as e:
            logger.error(f"Error fetching roles for user {username}: {e}")
            raise
        finally:
            if conn:
                self.return_connection(conn)
    
    def create_role(self, role_name: str, dry_run: bool = False):
        """
        Create a new PostgreSQL role
        
        Args:
            role_name: Name of the role to create
            dry_run: If True, only log the action without executing
        """
        if dry_run:
            logger.info(f"[DRY-RUN] Would create role: {role_name}")
            return
        
        conn = None
        try:
            conn = self.get_connection()
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            with conn.cursor() as cur:
                # Use sql.Identifier to prevent SQL injection
                cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN;").format(
                    sql.Identifier(role_name)
                ))
                logger.info(f"{WHITE}Created role: {role_name}{RESET}")
        except psycopg2.Error as e:
            logger.error(f"Error creating role {role_name}: {e}")
            raise
        finally:
            if conn:
                self.return_connection(conn)
    
    def drop_role(self, role_name: str, dry_run: bool = False):
        """
        Drop a PostgreSQL role
        
        Args:
            role_name: Name of the role to drop
            dry_run: If True, only log the action without executing
        """
        if dry_run:
            logger.info(f"[DRY-RUN] Would drop role: {role_name}")
            return
        
        conn = None
        try:
            conn = self.get_connection()
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            with conn.cursor() as cur:
                # Revoke from all users first
                cur.execute(sql.SQL("DROP ROLE IF EXISTS {};").format(
                    sql.Identifier(role_name)
                ))
                logger.info(f"{WHITE}Dropped role: {role_name}{RESET}")
        except psycopg2.Error as e:
            logger.error(f"Error dropping role {role_name}: {e}")
            raise
        finally:
            if conn:
                self.return_connection(conn)
    
    def create_user(self, user_spec: UserSpec, password: str, dry_run: bool = False):
        """
        Create a new PostgreSQL user with specified roles and privileges
        
        Args:
            user_spec: User specification
            password: User password (will be masked in logs)
            dry_run: If True, only log the action without executing
        """
        if dry_run:
            logger.info(f"[DRY-RUN] Would create user: {user_spec.username} with roles {user_spec.roles}")
            return
        
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                # Create user
                cur.execute(
                    sql.SQL("CREATE USER {} WITH PASSWORD %s;").format(
                        sql.Identifier(user_spec.username)
                    ),
                    (password,)
                )
                logger.info(f"{WHITE}Created user: {user_spec.username}{RESET}")
                
                # Grant database access
                cur.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {};").format(
                        sql.Identifier(user_spec.database),
                        sql.Identifier(user_spec.username)
                    )
                )
                
                # Grant roles
                for role in user_spec.roles:
                    cur.execute(
                        sql.SQL("GRANT {} TO {};").format(
                            sql.Identifier(role),
                            sql.Identifier(user_spec.username)
                        )
                    )
                    logger.info(f"  ↳ Granted role {role} to {user_spec.username}")
                
                # Grant additional privileges if specified
                if user_spec.privileges:
                    self._grant_privileges(cur, user_spec)
                
                conn.commit()
        except psycopg2.Error as e:
            logger.error(f"Error creating user {user_spec.username}: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self.return_connection(conn)
    
    def update_user_roles(self, username: str, old_roles: Set[str], new_roles: Set[str], dry_run: bool = False):
        """
        Update user role memberships
        
        Args:
            username: Username to update
            old_roles: Current roles
            new_roles: Desired roles
            dry_run: If True, only log the action without executing
        """
        to_revoke = old_roles - new_roles
        to_grant = new_roles - old_roles
        
        if not to_revoke and not to_grant:
            return
        
        if dry_run:
            if to_revoke:
                logger.info(f"[DRY-RUN] Would revoke roles from {username}: {to_revoke}")
            if to_grant:
                logger.info(f"[DRY-RUN] Would grant roles to {username}: {to_grant}")
            return
        
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                for role in to_revoke:
                    cur.execute(
                        sql.SQL("REVOKE {} FROM {};").format(
                            sql.Identifier(role),
                            sql.Identifier(username)
                        )
                    )
                    logger.info(f"  ↳ Revoked role {role} from {username}")
                
                for role in to_grant:
                    cur.execute(
                        sql.SQL("GRANT {} TO {};").format(
                            sql.Identifier(role),
                            sql.Identifier(username)
                        )
                    )
                    logger.info(f"  ↳ Granted role {role} to {username}")
                
                conn.commit()
                logger.info(f"{WHITE}Updated roles for user: {username}{RESET}")
        except psycopg2.Error as e:
            logger.error(f"Error updating roles for user {username}: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self.return_connection(conn)
    
    def drop_user(self, username: str, dry_run: bool = False):
        """
        Drop a PostgreSQL user and clean up all dependencies
        
        Args:
            username: Username to drop
            dry_run: If True, only log the action without executing
        """
        if dry_run:
            logger.info(f"[DRY-RUN] Would drop user: {username}")
            return
        
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                # Revoke all privileges
                cur.execute(
                    sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM {};").format(
                        sql.Identifier(Config.DB_NAME),
                        sql.Identifier(username)
                    )
                )
                
                # Reassign owned objects
                cur.execute(
                    sql.SQL("REASSIGN OWNED BY {} TO {};").format(
                        sql.Identifier(username),
                        sql.Identifier(Config.DB_USER)
                    )
                )
                
                # Drop owned objects
                cur.execute(
                    sql.SQL("DROP OWNED BY {};").format(
                        sql.Identifier(username)
                    )
                )
                
                # Drop the user
                cur.execute(
                    sql.SQL("DROP USER IF EXISTS {};").format(
                        sql.Identifier(username)
                    )
                )
                
                conn.commit()
                logger.info(f"{WHITE}Dropped user: {username}{RESET}")
        except psycopg2.Error as e:
            logger.error(f"Error dropping user {username}: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self.return_connection(conn)
    
    def _grant_privileges(self, cursor, user_spec: UserSpec):
        """
        Grant additional privileges to a user
        
        Args:
            cursor: Database cursor
            user_spec: User specification with privileges
        """
        if not user_spec.privileges:
            return
        
        for object_type, privileges_list in user_spec.privileges.items():
            for privilege in privileges_list:
                # This is a simplified example - expand based on your needs
                cursor.execute(
                    sql.SQL("GRANT {} ON {} TO {};").format(
                        sql.SQL(privilege),
                        sql.Identifier(object_type),
                        sql.Identifier(user_spec.username)
                    )
                )
    
    def close(self):
        """Close the connection pool"""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("Database connection pool closed")


# ============================================================================
# STATE MANAGER
# ============================================================================

class StateManager:
    """Manages persistent state for drift detection"""
    
    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
    
    def load_state(self) -> Dict[str, UserSpec]:
        """
        Load last applied state from disk
        
        Returns:
            Dictionary mapping username to UserSpec
        """
        if not self.state_file.exists():
            logger.info("No previous state file found, starting fresh")
            return {}
        
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
                return {
                    username: UserSpec(**spec)
                    for username, spec in data.items()
                }
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading state file: {e}, starting fresh")
            return {}
    
    def save_state(self, users: Dict[str, UserSpec]):
        """
        Save current state to disk
        
        Args:
            users: Dictionary mapping username to UserSpec
        """
        try:
            data = {
                username: asdict(spec)
                for username, spec in users.items()
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"State saved to {self.state_file}")
        except IOError as e:
            logger.error(f"Error saving state file: {e}")


# ============================================================================
# RECONCILIATION CONTROLLER
# ============================================================================

class PostgresUserController:
    """
    Main controller for reconciling PostgreSQL users and roles
    """
    
    def __init__(self):
        self.k8s_client = KubernetesClient()
        self.db_client = DatabaseClient()
        self.state_manager = StateManager(Config.STATE_FILE)
        self.metrics = Metrics()
        logger.info("PostgreSQL User Controller initialized")
    
    def parse_desired_users(self, yaml_content: str) -> Dict[str, UserSpec]:
        """
        Parse users.yaml content into UserSpec objects
        
        Args:
            yaml_content: YAML string from ConfigMap
            
        Returns:
            Dictionary mapping username to UserSpec
        """
        if not yaml_content:
            logger.warning("Empty ConfigMap content, no users to manage")
            return {}
        
        try:
            parsed = yaml.safe_load(yaml_content)
            users = {}
            for user_data in parsed.get("users", []):
                spec = UserSpec(
                    username=user_data["username"],
                    database=user_data.get("database", Config.DB_NAME),
                    roles=user_data.get("roles", []),
                    privileges=user_data.get("privileges")
                )
                users[spec.username] = spec
            return users
        except (yaml.YAMLError, KeyError) as e:
            logger.error(f"Error parsing users.yaml: {e}")
            return {}
    
    def detect_drift(self, desired: Dict[str, UserSpec], actual_users: Set[str]) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Detect drift between desired and actual state
        
        Args:
            desired: Desired user specifications
            actual_users: Actual users in database
            
        Returns:
            Tuple of (users_to_create, users_to_delete, users_to_update)
        """
        desired_usernames = set(desired.keys())
        
        users_to_create = desired_usernames - actual_users
        users_to_delete = actual_users - desired_usernames
        users_to_update = desired_usernames & actual_users
        
        return users_to_create, users_to_delete, users_to_update
    
    def reconcile_roles(self, desired_users: Dict[str, UserSpec], stats: ReconciliationStats, dry_run: bool = False):
        """
        Ensure all required roles exist in the database
        
        Args:
            desired_users: Desired user specifications
            stats: Statistics object to update
            dry_run: If True, only simulate actions
        """
        # Collect all roles mentioned in desired state
        all_desired_roles = set()
        for user_spec in desired_users.values():
            all_desired_roles.update(user_spec.roles)
        
        # Fetch existing roles from database
        existing_roles = self.db_client.fetch_existing_roles()
        
        # Create missing roles
        roles_to_create = all_desired_roles - existing_roles
        for role in roles_to_create:
            try:
                self.db_client.create_role(role, dry_run=dry_run)
                stats.roles_created += 1
            except Exception as e:
                logger.error(f"Failed to create role {role}: {e}")
                stats.errors += 1
        
        # Optionally clean up unused roles (be careful with this!)
        # Commented out by default to prevent accidental deletions
        # roles_to_delete = existing_roles - all_desired_roles
        # for role in roles_to_delete:
        #     try:
        #         self.db_client.drop_role(role, dry_run=dry_run)
        #         stats.roles_deleted += 1
        #     except Exception as e:
        #         logger.error(f"Failed to drop role {role}: {e}")
        #         stats.errors += 1
    
    def reconcile_users(self, stats: ReconciliationStats, dry_run: bool = False):
        """
        Main reconciliation logic
        
        Args:
            stats: Statistics object to update
            dry_run: If True, only simulate actions
        """
        # Fetch desired state from ConfigMap
        yaml_content = self.k8s_client.fetch_configmap(
            Config.CONFIGMAP_NAME,
            Config.NAMESPACE
        )
        
        if yaml_content is None:
            logger.error("Failed to fetch ConfigMap, skipping reconciliation")
            stats.errors += 1
            return
        
        desired_users = self.parse_desired_users(yaml_content)
        
        # Load previous state
        previous_state = self.state_manager.load_state()
        
        # Fetch actual database state
        try:
            actual_users = self.db_client.fetch_existing_users()
        except Exception as e:
            logger.error(f"Failed to fetch existing users: {e}")
            stats.errors += 1
            return
        
        # Reconcile roles first
        self.reconcile_roles(desired_users, stats, dry_run=dry_run)
        
        # Detect drift
        users_to_create, users_to_delete, users_to_update = self.detect_drift(
            desired_users, actual_users
        )
        
        drift_count = len(users_to_create) + len(users_to_delete)
        if drift_count > 0:
            logger.info(f"{YELLOW}Drift detected: {drift_count} changes needed{RESET}")
            stats.drift_detected = drift_count
        
        # Handle deletions
        for username in users_to_delete:
            # Only delete if it was in our previous state (we manage it)
            if username in previous_state:
                try:
                    self.db_client.drop_user(username, dry_run=dry_run)
                    stats.users_deleted += 1
                except Exception as e:
                    logger.error(f"Failed to delete user {username}: {e}")
                    stats.errors += 1
        
        # Handle creations
        for username in users_to_create:
            user_spec = desired_users[username]
            try:
                password = self.k8s_client.get_user_password(
                    username,
                    Config.NAMESPACE
                )
                if not password:
                    logger.error(f"No password found for user {username}, skipping creation")
                    stats.errors += 1
                    continue
                
                self.db_client.create_user(user_spec, password, dry_run=dry_run)
                stats.users_created += 1
            except Exception as e:
                logger.error(f"Failed to create user {username}: {e}")
                stats.errors += 1
        
        # Handle updates
        for username in users_to_update:
            user_spec = desired_users[username]
            prev_spec = previous_state.get(username)
            
            # Check if roles changed
            if prev_spec and set(prev_spec.roles) != set(user_spec.roles):
                try:
                    actual_roles = self.db_client.fetch_user_roles(username)
                    desired_roles = set(user_spec.roles)
                    
                    if actual_roles != desired_roles:
                        self.db_client.update_user_roles(
                            username,
                            actual_roles,
                            desired_roles,
                            dry_run=dry_run
                        )
                        stats.users_updated += 1
                except Exception as e:
                    logger.error(f"Failed to update user {username}: {e}")
                    stats.errors += 1
        
        # Save new state
        if not dry_run:
            self.state_manager.save_state(desired_users)
        
        # Update metrics
        self.metrics.users_managed = len(desired_users)
        self.metrics.roles_managed = len(self.db_client.fetch_existing_roles())
    
    def run_reconciliation_loop(self):
        """
        Main control loop that runs continuously
        """
        logger.info(f"{GREEN}Controller started (DRY_RUN={Config.DRY_RUN}){RESET}")
        logger.info(f"Sync interval: {Config.SYNC_INTERVAL}s")
        
        while True:
            stats = ReconciliationStats(start_time=datetime.now())
            
            try:
                logger.info("=" * 60)
                logger.info("Starting reconciliation cycle")
                
                self.reconcile_users(stats, dry_run=Config.DRY_RUN)
                
                stats.end_time = datetime.now()
                self.metrics.record_reconciliation(stats)
                
                # Print summary
                logger.info("=" * 60)
                logger.info(f"{WHITE}Reconciliation Summary:{RESET}")
                logger.info(f"  • Users created: {stats.users_created}")
                logger.info(f"  • Users updated: {stats.users_updated}")
                logger.info(f"  • Users deleted: {stats.users_deleted}")
                logger.info(f"  • Roles created: {stats.roles_created}")
                logger.info(f"  • Roles deleted: {stats.roles_deleted}")
                logger.info(f"  • Drift detected: {stats.drift_detected}")
                logger.info(f"  • Errors: {stats.errors}")
                logger.info(f"  • Duration: {stats.duration_seconds():.2f}s")
                logger.info("=" * 60)
                
            except Exception as e:
                logger.error(f"Unexpected error in reconciliation loop: {e}", exc_info=True)
                stats.errors += 1
                stats.end_time = datetime.now()
                self.metrics.record_reconciliation(stats)
            
            # Sleep until next cycle
            logger.info(f"{BLUE}Sleeping for {Config.SYNC_INTERVAL}s...{RESET}")
            time.sleep(Config.SYNC_INTERVAL)
    
    def cleanup(self):
        """Cleanup resources"""
        logger.info("Shutting down controller...")
        self.db_client.close()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    controller = None
    try:
        controller = PostgresUserController()
        controller.run_reconciliation_loop()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down gracefully...")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if controller:
            controller.cleanup()


if __name__ == "__main__":
    main()
