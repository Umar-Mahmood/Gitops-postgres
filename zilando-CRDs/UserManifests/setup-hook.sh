#!/bin/bash

# Setup script for the pre-commit hook
# Run this after cloning the repository to enable automatic secret sealing

HOOK_SOURCE="zilando-CRDs/UserManifests/pre-commit-hook.sh"
HOOK_DEST=".git/hooks/pre-commit"

echo "🔧 Setting up pre-commit hook for automatic secret sealing..."

# Check if .git directory exists
if [ ! -d ".git" ]; then
    echo "❌ Error: .git directory not found. Make sure you're in the repository root."
    exit 1
fi

# Copy the hook
if [ -f "${HOOK_SOURCE}" ]; then
    cp "${HOOK_SOURCE}" "${HOOK_DEST}"
    chmod +x "${HOOK_DEST}"
    echo "✅ Pre-commit hook installed successfully!"
else
    echo "❌ Error: ${HOOK_SOURCE} not found!"
    echo "Creating hook directly in .git/hooks/pre-commit..."
    
    # Create the hook directly if source doesn't exist
    cat > "${HOOK_DEST}" << 'HOOKEOF'
#!/bin/bash

# Pre-commit hook to seal user secrets
# This hook runs seal_users.py when edit-users.yaml is modified

EDIT_FILE="zilando-CRDs/UserManifests/edit-users.yaml"
SEAL_SCRIPT="zilando-CRDs/UserManifests/seal_users.py"
USERS_YAML="zilando-CRDs/UserManifests/users.yaml"
SEALED_YAML_IN_MANIFEST="zilando-CRDs/UserManifests/sealed-users.yaml"
SEALED_YAML_ROOT="zilando-CRDs/sealed-users.yaml"
CERT_FILE="zilando-CRDs/pub-cert.pem"

# Check if edit-users.yaml is staged
if git diff --cached --name-only | grep -q "^${EDIT_FILE}$"; then
    echo "🔍 Detected changes to ${EDIT_FILE}"
    
    # Check if required files exist
    if [ ! -f "${SEAL_SCRIPT}" ]; then
        echo "❌ Error: ${SEAL_SCRIPT} not found!"
        exit 1
    fi
    
    if [ ! -f "${CERT_FILE}" ]; then
        echo "❌ Error: ${CERT_FILE} not found! Cannot seal secrets."
        exit 1
    fi
    
    # Change to the UserManifests directory to run the script
    cd zilando-CRDs/UserManifests || exit 1
    
    echo "🔐 Running seal_users.py to generate sealed secrets..."
    
    # Run the seal script
    if python3 seal_users.py; then
        cd - > /dev/null || exit 1
        
        # Stage the generated files
        echo "📝 Staging generated files..."
        git add "${USERS_YAML}"
        
        # Check which sealed-users.yaml was created and stage it
        if [ -f "${SEALED_YAML_IN_MANIFEST}" ]; then
            git add "${SEALED_YAML_IN_MANIFEST}"
        fi
        if [ -f "${SEALED_YAML_ROOT}" ]; then
            git add "${SEALED_YAML_ROOT}"
        fi
        
        # Unstage edit-users.yaml
        echo "🔄 Unstaging ${EDIT_FILE}..."
        git reset HEAD "${EDIT_FILE}"
        
        echo "✅ Pre-commit hook completed successfully!"
        echo "📌 Note: ${EDIT_FILE} has been unstaged but your local changes are preserved."
        echo "📦 Committing: ${USERS_YAML} and sealed-users.yaml"
    else
        cd - > /dev/null || exit 1
        echo "❌ Failed to seal secrets. Commit aborted."
        exit 1
    fi
fi

exit 0
HOOKEOF
    
    chmod +x "${HOOK_DEST}"
    echo "✅ Pre-commit hook created and installed!"
fi

echo ""
echo "📋 Setup complete! The hook will now:"
echo "   1. Detect changes to edit-users.yaml"
echo "   2. Run seal_users.py automatically"
echo "   3. Stage users.yaml and sealed-users.yaml"
echo "   4. Unstage edit-users.yaml (keeping local changes)"
echo ""
echo "💡 Test it by editing and committing edit-users.yaml!"
