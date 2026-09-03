from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def log(level, message):
    timestamp = datetime.now(IST).strftime("%d/%m/%Y, %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")
