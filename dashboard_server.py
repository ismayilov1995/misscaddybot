# dashboard_server.py
"""Entry point for the dashboard — run separately from the bot."""
import os
from dotenv import load_dotenv

load_dotenv()

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=port, reload=False)
