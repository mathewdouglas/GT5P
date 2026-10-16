#!/usr/bin/env python3
"""Refuse game files in the repository.

Nothing from the game may be committed: no executables, packages, volumes,
movies, licences, keys, decrypted or generated code. .gitignore keeps them out
of `git add .`, but an ignore rule does nothing against `git add -f`, a renamed
file, or a new kind of file nobody listed. This checks the content itself.

    python scripts/check_no_game_files.py --staged     # what is about to be committed
    python scripts/check_no_game_files.py --tracked    # every file in HEAD
    python scripts/check_no_game_files.py --history    # every blob in every commit

Exit status is 1 if anything is refused. The pre-commit hook in .githooks/ runs
--staged; CI runs --tracked and --history.

A file is refused if any of these holds:
  * its name or extension is a known game-file kind;
  * it sits under a directory reserved for game-derived data;
  * it starts with the magic bytes of a PS3 container or executable;
  * it is larger than MAX_BYTES, or is binary and larger than MAX_BINARY_BYTES.
"""
import subprocess
import sys

MAX_BYTES = 1_000_000          # largest legitimate file today is ~160 KB of text
MAX_BINARY_BYTES = 64_000      # no binary file belongs here at all, bar a small image
# The ps3recomp local-changes patch (patches/*.patch) is our own source diff and
# passed 1 MB in Phase 60. Text diffs there get a larger limit; anything else
# keeps MAX_BYTES.
MAX_PATCH_BYTES = 4_000_000

# Lower-cased. Extensions of game data, licences, keys, and analysis databases.
EXTENSIONS = {
    ".elf", ".self", ".sprx", ".prx", ".bin", ".pkg", ".rap", ".rif", ".edat", ".sdat",
    ".vol", ".dat", ".pam", ".esp", ".sfo", ".sfb", ".p3t", ".at3", ".gpb", ".rt2",
    ".iso", ".img", ".zip", ".rar", ".7z",
    ".gzf", ".gpr", ".rep", ".i64", ".idb",          # Ghidra / IDA databases
}
NAMES = {"eboot.bin", "emain.self", "gt.vol", "tv.dat", "gamedata.esp", "param.sfo",
         "ps3_disc.sfb", "act.dat", "keys", "ldr_curves", "vsh_curves", "klics.txt",
         "icon0.png", "icon1.pam", "pic0.png", "pic1.png", "pic2.png", "snd0.at3", "ps3logo.dat"}
DIRECTORIES = ("input/", "generated/", "analysis/", "gamedata/", "savedata/", "scratch/",
               "build/", "data/keys", "pdipfs/", "ps3_game/", "usrdir/")
MAGIC = {
    b"\x7fELF": "ELF executable",
    b"SCE\x00": "SELF / signed PS3 container",
    b"\x7fPKG": "PS3 package",
    b"\x00PSF": "PARAM.SFO",
    b"NPD\x00": "NPDRM (EDAT/SDAT) container",
    b".SFB": "disc SFB",
    b"PAMF": "PAMF movie",
    b"\xac\xbc\xba\xff": "bit-inverted SELF (GAMEDATA.ESP)",
}


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def verdict(path, size, head):
    """Why this file is refused, or None."""
    low = path.lower().replace("\\", "/")
    base = low.rsplit("/", 1)[-1]
    if base in NAMES:
        return "game file name"
    dot = base.rfind(".")
    if dot >= 0 and base[dot:] in EXTENSIONS:
        return "game file extension " + base[dot:]
    for d in DIRECTORIES:
        if low.startswith(d) or ("/" + d) in ("/" + low):
            return "under " + d
    for magic, what in MAGIC.items():
        if head.startswith(magic):
            return what
    is_patch = (low.startswith("patches/") and low.endswith(".patch")
                and head.startswith(b"diff --git") and b"\x00" not in head)
    limit = MAX_PATCH_BYTES if is_patch else MAX_BYTES
    if size > limit:
        return "larger than %d bytes" % limit
    if b"\x00" in head and size > MAX_BINARY_BYTES:
        return "binary and larger than %d bytes" % MAX_BINARY_BYTES
    return None


def blob_info(spec):
    size = int(git("cat-file", "-s", spec))
    head = subprocess.run(["git", "cat-file", "blob", spec], capture_output=True).stdout[:4096]
    return size, head


def staged():
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode("utf-8", "replace")
    for path in filter(None, out.split("\0")):
        yield path, ":" + path


def tracked():
    out = git("ls-files", "-z").decode("utf-8", "replace")
    for path in filter(None, out.split("\0")):
        yield path, "HEAD:" + path


def history():
    seen = set()
    out = git("rev-list", "--objects", "--all").decode("utf-8", "replace")
    for line in out.splitlines():
        sha, _, path = line.partition(" ")
        if not path or sha in seen:
            continue
        seen.add(sha)
        if git("cat-file", "-t", sha).strip() == b"blob":
            yield path, sha


def main():
    modes = {"--staged": staged, "--tracked": tracked, "--history": history}
    chosen = [m for m in sys.argv[1:] if m in modes] or ["--staged"]
    bad = 0
    for mode in chosen:
        n = 0
        for path, spec in modes[mode]():
            n += 1
            try:
                size, head = blob_info(spec)
            except subprocess.CalledProcessError:
                continue                      # deleted, or a submodule entry
            why = verdict(path, size, head)
            if why:
                bad += 1
                print("REFUSED  %s  (%s, %d bytes)" % (path, why, size))
        print("%s: %d file(s) checked" % (mode.lstrip("-"), n))
    if bad:
        print("\n%d file(s) refused. Game files, keys and generated code must not be "
              "committed.\nSee scripts/check_no_game_files.py for the rules." % bad)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
