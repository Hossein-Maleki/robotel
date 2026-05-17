
# Action: file_editor create /app/bot/main.py --file-text """"
# Launcher: runs telebot.py (Telegram bot) and rub_worker.py (Rubika worker)
# as two child processes, restarts them if they crash.
# """
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable


def start_process(script: str) -> subprocess.Popen:
    return subprocess.Popen(
        [PYTHON, "-u", str(BASE_DIR / script)],
        cwd=str(BASE_DIR),
        env=os.environ.copy(),
    )


def main() -> None:
    print("=== Tele2Rub Pro launcher ===")
    procs: dict[str, subprocess.Popen] = {}

    def shutdown(*_):
        print("Shutting down ...")
        for p in procs.values():
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs.values():
            try:
                p.wait(timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    targets = {"rubika": "rub_worker.py", "telegram": "telebot.py"}

    # Start rubika first so it can prompt for the verification code interactively
    for name, script in targets.items():
        procs[name] = start_process(script)
        print(f"[{name}] started (pid={procs[name].pid})")
        time.sleep(2)

    # Supervise: if any process dies, restart it after a short delay.
    while True:
        for name, script in targets.items():
            proc = procs[name]
            if proc.poll() is not None:
                print(f"[{name}] exited with code {proc.returncode}. Restarting in 5s ...")
                time.sleep(5)
                procs[name] = start_process(script)
                print(f"[{name}] restarted (pid={procs[name].pid})")
        time.sleep(2)


if __name__ == "__main__":
    main()
