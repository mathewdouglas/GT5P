"""Measure coherent brightness changes in a static patch of RSX_CAP frames.

Example: temporal_luma.py scratch/pv/cap_run --roi 100,800,400,150
Requires Pillow. Use a patch with no moving geometry, camera cuts or UI;
pixel motion and ordinary scene changes otherwise invalidate the comparison.
"""
import argparse
import json
import statistics
from pathlib import Path

from PIL import Image, ImageStat

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("capture", type=Path)
parser.add_argument("--roi", required=True, help="left,top,width,height in pixels")
parser.add_argument("--image", default="backbuffer.bmp")
args = parser.parse_args()
try:
    x, y, w, h = map(int, args.roi.split(","))
except ValueError:
    parser.error("--roi must contain four integers")
if min(x, y) < 0 or min(w, h) <= 0:
    parser.error("--roi needs a nonnegative origin and positive size")
files = sorted(args.capture.glob("frame_*/" + args.image),
               key=lambda p: int(p.parent.name.removeprefix("frame_")))
if len(files) < 2:
    parser.error("at least two captured images are required")
means = []
for path in files:
    with Image.open(path) as image:
        if x + w > image.width or y + h > image.height:
            parser.error("--roi exceeds image bounds: " + str(path))
        means.append(ImageStat.Stat(image.convert("RGB").crop((x, y, x+w, y+h))).mean)
channels = list(zip(*means))
print(json.dumps({
    "capture": str(args.capture), "frames": len(files), "roi": [x, y, w, h],
    "units": "8-bit RGB code values; statistics of spatial means across frames",
    "temporal_std_rgb": [statistics.pstdev(c) for c in channels],
    "temporal_range_rgb": [max(c) - min(c) for c in channels],
    "frame_means_rgb": means,
}, indent=2))
