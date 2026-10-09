import os
import fnmatch
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set, Optional
from codebase_ai.config import (
    DEFAULT_IGNORE_DIRS,
    DEFAULT_IGNORE_FILES,
    DEFAULT_IGNORE_EXTENSIONS,
    DEFAULT_ALLOWED_EXTENSIONS,
)

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".xml": "xml",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".csv": "csv",
    ".tsv": "csv",
    ".pkl": "pickle",
    ".pickle": "pickle",
    ".md": "markdown",
    ".txt": "plaintext",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
}


@dataclass
class CodeFile:
    file_path: str        # Relative path (e.g., "backend/auth.py")
    absolute_path: Path
    extension: str
    language: str
    content: str


class RepoScanner:
    """Scans a local repository or clones and scans a GitHub repository URL."""

    def __init__(
        self,
        allowed_extensions: Optional[Set[str]] = None,
        ignore_dirs: Optional[Set[str]] = None,
        ignore_files: Optional[Set[str]] = None,
        ignore_extensions: Optional[Set[str]] = None,
    ):
        self.allowed_extensions = allowed_extensions or DEFAULT_ALLOWED_EXTENSIONS
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS
        self.ignore_files = ignore_files or DEFAULT_IGNORE_FILES
        self.ignore_extensions = ignore_extensions or DEFAULT_IGNORE_EXTENSIONS

    def _safe_remove_dir(self, dir_path: Path):
        if not dir_path.exists():
            return
        import stat
        try:
            for root, dirs, files in os.walk(dir_path, topdown=False):
                for file in files:
                    p = os.path.join(root, file)
                    try:
                        os.chmod(p, stat.S_IWRITE)
                        os.remove(p)
                    except Exception:
                        pass
                for d in dirs:
                    p = os.path.join(root, d)
                    try:
                        os.chmod(p, stat.S_IWRITE)
                        os.rmdir(p)
                    except Exception:
                        pass
            os.chmod(dir_path, stat.S_IWRITE)
            shutil.rmtree(dir_path, ignore_errors=True)
        except Exception:
            pass

    def _is_valid_repo_dir(self, target_dir: Path) -> bool:
        if not target_dir.exists() or not target_dir.is_dir():
            return False
        # Check if there is at least one non-ignored code file
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs and not d.startswith(".")]
            for file in files:
                if file in self.ignore_files or file.startswith("."):
                    continue
                ext = Path(file).suffix.lower()
                if self.ignore_extensions and ext in self.ignore_extensions:
                    continue
                if self.allowed_extensions is None or ext in self.allowed_extensions:
                    return True
        return False



    def resolve_repo_path(self, repo_path_or_url: str | Path) -> Path:
        raw_str = str(repo_path_or_url).strip()
        if not raw_str:
            return Path("./").resolve()

        is_git_url = (
            raw_str.startswith("http://")
            or raw_str.startswith("https://")
            or raw_str.startswith("git@")
            or raw_str.endswith(".git")
            or "github.com/" in raw_str
        )

        if is_git_url:
            clean_url = raw_str.rstrip(" /\t\n\r")
            if not (clean_url.startswith("http://") or clean_url.startswith("https://") or clean_url.startswith("git@")):
                git_fetch_url = f"https://{clean_url}"
            else:
                git_fetch_url = clean_url

            raw_folder_name = git_fetch_url.rstrip("/").split("/")[-1]
            if raw_folder_name.endswith(".git"):
                raw_folder_name = raw_folder_name[:-4]
            clean_name = raw_folder_name.strip(" .") or "repository"

            target_dir = Path("cloned_repos") / clean_name
            target_dir.parent.mkdir(parents=True, exist_ok=True)

            if self._is_valid_repo_dir(target_dir):
                return target_dir.resolve()

            if target_dir.exists():
                self._safe_remove_dir(target_dir)

            # Clone repository using shallow git clone
            clone_urls = [git_fetch_url]
            if not git_fetch_url.endswith(".git"):
                clone_urls.append(f"{git_fetch_url}.git")

            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GIT_ASKPASS"] = ""
            env["GIT_LFS_SKIP_SMUDGE"] = "1"

            last_error = ""
            for url in clone_urls:
                if target_dir.exists():
                    self._safe_remove_dir(target_dir)
                try:
                    res = subprocess.run(
                        ["git", "clone", "--depth", "1", url, str(target_dir)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=env,
                        timeout=30,
                    )
                    if res.returncode == 0 and self._is_valid_repo_dir(target_dir):
                        return target_dir.resolve()
                    err_msg = res.stderr.strip() or res.stdout.strip()
                    last_error = f"URL '{url}': {err_msg}"
                    if target_dir.exists():
                        self._safe_remove_dir(target_dir)
                except Exception as ex:
                    last_error = f"URL '{url}': {str(ex)}"
                    if target_dir.exists():
                        self._safe_remove_dir(target_dir)

            raise ValueError(f"Could not clone repository '{raw_str}'. Details: {last_error or 'Unknown error'}")

        local_path = Path(raw_str).resolve()
        if not local_path.exists():
            raise ValueError(f"Repository path '{raw_str}' does not exist.")
        return local_path



    def _parse_gitignore(self, repo_dir: Path) -> List[str]:
        gitignore_path = repo_dir / ".gitignore"
        patterns = []
        if gitignore_path.is_file():
            try:
                with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception:
                pass
        return patterns

    def _is_ignored_by_gitignore(self, rel_path_str: str, patterns: List[str]) -> bool:
        normalized_path = rel_path_str.replace("\\", "/")
        parts = normalized_path.split("/")
        
        for pattern in patterns:
            pattern = pattern.rstrip("/")
            if fnmatch.fnmatch(normalized_path, pattern) or fnmatch.fnmatch(normalized_path, f"*/{pattern}"):
                return True
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    def scan_directory(self, repo_dir: str | Path) -> List[CodeFile]:
        repo_path = self.resolve_repo_path(repo_dir)
        if not repo_path.exists() or not repo_path.is_dir():
            raise ValueError(f"Invalid repository directory: {repo_dir}")

        gitignore_patterns = self._parse_gitignore(repo_path)
        code_files: List[CodeFile] = []

        for root, dirs, files in os.walk(repo_path):
            # Exclude ignored directories in-place to prevent os.walk from recursing into them
            dirs[:] = [
                d for d in dirs
                if d not in self.ignore_dirs and not d.startswith(".")
            ]

            rel_root = Path(root).relative_to(repo_path)

            for file in files:
                if file in self.ignore_files or file.startswith("."):
                    continue

                ext = Path(file).suffix.lower()
                if self.ignore_extensions and ext in self.ignore_extensions:
                    continue

                if self.allowed_extensions is not None and ext not in self.allowed_extensions:
                    continue

                file_abs = Path(root) / file
                rel_path = file_abs.relative_to(repo_path)
                rel_path_str = str(rel_path)

                if self._is_ignored_by_gitignore(rel_path_str, gitignore_patterns):
                    continue

                try:
                    with open(file_abs, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    # Skip empty files
                    if not content.strip():
                        continue

                    language = EXTENSION_TO_LANGUAGE.get(ext, ext.lstrip(".") if ext else "plaintext")

                    code_files.append(
                        CodeFile(
                            file_path=rel_path_str.replace("\\", "/"),
                            absolute_path=file_abs,
                            extension=ext,
                            language=language,
                            content=content,
                        )
                    )
                except Exception as e:
                    # Non-readable / binary file fallback
                    continue

        return code_files
