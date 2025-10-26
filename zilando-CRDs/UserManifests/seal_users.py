import yaml
import subprocess
import tempfile
import os
import base64
from datetime import datetime

EDIT_FILE = "edit-users.yaml"
OUTPUT_CONFIGMAP = "users.yaml"
CERT_FILE = "pub-cert.pem"
NAMESPACE = "postgres"
OUTPUT_SEALED = "sealed-users.yaml"

def load_users():
    with open(EDIT_FILE, "r") as f:
        outer_yaml = yaml.safe_load(f)
    users_yaml_str = outer_yaml["data"]["users.yaml"]
    parsed_users = yaml.safe_load(users_yaml_str.strip())
    return parsed_users["users"]

def make_secret_yaml(user):
    encoded_pw = base64.b64encode(user["password"].encode()).decode()
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": f"user-{user['username'].replace('_','-')}-secret",
            "namespace": NAMESPACE
        },
        "type": "Opaque",
        "data": {
            "password": encoded_pw
        }
    }

def seal(secret_yaml):
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        yaml.dump(secret_yaml, tmp)
        tmp_path = tmp.name

    result = subprocess.run([
        "kubeseal",
        "--format", "yaml",
        "--cert", CERT_FILE,
        "-o", "yaml",
        "-n", NAMESPACE,
        "-f", tmp_path
    ], capture_output=True)

    os.remove(tmp_path)

    if result.returncode != 0:
        print("❌ Sealing failed:", result.stderr.decode())
        exit(1)

    return yaml.safe_load(result.stdout.decode())

def main():
    users = load_users()
    sealed_secrets = [seal(make_secret_yaml(user)) for user in users]

    # Write sealed secrets
    with open(OUTPUT_SEALED, "w") as f:
        yaml.dump_all(sealed_secrets, f)
    print(f"✅ Sealed secrets written to: {OUTPUT_SEALED}")

    # Create cleaned configmap
    cleaned_users = []
    for user in users:
        cleaned = {k: v for k, v in user.items() if k != "password"}
        cleaned_users.append(cleaned)

    users_configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "postgres-users-config",
            "namespace": NAMESPACE
        },
        "data": {
            "users.yaml": yaml.dump({
                "timestamp": datetime.utcnow().isoformat(),
                "users": cleaned_users
            })
        }
    }

    with open(OUTPUT_CONFIGMAP, "w") as f:
        yaml.dump(users_configmap, f)

    print(f"🧹 Passwords removed from output: {OUTPUT_CONFIGMAP}")

if __name__ == "__main__":
    main()
