import subprocess


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def send_desktop_notification(title: str, message: str) -> None:
    """Fires a native macOS notification via osascript. This is
    intentionally macOS-only (the project's documented dev environment is
    otherwise Windows/PowerShell) -- failing quietly here matters more than
    the notification itself, since a broken alert must never take down the
    actual trading tick."""
    try:
        script = f'display notification "{_escape_applescript(message)}" with title "{_escape_applescript(title)}"'
        subprocess.run(["osascript", "-e", script], check=False, timeout=5, capture_output=True)
    except Exception:
        pass
