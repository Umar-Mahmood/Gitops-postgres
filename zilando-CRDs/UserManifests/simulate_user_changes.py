import os
import time
import yaml
import subprocess
from datetime import datetime

CONFIGMAP_PATH = "users.yaml"
NAMESPACE = "postgres"
CONFIGMAP_NAME = "postgres-users-config"

def generate_users_block(num_users):
    users = []
    for i in range(num_users):
        users.append({
            "username": f"user_{i}",
            "password": f"pass{i}",
            "roles": ["read"],
            "database": "postgres"
        })
    users_block = {
        "users": users,
        "timestamp": datetime.now().isoformat()
    }
    return yaml.dump(users_block)

def write_configmap(num_users):
    with open(CONFIGMAP_PATH, "r") as f:
        configmap = yaml.safe_load(f)
    configmap["data"]["users.yaml"] = generate_users_block(num_users)
    with open(CONFIGMAP_PATH, "w") as f:
        yaml.dump(configmap, f)

def commit_and_push():
    subprocess.run(["git", "add", "users.yaml"])
    subprocess.run(["git", "commit", "-m", f"auto update @ {datetime.now().isoformat()}"])
    subprocess.run(["git", "push"])

def sync_argocd_app():
    subprocess.run(["argocd", "app", "sync", "postgres-users"])

def check_configmap(num_expected_users):
    try:
        result = subprocess.run(
            ["kubectl", "get", "configmap", CONFIGMAP_NAME, "-n", NAMESPACE, "-o", "yaml"],
            capture_output=True,
            text=True,
        )
        raw_yaml = yaml.safe_load(result.stdout)
        user_yaml_str = raw_yaml["data"]["users.yaml"]
        users = yaml.safe_load(user_yaml_str).get("users", [])
        return len(users) == num_expected_users
    except Exception as e:
        print(f"❌ Error checking configmap: {e}")
        return False

def run_test():
    total = 0
    passed = 0
    for delay in [15, 10, 5, 2, 1]:
        print(f"\n⏱️ Phase: 1 update every {delay}s")
        for i in range(5):
            user_count = i + 1
            write_configmap(user_count)
            commit_and_push()
            sync_argocd_app()
            print(f"🚀 Pushed and synced {user_count} users")
            time.sleep(5)  # allow time for ArgoCD and controller

            if check_configmap(user_count):
                print(f"✅ Verified {user_count} users in ConfigMap")
                passed += 1
            else:
                print(f"❌ Verification failed for {user_count} users")
            total += 1
            time.sleep(delay)

    print("\n📊 Test Summary:")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {total - passed}")
    print(f"📦 Total: {total}")

if __name__ == "__main__":
    run_test()
