"""Install user-level systemd timers on the machine that stores Metadex data."""

import shutil
import subprocess
from pathlib import Path


def main() -> None:
    backend = Path(__file__).resolve().parents[1] / "backend"
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required on this host")
    if any(character.isspace() for character in str(backend) + uv):
        raise SystemExit("install path with whitespace is not supported by this installer")
    units = Path.home() / ".config" / "systemd" / "user"
    units.mkdir(parents=True, exist_ok=True)
    services = {
        "metadex-daily.service": "daily",
        "metadex-monitor.service": "monitor",
    }
    for name, command in services.items():
        (units / name).write_text(
            "[Unit]\nDescription=Metadex " + command + "\n\n"
            "[Service]\nType=oneshot\n"
            f"WorkingDirectory={backend}\n"
            f"ExecStart={uv} run --frozen python -m app.operations {command}\n",
            encoding="utf-8",
        )
    timers = {
        "metadex-daily.timer": "*-*-* 03:15:00 UTC",
        "metadex-monitor.timer": "hourly",
    }
    for name, schedule in timers.items():
        service = name.replace(".timer", ".service")
        (units / name).write_text(
            "[Unit]\nDescription=Schedule " + service + "\n\n"
            "[Timer]\n"
            f"OnCalendar={schedule}\n"
            "Persistent=true\n"
            f"Unit={service}\n\n"
            "[Install]\nWantedBy=timers.target\n",
            encoding="utf-8",
        )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", *timers], check=True
    )
    print("Installed daily and hourly monitor timers. Run systemctl --user list-timers metadex-*.")


if __name__ == "__main__":
    main()
