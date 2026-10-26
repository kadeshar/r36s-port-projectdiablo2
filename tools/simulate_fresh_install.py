#!/usr/bin/env python3
"""Simulate fresh installation of Project Diablo 2 on R36S console.

This tool safely resets the port to a fresh first-boot state without
affecting game saves or original game assets.
Can run remotely via SSH (plink/ssh) or locally on the console with --local.
"""

import argparse
import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys


REMOTE_SCRIPT = r'''
import os
import sys
import shutil
import glob
import subprocess
from datetime import datetime

def log(msg):
    print(f"[FRESH-INSTALL] {msg}", flush=True)

dry_run = "--dry-run" in sys.argv

# 1. Locate ports dir
candidates = ["/roms2/ports/projectdiablo2", "/roms/ports/projectdiablo2"]
port_dir = None
for c in candidates:
    if os.path.isdir(c):
        port_dir = c
        break

if not port_dir:
    log("ERROR: Could not find projectdiablo2 directory in /roms2/ports or /roms/ports")
    sys.exit(1)

log(f"Target port directory: {port_dir}")
roms_ports = os.path.dirname(port_dir)

# 2. Locate all save files (*.d2s, *.key, *.ma0, *.map)
save_extensions = ('.d2s', '.key', '.ma0', '.map', '.ctl')
found_saves = []

def scan_saves(directory):
    if not os.path.isdir(directory):
        return []
    result = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(save_extensions):
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, directory)
                result.append((full_path, rel_path, os.path.getsize(full_path)))
    return result

home_state = os.path.expanduser("~/.local/share/pd2-r36s")
save_locations = [
    ("saves", os.path.join(port_dir, "saves")),
    ("saves_s14", os.path.join(port_dir, "saves_s14")),
    ("gamedata", os.path.join(port_dir, "gamedata")),
    ("home_state_saves", os.path.join(home_state, "saves")),
]

total_saves_count = 0
for loc_name, loc_path in save_locations:
    saves = scan_saves(loc_path)
    total_saves_count += len(saves)
    if saves:
        log(f"Found {len(saves)} save files in {loc_name} ({loc_path})")
        for full, rel, sz in saves:
            found_saves.append((loc_name, full, rel, sz))

log(f"Total save files found: {len(found_saves)}")

# 3. Create backup of all saves
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = os.path.join(roms_ports, f"projectdiablo2-saves-backup-{ts}")
log(f"Backing up saves to: {backup_dir}")

if not dry_run:
    os.makedirs(backup_dir, exist_ok=True)
    for loc_name, full, rel, sz in found_saves:
        dest = os.path.join(backup_dir, loc_name, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(full, dest)
    log(f"Backup completed successfully ({len(found_saves)} files saved)")

# 4. Check for active mounts or loop devices
env_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
os.environ["PATH"] = env_path

state_img = os.path.join(port_dir, "storage", "state.ext4")
try:
    res = subprocess.run(["losetup", "-j", state_img], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if res.stdout.strip():
        log(f"Attached loop device found for state.ext4: {res.stdout.strip()}")
        if not dry_run:
            log("Attempting unmount / detach of loop device...")
            # Unmount any mounts inside storage
            subprocess.run(["umount", os.path.join(port_dir, "storage", "mounted-state")], stderr=subprocess.DEVNULL)
            subprocess.run(["umount", os.path.join(port_dir, "storage", "mounted-wine-check")], stderr=subprocess.DEVNULL)
            loop_dev = res.stdout.split(":")[0].strip()
            subprocess.run(["losetup", "-d", loop_dev])
except Exception as e:
    log(f"Notice: losetup check returned: {e}")

# 5. Clean runtime and first-boot artifacts (DO NOT touch saves or gamedata)
paths_to_remove = [
    ("state image", os.path.join(port_dir, "storage", "state.ext4")),
    ("session lock", os.path.join(port_dir, "storage", "session.lock")),
    ("runtime logs", glob.glob(os.path.join(port_dir, "logs", "*.log"))),
]

for label, p in paths_to_remove:
    if isinstance(p, list):
        for item in p:
            log(f"Removing {label}: {item}")
            if not dry_run and os.path.exists(item):
                os.remove(item)
    elif os.path.exists(p):
        log(f"Removing {label}: {p}")
        if not dry_run:
            os.remove(p)
    else:
        log(f"{label} does not exist (already clean)")

# Ensure mountpoint directories exist and are clean
for mp in ["mounted-state", "mounted-wine-check"]:
    mp_path = os.path.join(port_dir, "storage", mp)
    if os.path.exists(mp_path):
        if not dry_run:
            for item in os.listdir(mp_path):
                ip = os.path.join(mp_path, item)
                try:
                    if os.path.isdir(ip): shutil.rmtree(ip)
                    else: os.remove(ip)
                except Exception as e:
                    log(f"Warning: could not clean {ip}: {e}")
    else:
        if not dry_run:
            os.makedirs(mp_path, exist_ok=True)

# 6. Reset $HOME/.local/share/pd2-r36s runtime artifacts (protecting saves)
if os.path.isdir(home_state):
    log(f"Cleaning runtime artifacts in home state: {home_state}")
    items_to_clean = ["wineprefix", "game", "session-layout.json", "session-layout.json.new", "session.lock", "wine-launchers"]
    for it in items_to_clean:
        ip = os.path.join(home_state, it)
        if os.path.exists(ip):
            log(f"Cleaning {ip}")
            if not dry_run:
                if os.path.isdir(ip):
                    shutil.rmtree(ip, ignore_errors=True)
                else:
                    try: os.remove(ip)
                    except Exception: pass
    # Clean runtime-* directories in home_state
    for rt in glob.glob(os.path.join(home_state, "runtime-*")):
        log(f"Cleaning runtime cache: {rt}")
        if not dry_run:
            shutil.rmtree(rt, ignore_errors=True)

# 7. Verification of Game Assets & Saves Integrity
log("=== Post-Reset Integrity Check ===")
# A. Verify state.ext4 is gone
if not dry_run:
    if os.path.exists(state_img):
        log("ERROR: state.ext4 still exists!")
        sys.exit(1)
    else:
        log("PASS: state.ext4 is removed (first-boot state ready).")
else:
    log("DRY-RUN: state.ext4 check skipped.")

# B. Verify saves still exist
post_saves_count = 0
for loc_name, loc_path in save_locations:
    saves = scan_saves(loc_path)
    post_saves_count += len(saves)

log(f"Original saves count: {total_saves_count}, Post-reset saves count: {post_saves_count}")
if post_saves_count < total_saves_count:
    log("ERROR: Saves count decreased! Check backup immediately!")
    sys.exit(1)
else:
    log("PASS: All game saves intact and verified.")

# C. Verify game files still exist
game_exe_found = False
for check_path in [
    os.path.join(port_dir, "gamedata", "Diablo II", "ProjectD2", "Game.exe"),
    os.path.join(port_dir, "gamedata", "Diablo II", "game.exe"),
    os.path.join(port_dir, "gamedata", "Diablo II", "GAME.EXE"),
    os.path.join(port_dir, "gamedata", "Diablo II_s14", "ProjectD2", "Game.exe"),
]:
    if os.path.isfile(check_path):
        game_exe_found = True
        log(f"PASS: Game executable verified at {check_path}")
        break

if not game_exe_found:
    log("NOTICE: Game executable not found in standard subdirectories, checking gamedata...")
    for root, dirs, files in os.walk(os.path.join(port_dir, "gamedata")):
        for f in files:
            if f.lower() == "game.exe":
                game_exe_found = True
                log(f"PASS: Game executable found at {os.path.join(root, f)}")
                break
        if game_exe_found:
            break

# D. Launcher permissions
launcher = os.path.join(roms_ports, "Project Diablo 2.sh")
if os.path.isfile(launcher) and not dry_run:
    os.chmod(launcher, 0o755)
    log("PASS: Project Diablo 2.sh executable permissions set (0755).")

log("=== FRESH INSTALL SIMULATION COMPLETED SUCCESSFULLY ===")
log("Target console is now in clean first-boot state. User can launch game to test fresh initialization.")
'''


def run_remote(host, user, password, dry_run=False):
    print(f"Connecting to {host} as {user}...")

    cmd_prefix = []
    if shutil.which("plink"):
        cmd_prefix = ["plink", "-batch", "-pw", password, f"{user}@{host}"]
    elif shutil.which("sshpass") and shutil.which("ssh"):
        cmd_prefix = ["sshpass", "-p", password, "ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{host}"]
    elif shutil.which("ssh"):
        cmd_prefix = ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{host}"]
    else:
        print("Error: neither plink nor ssh found in PATH.")
        sys.exit(1)

    args = ["--dry-run"] if dry_run else []
    # Feed the python script via stdin: python3 - <args>
    full_cmd = cmd_prefix + ["python3", "-"] + args
    result = subprocess.run(full_cmd, input=REMOTE_SCRIPT, text=True, capture_output=False)
    return result.returncode


def run_local(dry_run=False):
    exec_globals = {"__name__": "__main__"}
    if dry_run:
        sys.argv.append("--dry-run")
    exec(REMOTE_SCRIPT, exec_globals)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Simulate fresh installation of Project Diablo 2 on R36S")
    parser.add_argument("--host", default="192.168.50.135", help="Target console IP (default: 192.168.50.135)")
    parser.add_argument("--user", default="ark", help="Console user (default: ark)")
    parser.add_argument("--password", default="ark", help="Console password (default: ark)")
    parser.add_argument("--local", action="store_true", help="Run locally directly on console")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without removing any files")

    args = parser.parse_args()

    if args.local:
        return run_local(dry_run=args.dry_run)
    else:
        return run_remote(args.host, args.user, args.password, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
