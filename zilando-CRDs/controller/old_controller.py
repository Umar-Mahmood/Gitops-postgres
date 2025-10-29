# this is a simplified controller that syncs PostgreSQL users based on a ConfigMap in Kubernetes.
# It creates, updates, and deletes users in the PostgreSQL database according to the desired state defined in the ConfigMap.
# this is just a proof of concept and lacks advanced features like event-driven updates or error handling for production use.


import os
import time
import yaml
import psycopg2
from kubernetes import client, config
from datetime import datetime

# Load Kubernetes config
config.load_incluster_config()
v1 = client.CoreV1Api()

import base64

def get_user_password(username):
    # Sanitize name (replace _ with - to match secret names)
    secret_name = f"user-{username.replace('_', '-')}-secret"
    secret = v1.read_namespaced_secret(secret_name, NAMESPACE)
    encoded_pw = secret.data["password"]
    return base64.b64decode(encoded_pw).decode()

NAMESPACE = "postgres"
CONFIGMAP_NAME = "postgres-users-config"

DB_HOST = os.getenv("DB_HOST", "acid-minimal-cluster.default.svc.cluster.local")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

last_seen_users = {}

def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}", flush=True)

def connect_db():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )

def user_key(user):
    return user["username"]

def fetch_desired_users():
    cm = v1.read_namespaced_config_map(CONFIGMAP_NAME, NAMESPACE)
    raw_yaml = cm.data.get("users.yaml", "")
    parsed = yaml.safe_load(raw_yaml)
    return {user_key(u): u for u in parsed.get("users", [])}

def fetch_existing_users(cursor):
    cursor.execute("SELECT rolname FROM pg_roles WHERE rolname NOT IN ('postgres');")
    return {r[0] for r in cursor.fetchall()}

def create_user(cursor, user):
    username = user["username"]
    password = get_user_password(user["username"])
    roles = user.get("roles", [])
    database = user["database"]

    cursor.execute(f"CREATE USER {username} WITH PASSWORD %s;", (password,))
    cursor.execute(f"GRANT CONNECT ON DATABASE {database} TO {username};")
    for role in roles:
        cursor.execute(f"GRANT {role} TO {username};")

def update_roles(cursor, username, old_roles, new_roles):
    to_revoke = set(old_roles) - set(new_roles)
    to_grant = set(new_roles) - set(old_roles)
    for role in to_revoke:
        cursor.execute(f"REVOKE {role} FROM {username};")
    for role in to_grant:
        cursor.execute(f"GRANT {role} TO {username};")

def drop_user(cursor, username):
    cursor.execute(f"REVOKE ALL PRIVILEGES ON DATABASE {DB_NAME} FROM {username};")
    cursor.execute(f"REASSIGN OWNED BY {username} TO {DB_USER};")
    cursor.execute(f"DROP OWNED BY {username};")
    cursor.execute(f"DROP USER IF EXISTS {username};")
    cursor.execute(f"DROP USER IF EXISTS {username};")

def sync_users():
    global last_seen_users

    try:
        desired_users = fetch_desired_users()
        with connect_db() as conn:
            with conn.cursor() as cur:
                current_users = fetch_existing_users(cur)

                # Handle deletions
                for username in last_seen_users:
                    if username not in desired_users and username in current_users:
                        print(f"🗑️ Deleting user: {username}")
                        try:
                            drop_user(cur, username)
                            log(f"Deleted user: {username}")
                        except Exception as e:
                            log(f"Error deleting user {username}: {e}")

                # Handle additions and updates
                for username, user in desired_users.items():
                    if username not in current_users:
                        create_user(cur, user)
                        log(f" Created user: {username}")
                    else:
                        prev = last_seen_users.get(username, {})
                        if prev.get("roles") != user.get("roles"):
                            update_roles(cur, username, prev.get("roles", []), user.get("roles", []))
                            log(f"Updated roles for: {username}")

            conn.commit()

        last_seen_users = desired_users
        log("Sync complete.")

    except Exception as e:
        log(f"Sync error: {e}")

if __name__ == "__main__":
    log(f"Controller started...")
    while True:
        log("Syncing users...")
        sync_users()
        time.sleep(30)
