"""
Shared auth recovery — re-scan Firefox when cookies expire.
Import in server scripts: from server_auth import refresh_auth
"""

import json
import sqlite3
import shutil
import os
from pathlib import Path


def refresh_auth(domain_pattern: str, cookie_names: list[str], 
                 auth_file: Path, browser_profile: Path) -> dict | None:
    """
    Re-scan Windows Firefox profiles for fresh cookies.
    
    Args:
        domain_pattern: SQL LIKE pattern for cookie host (e.g. '%mimo%')
        cookie_names: specific cookie names to look for
        auth_file: where to save the auth JSON
        browser_profile: persistent browser profile dir (not used for scan)
    
    Returns new auth dict or None.
    """
    for ud in Path("/mnt/c/Users").iterdir():
        if not ud.is_dir():
            continue
        fp = ud / "AppData/Roaming/Mozilla/Firefox/Profiles"
        if not fp.exists():
            continue
        for p in fp.iterdir():
            if not (p / "cookies.sqlite").exists():
                continue
            try:
                t = Path(f"/tmp/ra_{os.getpid()}.sqlite")
                shutil.copy2(str(p / "cookies.sqlite"), str(t))
                c = sqlite3.connect(str(t))
                cur = c.cursor()
                cur.execute(
                    f"SELECT name,value,host FROM moz_cookies "
                    f"WHERE host LIKE ?",
                    (domain_pattern,)
                )
                rows = cur.fetchall()
                c.close()
                t.unlink(missing_ok=True)
                
                if rows:
                    cookies = {n: v.strip('"') for n, v, _ in rows}
                    # Check if essential cookies are present
                    if any(name in cookies for name in cookie_names):
                        auth = {
                            "cookies": cookies,
                            "cookie_count": len(cookies),
                        }
                        from datetime import datetime, timezone
                        auth["saved_at"] = datetime.now(timezone.utc).isoformat()
                        auth_file.parent.mkdir(parents=True, exist_ok=True)
                        auth_file.write_text(json.dumps(auth, indent=2))
                        return auth
            except Exception:
                pass
    return None
