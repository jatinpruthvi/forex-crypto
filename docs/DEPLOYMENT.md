# AMATS Deployment & VPS Setup Guide

## 1. Oracle Cloud Always Free VM Setup

1. **Sign Up:** Go to `cloud.oracle.com` and register for the Always Free Tier.
2. **Provision Instance:**
   - Shape: `VM.Standard.A1.Flex` (Ampere ARM)
   - Specs: 2 OCPUs, 12 GB RAM
   - Image: Ubuntu 22.04 LTS
   - Region: Tokyo or Singapore (lowest latency to Bybit & MT5 liquidity hubs)
3. **Network Security List:**
   - Inbound Port `22` (SSH)
   - Inbound Port `8000` (Brain API)
   - Inbound Port `8080` (FreqTrade UI API)
4. **SSH Access:**
   ```bash
   chmod 400 your-oracle-key.pem
   ssh -i your-oracle-key.pem ubuntu@<your-vps-ip>
   ```

---

## 2. One-Click Bootstrap

Run the provided setup script on the VPS:
```bash
git clone -b arena/b657ea09-forex-crypto https://github.com/jatinpruthvi/forex-crypto.git trading
cd trading
./scripts/setup_vps.sh
```

---

## 3. Systemd Service Deployment

Create the Brain API service `/etc/systemd/system/brain-api.service`:
```ini
[Unit]
Description=AMATS Trading Brain API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/trading
ExecStart=/home/ubuntu/trading/venv/bin/uvicorn services.brain_api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
Environment=PYTHONPATH=/home/ubuntu/trading

[Install]
WantedBy=multi-user.target
```

Enable and start services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable brain-api.service
sudo systemctl start brain-api.service
```

---

## 4. Cron Schedules

Configure hourly data collection and automated backups:
```bash
crontab -e
```
Add:
```cron
# Hourly free signal collector
0 * * * * cd /home/ubuntu/trading && /home/ubuntu/trading/venv/bin/python services/data_collector/collector.py >> logs/collector.log 2>&1

# Daily backup at 03:00 UTC
0 3 * * * /home/ubuntu/trading/scripts/backup.sh >> logs/backup.log 2>&1

# Weekly database pruning & log rotation (Sundays at 04:00 UTC)
0 4 * * 0 cd /home/ubuntu/trading && /home/ubuntu/trading/venv/bin/python scripts/prune_maintenance.py >> logs/maintenance.log 2>&1
```

---

## 5. MetaTrader 5 Setup for Prop Firms

1. Copy `services/mql5/Include/BrainClient.mqh` and `RiskManager.mqh` to MT5 `MQL5/Include/`.
2. Copy `services/mql5/MasterRiskEA.mq5` and `PythonBrainEA.mq5` to MT5 `MQL5/Experts/`.
3. Open MT5: **Tools > Options > Expert Advisors**:
   - Check `Allow Algo Trading`
   - Check `Allow WebRequest for listed URL`
   - Add: `http://<your-vps-ip>:8000`
4. Attach `MasterRiskEA` to EURUSD M1 chart.
5. Attach `PythonBrainEA` to EURUSD H1 chart with `InpBrainApiUrl = http://<your-vps-ip>:8000`.
