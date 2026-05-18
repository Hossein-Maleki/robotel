import subprocess
import sys
import signal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

telegram_file = BASE_DIR / "telebot.py"
rubika_file = BASE_DIR / "rubbot.py"

telegram_proc = None
rubika_proc = None


def cleanup(signum=None, frame=None):
    for proc in [telegram_proc, rubika_proc]:
        if proc and proc.poll() is None:
            proc.terminate()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def main():
    global telegram_proc, rubika_proc

    print("=" * 50)
    print("  Telegram-to-Rubika File Transfer Bot")
    print("=" * 50)
    print()
    print("Starting services...")

    try:
        # Start Rubika bot first (needs session)
        print("[1/2] Starting Rubika bot...")
        rubika_proc = subprocess.Popen(
            [sys.executable, str(rubika_file)],
            cwd=str(BASE_DIR)
        )

        # Start Telegram bot
        print("[2/2] Starting Telegram bot...")
        telegram_proc = subprocess.Popen(
            [sys.executable, str(telegram_file)],
            cwd=str(BASE_DIR)
        )

        print()
        print("Both services are running.")
        print("Press Ctrl+C to stop.")
        print()

        # Wait for either process to exit
        while True:
            if rubika_proc.poll() is not None:
                print(f"Rubika bot exited with code {rubika_proc.returncode}")
                break
            if telegram_proc.poll() is not None:
                print(f"Telegram bot exited with code {telegram_proc.returncode}")
                break

            try:
                rubika_proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        cleanup()


if __name__ == "__main__":
    main()


