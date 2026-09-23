# Pillar 1 Production Deployment Guide (AWS EC2 / Ubuntu Linux)

This guide provides end-to-end instructions for deploying the **Pillar 1 Company Discovery & Lead Generation OSINT Pipeline** on an **AWS EC2 Ubuntu Linux instance**.

---

## 1. System Architecture & Requirements

### Infrastructure Architecture
```
Internet
   │
   ▼
AWS Security Group (Ports 22, 80, 443)
   │
   ▼
Nginx (Reverse Proxy & TLS Termination :443)
   │
   ▼ (proxy_pass http://127.0.0.1:8000)
Uvicorn ASGI Server (FastAPI :8000)
   │
   ├── BackgroundTasks Scraper
   │     ├── Discovery & Direct Lane (Google, Brave, LinkedIn)
   │     ├── BrowserPool (Playwright Headless Chromium)
   │     ├── NetworkClient (Proxy Manager & Retry Engine)
   │     └── Extraction & Lead Consolidation
   │
   ├── SQLite Database (`leads.db`)
   └── File Storage (`output/`, `logs/`, `cookies/`, `data/`)
```

### Recommended AWS EC2 Instance Specs
- **AMI**: Ubuntu 22.04 LTS or Ubuntu 24.04 LTS (64-bit x86_64)
- **Instance Type**:
  - Minimum: `t3.medium` (2 vCPU, 4 GB RAM)
  - Recommended for heavy scraping: `c6i.large` or `t3.large` (2 vCPU, 8 GB RAM)
  - *Note*: Chromium instances require ~300–600 MB RAM each; 4 GB RAM is the minimum required to comfortably run 2-3 browser instances plus FastAPI.
- **Storage**: 30 GB gp3 EBS Volume

### AWS Security Group Configuration
| Type | Port Range | Protocol | Source | Purpose |
|------|------------|----------|--------|---------|
| SSH | 22 | TCP | `Your-Admin-IP/32` | Secure administrator access |
| HTTP | 80 | TCP | `0.0.0.0/0` | Let's Encrypt renewal / HTTP redirect |
| HTTPS | 443 | TCP | `0.0.0.0/0` | Public API & Web Dashboard access |

> **Security Note**: Port `8000` must **NOT** be exposed publicly in the Security Group. Traffic must route through Nginx on port 80/443.

---

## 2. Step-by-Step Deployment on Fresh EC2 Instance

### Step 2.1: Connect to EC2 & Clone Repository
```bash
# SSH into EC2 instance
ssh -i your-key.pem ubuntu@<EC2-PUBLIC-IP>

# Update package index and install git
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-pip python3-venv python3-dev build-essential libssl-dev libffi-dev curl nginx

# Clone repository
git clone https://github.com/your-org/pillar1.git /home/ubuntu/pillar1
cd /home/ubuntu/pillar1
```

### Step 2.2: Setup Python Virtual Environment & Dependencies
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip & install project dependencies
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# Install Playwright Chromium and required Linux system libraries
python -m playwright install --with-deps chromium
```

### Step 2.3: Configure Environment Variables
```bash
# Copy example environment configuration
cp .env.example .env

# Edit .env to set your specific configuration
nano .env
```
Key `.env` variables to verify:
```ini
APP_ENV=production
HOST=127.0.0.1
PORT=8000
CORS_ORIGINS=*
PLAYWRIGHT_HEADLESS=true
MAX_RUNTIME=120
DISCOVERY_DEADLINE_SECONDS=55.0
SEARCH_MAX_RUNTIME=25.0
COMPANY_DEADLINE_SECONDS=40.0
```

### Step 2.4: Configure Systemd Service (Process Management)
```bash
# Copy systemd service file
sudo cp pillar1.service /etc/systemd/system/pillar1.service

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable pillar1

# Start the service
sudo systemctl start pillar1

# Verify status
sudo systemctl status pillar1
```

### Step 2.5: Configure Nginx Reverse Proxy
```bash
# Copy Nginx configuration
sudo cp pillar1.nginx.conf /etc/nginx/sites-available/pillar1

# Edit domain / IP in Nginx configuration
sudo nano /etc/nginx/sites-available/pillar1
# Replace YOUR_DOMAIN_OR_IP with your actual domain or EC2 Public IP

# Enable site and remove default
sudo ln -s /etc/nginx/sites-available/pillar1 /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test Nginx syntax and reload
sudo nginx -t
sudo systemctl restart nginx
```

### Step 2.6: Configure HTTPS (Let's Encrypt / Certbot)
If you have a domain pointing to the EC2 IP:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

## 3. Verification & Health Monitoring

### Test Health Endpoint
```bash
curl -i http://localhost:8000/health
# Or from external machine:
curl -i https://yourdomain.com/health
```
Expected response:
```json
{
  "status": "healthy",
  "service": "pillar1-api",
  "pipeline_status": "idle",
  "timestamp": 1726748400.0
}
```

### Test Live Scraping API Trigger
```bash
# Trigger a search
curl -X POST "http://localhost:8000/api/search?keyword=AI"

# Check execution progress
curl "http://localhost:8000/api/status"

# Fetch generated leads from SQLite database
curl "http://localhost:8000/api/leads?keyword=AI"
```

---

## 4. Maintenance & Operations

### View Live Application Logs
```bash
# Systemd service logs (Uvicorn and app stdout)
sudo journalctl -u pillar1 -f

# Network client rotating log
tail -f /home/ubuntu/pillar1/logs/network.log

# Error log
tail -f /home/ubuntu/pillar1/logs/errors.log
```

### Restarting / Updating Application
```bash
cd /home/ubuntu/pillar1
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart pillar1
```

### Log Rotation
Application logs in `logs/` are automatically rotated by `SafeRotatingFileHandler` (10 MB per file, 5 backups). Systemd journal logs are rotated automatically by `journald`.
