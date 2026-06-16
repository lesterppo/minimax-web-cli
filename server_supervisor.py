#!/usr/bin/env python3
"""
Supervisor for AI web CLI page servers — keeps MiniMax, MiMo, Qwen alive.

Usage:
  python server_supervisor.py                # Start all, monitor, auto-restart
  python server_supervisor.py --stop         # Stop all
  python server_supervisor.py --status       # Check health of all
  python server_supervisor.py --restart      # Restart all
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()

SERVERS = {
    "minimax": {
        "port": 9871,
        "script": HOME / ".hermes" / "scripts" / "minimax" / "minimax_server.py",
        "pid_file": HOME / ".minimax-cli" / "server.pid",
    },
    "mimo": {
        "port": 9872,
        "script": HOME / ".hermes" / "scripts" / "mimo" / "mimo_server.py",
        "pid_file": HOME / ".mimo-cli" / "server.pid",
    },
    "qwen": {
        "port": 9873,
        "script": HOME / ".hermes" / "scripts" / "qwen" / "qwen_server.py",
        "pid_file": HOME / ".qwen-cli" / "server.pid",
    },
}

SUPERVISOR_PID = HOME / ".chrome-daemon" / "supervisor.pid"
CHECK_INTERVAL = 30  # seconds between health checks
MAX_RESTARTS = 5      # max restarts per check interval (rate limit)
BOOT_WAIT = 3         # seconds between starting each server


def is_healthy(port: int) -> bool:
    """Check if a server is responding."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def is_running(name: str) -> bool:
    """Check if server process is alive via PID file."""
    cfg = SERVERS[name]
    if cfg["pid_file"].exists():
        try:
            pid = int(cfg["pid_file"].read_text().strip())
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, ValueError, FileNotFoundError):
            cfg["pid_file"].unlink(missing_ok=True)
    return False


def start_server(name: str) -> bool:
    """Start a server. Returns True if started successfully."""
    cfg = SERVERS[name]
    
    # Already running?
    if is_healthy(cfg["port"]):
        return True
    
    # Kill stale PID if port is in use but process dead
    if is_running(name):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{cfg['port']}/stop", timeout=2)
        except Exception:
            pass
        time.sleep(1)
    
    # Launch
    log_path = HOME / ".chrome-daemon" / f"{name}_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        proc = subprocess.Popen(
            [sys.executable, str(cfg["script"])],
            stdout=open(log_path, "a"),
            stderr=open(log_path, "a"),
            start_new_session=True,
        )
    except Exception as e:
        print(f"  {name}: failed to start — {e}", flush=True)
        return False
    
    # Wait for health
    deadline = time.time() + 20
    while time.time() < deadline:
        if is_healthy(cfg["port"]):
            return True
        time.sleep(0.5)
    
    print(f"  {name}: started but not healthy after 20s", flush=True)
    return False


def stop_server(name: str):
    """Stop a server gracefully."""
    cfg = SERVERS[name]
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{cfg['port']}/stop", timeout=3)
    except Exception:
        pass
    # Kill hard if still running
    time.sleep(1)
    if is_running(name):
        try:
            pid = int(cfg["pid_file"].read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    cfg["pid_file"].unlink(missing_ok=True)


def start_all():
    """Start all servers sequentially with boot delay."""
    print("[supervisor] Starting all servers...", flush=True)
    for name in SERVERS:
        print(f"  {name}...", end=" ", flush=True)
        ok = start_server(name)
        print("✓" if ok else "✗", flush=True)
        if ok and name != list(SERVERS.keys())[-1]:
            time.sleep(BOOT_WAIT)


def stop_all():
    """Stop all servers."""
    print("[supervisor] Stopping all servers...", flush=True)
    for name in SERVERS:
        stop_server(name)
    SUPERVISOR_PID.unlink(missing_ok=True)


def status_all():
    """Print status of all servers."""
    print(f"{'Server':<12} {'Port':<8} {'Health':<8} {'PID'}")
    print("-" * 38)
    all_ok = True
    for name, cfg in SERVERS.items():
        healthy = is_healthy(cfg["port"])
        running = is_running(name)
        pid = ""
        if cfg["pid_file"].exists():
            try:
                pid = cfg["pid_file"].read_text().strip()
            except Exception:
                pass
        h = "✓ OK" if healthy else "✗ DOWN"
        r = "✓" if running else "✗"
        print(f"{name:<12} {cfg['port']:<8} {h:<8} {r} {pid}")
        if not healthy:
            all_ok = False
    return all_ok


def monitor_loop():
    """Main loop: start all, then monitor and restart on failure."""
    start_all()
    
    restart_counts = {name: 0 for name in SERVERS}
    last_reset = time.time()
    
    print(f"[supervisor] Monitoring every {CHECK_INTERVAL}s...", flush=True)
    
    while True:
        time.sleep(CHECK_INTERVAL)
        
        # Reset restart counters every 5 minutes
        if time.time() - last_reset > 300:
            restart_counts = {name: 0 for name in SERVERS}
            last_reset = time.time()
        
        for name, cfg in SERVERS.items():
            if not is_healthy(cfg["port"]):
                if restart_counts[name] >= MAX_RESTARTS:
                    print(f"[supervisor] {name} exceeded max restarts — skipping",
                          flush=True)
                    continue
                
                print(f"[supervisor] {name} DOWN — restarting...", flush=True)
                restart_counts[name] += 1
                ok = start_server(name)
                if ok:
                    print(f"[supervisor] {name} RECOVERED", flush=True)
                else:
                    print(f"[supervisor] {name} FAILED to restart "
                          f"({restart_counts[name]}/{MAX_RESTARTS})", flush=True)


def daemonize():
    """Fork into background."""
    if os.fork() > 0:
        return False
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    os.chdir("/")
    os.umask(0)
    sys.stdin = open("/dev/null", "r")
    log_dir = HOME / ".chrome-daemon"
    log_dir.mkdir(parents=True, exist_ok=True)
    sys.stdout = open(log_dir / "supervisor.log", "a")
    sys.stderr = sys.stdout
    return True


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--stop":
            stop_all()
            return
        if cmd == "--status":
            ok = status_all()
            sys.exit(0 if ok else 1)
            return
        if cmd == "--restart":
            stop_all()
            time.sleep(2)
            start_all()
            return
        if cmd == "--foreground":
            SUPERVISOR_PID.parent.mkdir(parents=True, exist_ok=True)
            SUPERVISOR_PID.write_text(str(os.getpid()))
            monitor_loop()
            return
        print(f"Unknown: {cmd}")
        sys.exit(1)
    
    # Background mode
    if daemonize():
        SUPERVISOR_PID.parent.mkdir(parents=True, exist_ok=True)
        SUPERVISOR_PID.write_text(str(os.getpid()))
        signal.signal(signal.SIGTERM, lambda *a: (stop_all(), sys.exit(0)))
        signal.signal(signal.SIGINT, lambda *a: (stop_all(), sys.exit(0)))
        monitor_loop()


if __name__ == "__main__":
    main()
