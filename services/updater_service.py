import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Optional, Dict, Any, Tuple

from utils.logger import log

RESTART_NOTICE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "restart_notice.json")


class UpdaterService:
    _instance: Optional['UpdaterService'] = None

    @classmethod
    def get_instance(cls) -> 'UpdaterService':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def is_git_repo(self) -> bool:
        """Checks if current directory is a valid git repository."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )
            return res.returncode == 0 and res.stdout.strip() == "true"
        except Exception:
            return False

    def get_current_commit(self) -> Tuple[str, str, str]:
        """Returns (hash[:7], commit_subject, commit_date)."""
        try:
            res = subprocess.run(
                ["git", "log", "-1", "--format=%h|%s|%cr"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )
            if res.returncode == 0 and "|" in res.stdout:
                parts = res.stdout.strip().split("|", 2)
                h = parts[0]
                s = parts[1] if len(parts) > 1 else "Unknown"
                d = parts[2] if len(parts) > 2 else "Unknown"
                return h, s, d
        except Exception as e:
            log.warning(f"[Updater] get_current_commit error: {e}")
        return "unknown", "No git commit found", "Unknown"

    def check_for_updates(self, remote: str = "origin", branch: str = "main") -> Optional[Dict[str, Any]]:
        """
        Fetches the remote repository and compares local HEAD with remote branch.
        Returns a dictionary with commit details if updates exist, or None if up to date.
        """
        if not self.is_git_repo():
            return None

        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"

        # 1. Fetch remote changes
        try:
            fetch_res = subprocess.run(
                ["git", "fetch", remote, branch],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                env=env
            )
            if fetch_res.returncode != 0:
                log.debug(f"[Updater] git fetch error: {fetch_res.stderr.strip()}")
                return None
        except Exception as e:
            log.debug(f"[Updater] git fetch exception: {e}")
            return None

        # 2. Get local HEAD hash
        local_hash = ""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )
            if res.returncode == 0:
                local_hash = res.stdout.strip()
        except Exception:
            return None

        # 3. Get remote branch hash
        remote_hash = ""
        try:
            res = subprocess.run(
                ["git", "rev-parse", f"{remote}/{branch}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )
            if res.returncode == 0:
                remote_hash = res.stdout.strip()
        except Exception:
            return None

        # Compare hashes
        if local_hash and remote_hash and local_hash != remote_hash:
            summary = "New commit on GitHub"
            try:
                res = subprocess.run(
                    ["git", "log", "-1", "--format=%h - %s (%cr)", f"{remote}/{branch}"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5
                )
                if res.returncode == 0:
                    summary = res.stdout.strip()
            except Exception:
                pass

            return {
                "local_hash": local_hash[:7],
                "remote_hash": remote_hash[:7],
                "summary": summary,
                "remote": remote,
                "branch": branch
            }

        return None

    def pull_updates(self, remote: str = "origin", branch: str = "main") -> Tuple[bool, str]:
        """
        Pulls latest updates from GitHub using autostash.
        Falls back to hard reset against remote if merge conflicts exist.
        """
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"

        # 1. Try pulling with autostash
        try:
            res = subprocess.run(
                ["git", "pull", "--autostash", remote, branch],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env=env
            )
            if res.returncode == 0:
                return True, res.stdout.strip()
        except Exception as e:
            log.warning(f"[Updater] git pull exception: {e}")

        # 2. Fallback: reset hard against remote branch to guarantee 100% clean deployment
        try:
            log.info("[Updater] Attempting clean reset to remote branch...")
            subprocess.run(["git", "fetch", remote, branch], capture_output=True, check=False, timeout=20, env=env)
            reset_res = subprocess.run(
                ["git", "reset", "--hard", f"{remote}/{branch}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
                env=env
            )
            if reset_res.returncode == 0:
                return True, reset_res.stdout.strip()
            return False, reset_res.stderr.strip()
        except Exception as e:
            return False, str(e)

    def save_restart_notice(self, notice: Dict[str, Any]):
        """Persists restart notice to notify users in Discord upon reboot."""
        try:
            os.makedirs(os.path.dirname(RESTART_NOTICE_FILE), exist_ok=True)
            notice["saved_at"] = time.time()
            with open(RESTART_NOTICE_FILE, "w", encoding="utf-8") as f:
                json.dump(notice, f, indent=2)
        except Exception as e:
            log.warning(f"[Updater] Could not save restart notice: {e}")

    def consume_restart_notice(self) -> Optional[Dict[str, Any]]:
        """Reads and deletes restart notice if it was created within the last 5 minutes."""
        if not os.path.exists(RESTART_NOTICE_FILE):
            return None
        try:
            with open(RESTART_NOTICE_FILE, "r", encoding="utf-8") as f:
                notice = json.load(f)
            os.remove(RESTART_NOTICE_FILE)
            # Check freshness (within 300 seconds)
            if time.time() - notice.get("saved_at", 0) < 300:
                return notice
        except Exception as e:
            log.warning(f"[Updater] Could not consume restart notice: {e}")
        return None

    async def restart_bot(self, bot: Optional[Any] = None, delay: float = 1.0):
        """
        Gracefully closes active voice clients, database connections,
        and re-launches the bot process.
        """
        log.info("[Updater] Initiating graceful process restart...")
        if bot:
            try:
                for vc in list(getattr(bot, "voice_clients", [])):
                    try:
                        await vc.disconnect(force=True)
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                await bot.close()
            except Exception:
                pass

        await asyncio.sleep(delay)

        # Re-launch current Python process
        try:
            if sys.platform == "win32":
                subprocess.Popen([sys.executable] + sys.argv)
                os._exit(0)
            else:
                # In-place execv replacement on Linux, Termux, and Docker
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            log.critical(f"[Updater] Failed to re-launch process: {e}")
            os._exit(0)
