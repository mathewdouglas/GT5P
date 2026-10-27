"""Return Gran Turismo 5's game data to its first-boot install state.

Keeps only the update package's PDIPFS files (scratch/rpcs3/pkg_files.txt),
and removes the install marker, the bdmark tree and dev_hdd1 (system cache,
page files, database). --save also removes the save data, which GT5
recreates on its next first boot. Run by scripts/test/gt5boot.ps1 -Fresh.
"""
import os
import shutil
import sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
game = os.path.join(root, "gamedata", "dev_hdd0", "game", "BCUS98114")
usrdir = os.path.join(game, "USRDIR")
keep = set(l.strip().replace("/", os.sep)
           for l in open(os.path.join(root, "scratch", "rpcs3", "pkg_files.txt")) if "PDIPFS" in l)
removed = 0
for dp, _, fn in os.walk(os.path.join(usrdir, "PDIPFS")):
    for f in fn:
        if os.path.relpath(os.path.join(dp, f), game) not in keep:
            os.remove(os.path.join(dp, f))
            removed += 1
for d in (os.path.join(usrdir, "PDIPFS_bdmark"), os.path.join(usrdir, "grim2"), os.path.join(usrdir, "db"),
          os.path.join(root, "gamedata", "dev_hdd1")):
    if os.path.isdir(d):
        shutil.rmtree(d)
for f in (os.path.join(usrdir, "installed00.dat"), os.path.join(root, "gamedata", "dev_hdd1.id")):
    if os.path.exists(f):
        os.remove(f)
if "--save" in sys.argv:
    sd = os.path.join(root, "gamedata", "dev_hdd0", "home", "00000001", "savedata", "BCUS98114-GAME")
    if os.path.isdir(sd):
        shutil.rmtree(sd)
print("removed", removed, "installed files; first-boot state" + (" (save removed)" if "--save" in sys.argv else ""))
