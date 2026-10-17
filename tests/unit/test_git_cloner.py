from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from engines.ingestion.git import (
    GitCloneConfig,
    GitCloneError,
    SafeGitCloner,
    validate_github_url,
)


class TestValidateGitHubUrl:
    """Unit tests for GitHub URL validation and security sanitization."""

    @pytest.mark.parametrize(
        "valid_url,expected_canonical,expected_owner,expected_repo",
        [
            ("https://github.com/pallets/flask", "https://github.com/pallets/flask", "pallets", "flask"),
            ("https://github.com/pallets/flask.git", "https://github.com/pallets/flask", "pallets", "flask"),
            ("https://github.com/pallets/flask/", "https://github.com/pallets/flask", "pallets", "flask"),
            ("https://www.github.com/octocat/Hello-World", "https://github.com/octocat/Hello-World", "octocat", "Hello-World"),
            ("https://github.com/my-org/my_repo-1.0", "https://github.com/my-org/my_repo-1.0", "my-org", "my_repo-1.0"),
            ("https://github.com/A/B", "https://github.com/A/B", "A", "B"),
            ("  https://github.com/owner/repo.git  ", "https://github.com/owner/repo", "owner", "repo"),
        ],
    )
    def test_valid_urls(self, valid_url, expected_canonical, expected_owner, expected_repo):
        canonical, owner, repo = validate_github_url(valid_url)
        assert canonical == expected_canonical
        assert owner == expected_owner
        assert repo == expected_repo

    @pytest.mark.parametrize(
        "invalid_scheme",
        [
            "http://github.com/pallets/flask",
            "git://github.com/pallets/flask",
            "ssh://git@github.com/pallets/flask",
            "ftp://github.com/pallets/flask",
            "file:///tmp/repo",
            "javascript:alert(1)",
        ],
    )
    def test_reject_invalid_schemes(self, invalid_scheme):
        with pytest.raises(GitCloneError, match="Unsupported URL scheme"):
            validate_github_url(invalid_scheme)

    @pytest.mark.parametrize(
        "unsupported_host",
        [
            "https://gitlab.com/owner/repo",
            "https://bitbucket.org/owner/repo",
            "https://evil-github.com/owner/repo",
            "https://github.com.attacker.com/owner/repo",
            "https://192.168.1.1/owner/repo",
            "https://127.0.0.1/owner/repo",
        ],
    )
    def test_reject_unsupported_hosts(self, unsupported_host):
        with pytest.raises(GitCloneError, match="Unsupported host"):
            validate_github_url(unsupported_host)

    @pytest.mark.parametrize(
        "credential_url",
        [
            "https://user:pass@github.com/owner/repo",
            "https://token@github.com/owner/repo",
            "https://oauth2:ghp_12345@github.com/owner/repo",
        ],
    )
    def test_reject_credentials_in_url(self, credential_url):
        with pytest.raises(GitCloneError, match="Embedded credentials"):
            validate_github_url(credential_url)

    @pytest.mark.parametrize(
        "query_or_fragment",
        [
            "https://github.com/owner/repo?branch=main",
            "https://github.com/owner/repo#readme",
            "https://github.com/owner/repo?key=val#frag",
        ],
    )
    def test_reject_query_and_fragment(self, query_or_fragment):
        with pytest.raises(GitCloneError, match="Query parameters|URL fragments"):
            validate_github_url(query_or_fragment)

    @pytest.mark.parametrize(
        "path_traversal",
        [
            "https://github.com/owner/..",
            "https://github.com/../repo",
            "https://github.com/owner/repo/../other",
            "https://github.com/owner",
            "https://github.com/owner/repo/pull/123",
            "https://github.com/owner/repo/blob/main/foo",
        ],
    )
    def test_reject_path_traversal_and_extra_segments(self, path_traversal):
        with pytest.raises(GitCloneError):
            validate_github_url(path_traversal)

    @pytest.mark.parametrize(
        "injection_url",
        [
            "https://github.com/owner/repo; rm -rf /",
            "https://github.com/owner/repo | whoami",
            "https://github.com/owner/repo$(id)",
            "https://github.com/owner/`cat /etc/passwd`",
            "https://github.com/owner/repo\nnewline",
            "https://github.com/owner/repo\0nullbyte",
        ],
    )
    def test_reject_command_injection(self, injection_url):
        with pytest.raises(GitCloneError):
            validate_github_url(injection_url)

    @pytest.mark.parametrize(
        "empty_input",
        [
            "",
            "   ",
            None,
        ],
    )
    def test_reject_empty_input(self, empty_input):
        with pytest.raises(GitCloneError, match="GitHub repository URL cannot be empty"):
            validate_github_url(empty_input)


class TestSafeGitCloner:
    """Unit tests for SafeGitCloner resource boundaries and execution safety."""

    def test_clone_success_with_mock(self, tmp_path: Path):
        dest_dir = tmp_path / "cloned_repo"
        cloner = SafeGitCloner()

        def fake_run(cmd, capture_output, text, timeout, env, check):
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "README.md").write_text("# Hello World")
            (dest_dir / "main.py").write_text("print('hello')")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            result = cloner.clone("https://github.com/pallets/flask", dest_dir)

            assert result == dest_dir.resolve()
            assert (dest_dir / "README.md").exists()
            assert mock_run.called
            call_cmd = mock_run.call_args[0][0]
            assert call_cmd[0] == "git"
            assert call_cmd[1] == "clone"
            assert "--depth" in call_cmd
            assert "--single-branch" in call_cmd
            assert "https://github.com/pallets/flask" in call_cmd
            call_env = mock_run.call_args[1]["env"]
            assert call_env["GIT_TERMINAL_PROMPT"] == "0"
            assert call_env["GIT_ASKPASS"] == "echo"

    def test_destination_already_exists_and_not_empty(self, tmp_path: Path):
        dest_dir = tmp_path / "existing_repo"
        dest_dir.mkdir()
        (dest_dir / "file.txt").write_text("existing content")

        cloner = SafeGitCloner()
        with pytest.raises(GitCloneError, match="already exists and is not empty"):
            cloner.clone("https://github.com/pallets/flask", dest_dir)

    def test_clone_nonzero_exit_cleans_up(self, tmp_path: Path):
        dest_dir = tmp_path / "failed_repo"
        cloner = SafeGitCloner()

        def fake_run(cmd, capture_output, text, timeout, env, check):
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "partial.tmp").write_text("partial")
            return subprocess.CompletedProcess(
                args=cmd, returncode=128, stdout="", stderr="fatal: repository not found"
            )

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(GitCloneError, match="fatal: repository not found"):
                cloner.clone("https://github.com/pallets/flask", dest_dir)

        assert not dest_dir.exists()

    def test_clone_timeout_cleans_up(self, tmp_path: Path):
        dest_dir = tmp_path / "timeout_repo"
        cloner = SafeGitCloner(config=GitCloneConfig(clone_timeout_seconds=5))

        def fake_run(cmd, capture_output, text, timeout, env, check):
            dest_dir.mkdir(parents=True, exist_ok=True)
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(GitCloneError, match="timed out after 5 seconds"):
                cloner.clone("https://github.com/pallets/flask", dest_dir)

        assert not dest_dir.exists()

    def test_clone_size_limit_exceeded(self, tmp_path: Path):
        dest_dir = tmp_path / "large_repo"
        # 1 KB limit
        cloner = SafeGitCloner(config=GitCloneConfig(max_clone_size_bytes=1024))

        def fake_run(cmd, capture_output, text, timeout, env, check):
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "large_file.dat").write_bytes(b"X" * 2048)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(GitCloneError, match="exceeds limit"):
                cloner.clone("https://github.com/pallets/flask", dest_dir)

        assert not dest_dir.exists()

    def test_clone_file_count_limit_exceeded(self, tmp_path: Path):
        dest_dir = tmp_path / "many_files_repo"
        cloner = SafeGitCloner(config=GitCloneConfig(max_file_count=3))

        def fake_run(cmd, capture_output, text, timeout, env, check):
            dest_dir.mkdir(parents=True, exist_ok=True)
            for i in range(5):
                (dest_dir / f"file_{i}.txt").write_text("content")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(GitCloneError, match="file count .* exceeds limit"):
                cloner.clone("https://github.com/pallets/flask", dest_dir)

        assert not dest_dir.exists()

    def test_clone_symlink_escape_rejected(self, tmp_path: Path):
        dest_dir = tmp_path / "symlink_repo"
        outside_target = tmp_path / "sensitive.txt"
        outside_target.write_text("secret")

        cloner = SafeGitCloner()

        def fake_run(cmd, capture_output, text, timeout, env, check):
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "file.py").write_text("print(1)")
            symlink_path = dest_dir / "bad_symlink"
            try:
                symlink_path.symlink_to(outside_target)
            except OSError:
                pytest.skip("Symlink creation not supported in current environment")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(GitCloneError, match="points outside the repository workspace"):
                cloner.clone("https://github.com/pallets/flask", dest_dir)

        assert not dest_dir.exists()
