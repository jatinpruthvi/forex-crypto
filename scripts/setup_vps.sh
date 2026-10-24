#!/usr/bin/env bash
# One-click Ubuntu VPS Provisioning Script for AMATS (Oracle Cloud / EC2)
set -e

echo "=== AMATS VPS Setup Starting ==="

sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git curl ufw sqlite3 build-essential

# Firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 8000/tcp
sudo ufw allow 8080/tcp
sudo ufw --force enable

# Virtual environment setup
mkdir -p /home/ubuntu/trading
cd /home/ubuntu/trading
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Directory structure
mkdir -p data logs models backups

echo "=== AMATS VPS Setup Completed Successfully ==="
