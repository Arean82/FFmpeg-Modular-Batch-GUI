"""Linux power supply and battery monitor.

Reads AC line status and battery charge percentage via /sys/class/power_supply.
"""
import glob
import os


def get_power_status() -> tuple[bool, int]:
    """Returns (is_on_ac: bool, battery_percent: int).

    If no battery is detected (e.g. desktop), returns (True, 100).
    """
    is_on_ac = True
    battery_level = 100

    power_supplies = glob.glob("/sys/class/power_supply/*")
    if not power_supplies:
        return True, 100

    has_battery = False
    battery_capacities = []

    for ps in power_supplies:
        type_file = os.path.join(ps, "type")
        if not os.path.isfile(type_file):
            continue
        try:
            with open(type_file, encoding="utf-8") as f:
                ps_type = f.read().strip().lower()

            if ps_type in ("mains", "ac"):
                online_file = os.path.join(ps, "online")
                if os.path.isfile(online_file):
                    with open(online_file, encoding="utf-8") as f:
                        online_val = f.read().strip()
                        is_on_ac = (online_val == "1")

            elif ps_type == "battery":
                has_battery = True
                capacity_file = os.path.join(ps, "capacity")
                if os.path.isfile(capacity_file):
                    with open(capacity_file, encoding="utf-8") as f:
                        cap = int(f.read().strip())
                        battery_capacities.append(cap)
        except Exception:
            continue

    if has_battery and battery_capacities:
        battery_level = sum(battery_capacities) // len(battery_capacities)
    elif not has_battery:
        is_on_ac = True
        battery_level = 100

    return is_on_ac, battery_level
