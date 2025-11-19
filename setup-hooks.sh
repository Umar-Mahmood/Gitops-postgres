#!/bin/bash

# Script to install Git hooks for this repository
# Run this after cloning the repository: ./setup-hooks.sh

HOOKS_DIR=".git/hooks"
SOURCE_HOOKS_DIR="hooks"

echo "Setting up Git hooks..."

# Check if .git directory exists
if [ ! -d ".git" ]; then
    echo "Error: .git directory not found. Are you in the repository root?"
    exit 1
fi

# Check if hooks source directory exists
if [ ! -d "${SOURCE_HOOKS_DIR}" ]; then
    echo "Error: ${SOURCE_HOOKS_DIR} directory not found."
    exit 1
fi

# Copy hooks
for hook in "${SOURCE_HOOKS_DIR}"/*; do
    if [ -f "$hook" ]; then
        hook_name=$(basename "$hook")
        echo "Installing ${hook_name} hook..."
        cp "$hook" "${HOOKS_DIR}/${hook_name}"
        chmod +x "${HOOKS_DIR}/${hook_name}"
        echo "✓ ${hook_name} hook installed"
    fi
done

echo ""
echo "Git hooks have been installed successfully!"
echo "The pre-commit hook will automatically seal user secrets when edit-users.yaml is modified."
