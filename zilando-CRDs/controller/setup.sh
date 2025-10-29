#!/bin/bash
# PostgreSQL User Controller - Setup and Deployment Script

set -e

NAMESPACE="${NAMESPACE:-postgres}"
CONTROLLER_IMAGE="${CONTROLLER_IMAGE:-postgres-user-controller:latest}"
CONTEXT="${CONTEXT:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install kubectl."
        exit 1
    fi
    
    if ! command -v python3 &> /dev/null; then
        log_error "python3 not found. Please install Python 3.8+."
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        log_warning "docker not found. Docker is required to build images."
    fi
    
    log_success "Prerequisites check passed"
}

# Create namespace
create_namespace() {
    log_info "Creating namespace: $NAMESPACE"
    
    if kubectl get namespace "$NAMESPACE" &> /dev/null; then
        log_warning "Namespace $NAMESPACE already exists"
    else
        kubectl create namespace "$NAMESPACE"
        log_success "Namespace created: $NAMESPACE"
    fi
}

# Install Python dependencies locally
install_dependencies() {
    log_info "Installing Python dependencies..."
    
    if [ -f "requirements.txt" ]; then
        python3 -m pip install --user -r requirements.txt
        log_success "Dependencies installed"
    else
        log_error "requirements.txt not found"
        exit 1
    fi
}

# Build Docker image
build_image() {
    log_info "Building Docker image: $CONTROLLER_IMAGE"
    
    if [ -f "Dockerfile" ]; then
        docker build -t "$CONTROLLER_IMAGE" .
        log_success "Docker image built: $CONTROLLER_IMAGE"
    else
        log_error "Dockerfile not found"
        exit 1
    fi
}

# Load image to kind (if using kind)
load_image_to_kind() {
    if command -v kind &> /dev/null; then
        log_info "Checking if running on kind cluster..."
        
        current_context=$(kubectl config current-context)
        if [[ "$current_context" == *"kind"* ]]; then
            log_info "Loading image to kind cluster..."
            kind load docker-image "$CONTROLLER_IMAGE"
            log_success "Image loaded to kind cluster"
        fi
    fi
}

# Create example ConfigMap and Secrets
create_example_config() {
    log_info "Creating example ConfigMap and Secrets..."
    
    if [ -f "example-config.yaml" ]; then
        kubectl apply -f example-config.yaml -n "$NAMESPACE"
        log_success "Example configuration created"
    else
        log_warning "example-config.yaml not found, skipping"
    fi
}

# Create PostgreSQL admin credentials secret
create_admin_secret() {
    log_info "Creating PostgreSQL admin credentials secret..."
    
    read -p "Enter PostgreSQL admin username (default: postgres): " DB_USER
    DB_USER=${DB_USER:-postgres}
    
    read -sp "Enter PostgreSQL admin password: " DB_PASS
    echo
    
    if [ -z "$DB_PASS" ]; then
        log_error "Password cannot be empty"
        exit 1
    fi
    
    kubectl create secret generic postgres-admin-credentials \
        --from-literal=username="$DB_USER" \
        --from-literal=password="$DB_PASS" \
        -n "$NAMESPACE" \
        --dry-run=client -o yaml | kubectl apply -f -
    
    log_success "Admin credentials secret created"
}

# Deploy RBAC resources
deploy_rbac() {
    log_info "Deploying RBAC resources..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: postgres-user-controller
  namespace: $NAMESPACE
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: postgres-user-controller
  namespace: $NAMESPACE
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["create", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: postgres-user-controller
  namespace: $NAMESPACE
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: postgres-user-controller
subjects:
  - kind: ServiceAccount
    name: postgres-user-controller
    namespace: $NAMESPACE
EOF
    
    log_success "RBAC resources deployed"
}

# Deploy controller
deploy_controller() {
    log_info "Deploying controller..."
    
    read -p "Enter PostgreSQL host (e.g., acid-minimal-cluster.postgres.svc): " DB_HOST
    DB_HOST=${DB_HOST:-acid-minimal-cluster.postgres.svc.cluster.local}
    
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres-user-controller
  namespace: $NAMESPACE
  labels:
    app: postgres-user-controller
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: postgres-user-controller
  template:
    metadata:
      labels:
        app: postgres-user-controller
    spec:
      serviceAccountName: postgres-user-controller
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
      - name: controller
        image: $CONTROLLER_IMAGE
        imagePullPolicy: IfNotPresent
        env:
        - name: NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: DB_HOST
          value: "$DB_HOST"
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
        - name: SYNC_INTERVAL
          value: "30"
        - name: DRY_RUN
          value: "false"
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "500m"
        volumeMounts:
        - name: state
          mountPath: /var/lib/controller
      volumes:
      - name: state
        emptyDir: {}
EOF
    
    log_success "Controller deployed"
}

# Check deployment status
check_deployment() {
    log_info "Checking deployment status..."
    
    kubectl rollout status deployment/postgres-user-controller -n "$NAMESPACE" --timeout=60s
    
    log_success "Deployment is ready"
    
    log_info "Controller logs:"
    kubectl logs -n "$NAMESPACE" -l app=postgres-user-controller --tail=20
}

# Run tests
run_tests() {
    log_info "Running tests..."
    
    if [ -f "test_controller.py" ]; then
        python3 test_controller.py
    else
        log_warning "test_controller.py not found, skipping tests"
    fi
}

# Dry run deployment
dry_run() {
    log_info "Running in DRY-RUN mode..."
    
    export DRY_RUN=true
    python3 controller.py &
    CONTROLLER_PID=$!
    
    log_info "Controller running with PID: $CONTROLLER_PID"
    log_info "Press Ctrl+C to stop"
    
    wait $CONTROLLER_PID
}

# Show usage
usage() {
    cat <<EOF
PostgreSQL User Controller - Setup Script

Usage: $0 [command]

Commands:
    check           Check prerequisites
    install-deps    Install Python dependencies
    build           Build Docker image
    test            Run tests
    dry-run         Run controller locally in dry-run mode
    deploy-all      Deploy everything (RBAC + Controller)
    deploy-rbac     Deploy only RBAC resources
    deploy-ctrl     Deploy only controller
    status          Check deployment status
    logs            Show controller logs
    delete          Delete deployment
    help            Show this help message

Examples:
    # Full deployment
    $0 deploy-all

    # Local testing
    $0 install-deps
    $0 test
    $0 dry-run

    # Build and deploy custom image
    $0 build
    CONTROLLER_IMAGE=myregistry/controller:v1 $0 deploy-ctrl

Environment Variables:
    NAMESPACE           Kubernetes namespace (default: postgres)
    CONTROLLER_IMAGE    Docker image (default: postgres-user-controller:latest)
    CONTEXT             Kubernetes context to use

EOF
}

# Main script
main() {
    case "${1:-help}" in
        check)
            check_prerequisites
            ;;
        install-deps)
            install_dependencies
            ;;
        build)
            check_prerequisites
            build_image
            load_image_to_kind
            ;;
        test)
            install_dependencies
            run_tests
            ;;
        dry-run)
            install_dependencies
            dry_run
            ;;
        deploy-all)
            check_prerequisites
            create_namespace
            create_admin_secret
            deploy_rbac
            create_example_config
            deploy_controller
            check_deployment
            ;;
        deploy-rbac)
            check_prerequisites
            create_namespace
            deploy_rbac
            ;;
        deploy-ctrl)
            check_prerequisites
            deploy_controller
            check_deployment
            ;;
        status)
            check_deployment
            ;;
        logs)
            kubectl logs -n "$NAMESPACE" -l app=postgres-user-controller --tail=100 -f
            ;;
        delete)
            log_warning "Deleting controller deployment..."
            kubectl delete deployment postgres-user-controller -n "$NAMESPACE"
            log_success "Deployment deleted"
            ;;
        help|*)
            usage
            ;;
    esac
}

main "$@"
