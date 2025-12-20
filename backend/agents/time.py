from mcp.server.fastmcp import FastMCP
from datetime import datetime
import zoneinfo

# Initialize FastMCP server
mcp = FastMCP("Time Agent")

@mcp.tool()
def get_current_time(timezone: str = "UTC") -> str:
    """Get the current time in a specific timezone (default UTC)."""
    try:
        tz = zoneinfo.ZoneInfo(timezone)
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    mcp.run()
