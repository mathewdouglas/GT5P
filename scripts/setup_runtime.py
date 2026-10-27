"""Prepare the pinned upstream runtime plus this branch's GT5P compatibility patch.

Never resets, stashes or overwrites an existing dirty checkout. The legacy
shared runtime is left alone. PS3RECOMP_DIR or --path overrides the destination.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(path, *args, check=True):
    return subprocess.run(["git", "-C", str(path), *args], check=check,
                          capture_output=True, text=True)


def main():
    manifest = json.loads((ROOT / "config/ps3recomp.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path(os.environ.get(
        "PS3RECOMP_DIR", ROOT.parent / manifest["directory"])))
    parser.add_argument("--check", action="store_true", help="verify only; do not fetch or apply")
    args = parser.parse_args()
    path = args.path.resolve()
    patch = ROOT / manifest["patch"]
    if not patch.is_file():
        raise SystemExit(f"Compatibility patch missing: {patch}")
    if not path.exists():
        if args.check:
            raise SystemExit(f"Runtime missing: {path}; run this script without --check")
        subprocess.run(["git", "clone", manifest["repository"], str(path)], check=True)
    if git(path, "rev-parse", "--git-dir", check=False).returncode:
        raise SystemExit(f"Not a Git checkout: {path}")
    top = Path(git(path, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if top != path or path == ROOT:
        raise SystemExit(f"Destination must be a separate runtime checkout: {path}")
    head = git(path, "rev-parse", "HEAD", check=False).stdout.strip()
    if head == manifest["commit"] and not git(path, "apply", "--reverse", "--check", str(patch), check=False).returncode:
        print(f"{manifest['version']} + GT5P compatibility patch present: {path}")
        return
    if args.check:
        raise SystemExit("Runtime baseline or compatibility patch does not match this GT5P branch")
    if git(path, "status", "--porcelain").stdout:
        raise SystemExit(f"Refusing to change a dirty runtime: {path}")
    git(path, "fetch", "origin", manifest["commit"])
    git(path, "checkout", "--detach", manifest["commit"])
    git(path, "apply", "--check", str(patch))
    git(path, "apply", str(patch))
    print(f"Prepared {manifest['version']} + GT5P compatibility patch: {path}")


if __name__ == "__main__":
    main()
