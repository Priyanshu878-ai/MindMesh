from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Optional, Tuple
import urllib.parse


class GitCloneError(Exception):
    """Raised when repository URL validation or git clone execution fails."""
    pass


@dataclass
class GitCloneConfig:
    """Configuration limits and options for safe git cloning."""
    clone_timeout_seconds: int = 60
    max_clone_size_bytes: int = 100 * 1024 * 1024  # 100 MB
    max_file_count: int = 10_000
    depth: int = 1
    single_branch: bool = True


def validate_github_url(url: str) -> Tuple[str, str, str]:
    """Validate a GitHub repository URL and return (canonical_url, owner, repo).

    Security checks enforced:
    - Scheme must be strictly 'https'.
    - Hostname must be strictly 'github.com' or 'www.github.com'.
    - No credentials / userinfo allowed (e.g. token@ or user:pass@).
    - No query parameters or fragments allowed.
    - Owner and repository names are validated against strict character allowlists.
    - Path traversal sequences (e.g. '..', '/', '\\') are rejected.
    - Returns canonical URL in format 'https://github.com/<owner>/<repo>'.
    """
    if not url or not isinstance(url, str):
        raise GitCloneError("GitHub repository URL cannot be empty")

    url_str = url.strip()
    if not url_str:
        raise GitCloneError("GitHub repository URL cannot be empty")

    if len(url_str) > 1024:
        raise GitCloneError("GitHub repository URL exceeds maximum permitted length of 1024 characters")

    # Reject ASCII control characters, newlines, and NUL bytes
    if any(ord(c) < 32 or ord(c) == 127 for c in url_str):
        raise GitCloneError("GitHub repository URL contains illegal control characters")

    try:
        parsed = urllib.parse.urlsplit(url_str)
    except Exception as exc:
        raise GitCloneError(f"Malformed repository URL: {str(exc)}")

    # Strict HTTPS scheme enforcement
    if parsed.scheme.lower() != "https":
        raise GitCloneError(
            f"Unsupported URL scheme '{parsed.scheme}'. Only 'https' GitHub repositories are supported."
        )

    # Reject userinfo / credentials
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise GitCloneError("Embedded credentials in GitHub repository URLs are strictly prohibited")

    # Strict host allowlisting
    if not parsed.hostname:
        raise GitCloneError("Invalid GitHub repository URL: missing hostname")

    hostname = parsed.hostname.lower()
    if hostname not in ("github.com", "www.github.com"):
        raise GitCloneError(
            f"Unsupported host '{hostname}'. Only public repositories hosted on github.com are supported."
        )

    # Reject non-standard ports
    if parsed.port is not None and parsed.port != 443:
        raise GitCloneError(
            f"Unsupported port '{parsed.port}'. Only standard HTTPS port 443 is permitted."
        )

    # Reject query parameters and fragments
    if parsed.query:
        raise GitCloneError("Query parameters are not permitted in GitHub repository URLs")

    if parsed.fragment:
        raise GitCloneError("URL fragments are not permitted in GitHub repository URLs")

    # Validate path structure: must be /{owner}/{repo} or /{owner}/{repo}.git
    path_clean = parsed.path.strip("/")
    parts = [p for p in path_clean.split("/") if p]
    if len(parts) != 2:
        raise GitCloneError(
            "GitHub repository URL must follow the format 'https://github.com/<owner>/<repo>'"
        )

    owner, repo_part = parts[0], parts[1]

    # Strip .git suffix if present
    if repo_part.endswith(".git"):
        repo = repo_part[:-4]
    else:
        repo = repo_part

    if not owner or not repo:
        raise GitCloneError("GitHub repository URL must include both owner and repository name")

    # Validate owner name: 1-39 chars, alphanumeric and single hyphens, cannot start or end with hyphen
    if not re.fullmatch(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$", owner):
        raise GitCloneError(f"Invalid GitHub repository owner '{owner}'")

    # Validate repo name: 1-100 chars, alphanumeric, underscores, hyphens, periods; cannot be '.' or '..'
    if repo in (".", "..") or not re.fullmatch(r"^[a-zA-Z0-9_.-]{1,100}$", repo):
        raise GitCloneError(f"Invalid GitHub repository name '{repo}'")

    canonical_url = f"https://github.com/{owner}/{repo}"
    return canonical_url, owner, repo


class SafeGitCloner:
    """Performs isolated, resource-bounded cloning of public GitHub repositories."""

    def __init__(self, config: Optional[GitCloneConfig] = None) -> None:
        self.config = config or GitCloneConfig()

    def clone(self, github_url: str, destination_dir: Path) -> Path:
        """Clone a public GitHub repository safely into destination_dir.

        Security constraints enforced:
        - Validates repository URL against strict GitHub allowlists.
        - Prevents command injection by executing git via argument list (shell=False).
        - Disables interactive credential prompts and GUI askpass helpers.
        - Enforces shallow clone (--depth 1, --single-branch, --no-tags) to minimize resource usage.
        - Enforces timeout, maximum directory size, and maximum file count.
        - Detects and rejects escaping symlinks after cloning.
        - Cleans up destination directory on any failure or cancellation.
        """
        canonical_url, _, _ = validate_github_url(github_url)

        dest = destination_dir.resolve()
        if dest.exists() and any(dest.iterdir()):
            raise GitCloneError(
                f"Destination directory already exists and is not empty: '{dest}'"
            )

        dest.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["git", "clone"]
        if self.config.depth > 0:
            cmd.extend(["--depth", str(self.config.depth)])
        if self.config.single_branch:
            cmd.append("--single-branch")
        cmd.extend(["--no-tags", canonical_url, str(dest)])

        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = "echo"
        env["GIT_OPTIONAL_LOCKS"] = "0"

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.clone_timeout_seconds,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            raise GitCloneError(
                f"Git clone operation timed out after {self.config.clone_timeout_seconds} seconds"
            )
        except Exception as exc:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            raise GitCloneError(f"Failed to execute git clone: {str(exc)}")

        if res.returncode != 0:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            err_msg = res.stderr.strip() if res.stderr else "Unknown git clone error"
            raise GitCloneError(f"Git clone failed: {err_msg}")

        if not dest.exists() or not dest.is_dir():
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            raise GitCloneError("Git clone completed but destination directory was not created")

        # Post-clone security and resource inspection
        total_size = 0
        file_count = 0

        for item in dest.rglob("*"):
            # Check symlink containment
            if item.is_symlink():
                try:
                    target = item.resolve()
                    if not (target == dest or target.is_relative_to(dest)):
                        if dest.exists():
                            shutil.rmtree(dest, ignore_errors=True)
                        raise GitCloneError(
                            f"Security violation: Symlink '{item.name}' points outside the repository workspace"
                        )
                except (ValueError, RuntimeError):
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    raise GitCloneError(
                        f"Security violation: Broken or invalid symlink '{item.name}'"
                    )

            if item.is_file():
                file_count += 1
                if file_count > self.config.max_file_count:
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    raise GitCloneError(
                        f"Cloned repository file count ({file_count}) exceeds limit of {self.config.max_file_count}"
                    )
                try:
                    size = item.stat().st_size
                    total_size += size
                    if total_size > self.config.max_clone_size_bytes:
                        if dest.exists():
                            shutil.rmtree(dest, ignore_errors=True)
                        raise GitCloneError(
                            f"Cloned repository size ({total_size} bytes) exceeds limit of {self.config.max_clone_size_bytes} bytes"
                        )
                except OSError:
                    pass

        return dest
