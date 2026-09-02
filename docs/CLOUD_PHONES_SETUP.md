# CloudPhones Setup Guide

## Overview

This guide sets up cloud Android instances using Redroid (Android in Docker) on Oracle Cloud's free tier ARM instance, with full stealth protocols matching your local MuMu setup.

## Prerequisites

1. Oracle Cloud account (free tier)
2. Windows machine with ADB
3. Tailscale (for secure connection)

## Step 1: Create Oracle Cloud ARM Instance

1. Go to https://cloud.oracle.com
2. Create a new VM instance:
   - **Shape**: VM.Standard.A1.Flex (ARM)
   - **OCPU**: 4 (free tier)
   - **RAM**: 24 GB (free tier)
   - **OS**: Ubuntu 22.04 or Oracle Linux 8
3. Save the SSH key
4. Note the public IP

## Step 2: Install Docker and Redroid

SSH into your instance and run:

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Install kernel modules for Redroid
sudo apt-get update
sudo apt-get install -y linux-headers-$(uname -r) dkms

# Load required modules
sudo modprobe binder_linux
sudo modprobe ashmem_linux

# Make modules persistent
echo "binder_linux" | sudo tee /etc/modules-load.d/binder.conf
echo "ashmem_linux" | sudo tee -a /etc/modules-load.d/binder.conf
```

## Step 3: Deploy Redroid Instances

Copy `docker-compose.redroid.yml` to your instance and run:

```bash
docker compose -f docker-compose.redroid.yml up -d
```

This creates 8 Android instances on ports 5555-5562.

## Step 4: Connect from Windows

```batch
REM Connect to all instances
adb connect 100.x.x.x:5555
adb connect 100.x.x.x:5556
... (up to 5562)

REM Or use the CloudPhones tool
CloudPhones.exe connect --host 100.x.x.x
```

## Step 5: Apply Stealth

```batch
CloudPhones.exe stealth --host 100.x.x.x --count 8
```

This applies:
- Unique device fingerprints
- Valid IMEI numbers
- Unique Android IDs
- Browser user-agents matching each device
- Anti-detection properties

## Step 6: Set Up Tor (Optional)

```batch
CloudPhones.exe tor --host 100.x.x.x --verify
```

Each device gets its own Tor circuit with a unique exit IP.

## Step 7: Verify

```batch
CloudPhones.exe status
```

Should show all 8 devices online with their spoofed identities.

## Integration with CPharm

Once connected, the cloud phones appear as regular ADB devices. Your existing CPharm automation can use them alongside your local MuMu VMs.

## Troubleshooting

### ADB can't connect
- Ensure Tailscale is running on both machines
- Check firewall rules allow ADB ports (5555-5562)
- Verify Redroid containers are running: `docker ps`

### Stealth not applying
- Run as Administrator if needed
- Check ADB connectivity: `adb devices`
- Verify device is fully booted: `adb shell getprop sys.boot_completed`

### Tor not working
- Ensure Tor is installed in the containers
- Check Tor logs: `adb shell cat /data/tor_0/tor.log`
- Wait 30 seconds for initial bootstrap
