import yaml
import subprocess
import tempfile
import os
import base64

CONFIGMAP_FILE = "users-configmap.yaml"
CERT_FILE = "pub-cert.pem"
NAMESPACE = "postgres"
OUTPUT_FILE = "sealed-users.yaml"

def extract_users(configmap_path):
    with open(configmap_path, "r") as f:
        config = yaml.safe_load(f)
    users_yaml_str = config["data"]["users.yaml"]
    return yaml.safe_load(users_yaml_str)["users"]

def make_secret_yaml(user):
    encoded_pw = base64.b64encode(user["password"].encode()).decode()
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": f"user-{user['username'].replace('_', '-')}-secret",
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
    users = extract_users(CONFIGMAP_FILE)
    sealed_secrets = [seal(make_secret_yaml(user)) for user in users]

    with open(OUTPUT_FILE, "w") as f:
        yaml.dump_all(sealed_secrets, f)

    print(f"✅ Sealed secrets written to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
