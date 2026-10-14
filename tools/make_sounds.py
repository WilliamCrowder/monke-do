"""Turn the two voice lines into the addon's sound files.

    uv run python tools/make_sounds.py <"OK, monke do" recording> <"Monke don't" recording>

Any format ffmpeg reads (ElevenLabs gives mp3). Each file is trimmed of silence at both ends,
made mono, brought to the same loudness so neither line is louder than the other or than the
game's own UI sounds, and written as Ogg Vorbis, which PlaySoundFile plays:
addon/MonkeDo/Media/monke_do.ogg and monke_dont.ogg. Needs ffmpeg on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

MEDIA = Path(__file__).resolve().parent.parent / "addon" / "MonkeDo" / "Media"
OUTPUTS = ("monke_do.ogg", "monke_dont.ogg")
MAX_SECONDS = 2.5  # a reply to a click; longer gets in the way

# Silence off the front, then reverse and do the same for the end; loudness to -16 LUFS with
# 1.5 dB of headroom, about where WoW's interface sounds sit.
FILTER = (
    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03,"
    "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
    "loudnorm=I=-16:TP=-1.5:LRA=7"
)


def convert(source: Path, target: Path) -> float:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-af", FILTER, "-ac", "1", "-ar", "44100", "-c:a", "libvorbis", "-q:a", "5", str(target)],
        check=True,
    )
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(target)],
        check=True, capture_output=True, text=True,
    )
    return float(probe.stdout.strip())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    if not shutil.which("ffmpeg"):
        print("ffmpeg is not on PATH")
        return 1
    for source, name in zip(map(Path, argv), OUTPUTS):
        seconds = convert(source, MEDIA / name)
        note = f"  (long for a click reply; aim under {MAX_SECONDS}s)" if seconds > MAX_SECONDS else ""
        print(f"{name}: {seconds:.2f}s -> {MEDIA / name}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
