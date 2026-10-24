#!/usr/bin/env bash
# AMATS Automated Deployment Script
set -e

echo "Deploying AMATS updates..."
git pull origin arena/b657ea09-forex-crypto

source venv/bin/activate
pip install -r requirements.txt

# Restart Brain API
sudo systemctl restart brain-api.service || echo "brain-api.service not registered via systemd"
echo "Deployment completed."
