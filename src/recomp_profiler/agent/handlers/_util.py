from __future__ import annotations

import asyncio
import shutil


async def run_capture(argv: list[str], timeout: float = 10.0) -> str | None:
    """Run a helper tool and return stdout, or None if missing/failing."""
    if shutil.which(argv[0]) is None:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    return out.decode(errors="replace") if proc.returncode == 0 else None
