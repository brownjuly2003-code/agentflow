#!/usr/bin/env bash
# Build voice-over MP4 from demo.cast + demo_voiced.narration.txt
#
# Prereqs:
#   pip install edge-tts
#   ffmpeg in PATH
#   agg binary (https://github.com/asciinema/agg/releases)
#
# Usage: bash demo_voiced.build.sh [path-to-agg]
#
# Inputs (same directory as this script):
#   demo.cast                    — asciinema cast recorded against the live cluster
#   demo_voiced.narration.txt    — Russian voice-over script
#
# Output:
#   demo_voiced.mp4              — final video with synced narration
#
# Intermediates (overwritten on each run, safe to delete):
#   .demo.gif  .demo_native.mp4  .demo_voiced.narration.mp3

set -euo pipefail
cd "$(dirname "$0")"

AGG="${1:-agg}"
VOICE="ru-RU-SvetlanaNeural"
RATE="+25%"

echo "[1/4] TTS narration via edge-tts ($VOICE rate=$RATE)..."
edge-tts --voice "$VOICE" --rate="$RATE" \
  --file demo_voiced.narration.txt \
  --write-media .demo_voiced.narration.mp3
NARR_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 .demo_voiced.narration.mp3)
echo "    narration duration: ${NARR_DUR}s"

echo "[2/4] Render demo.cast -> .demo.gif via agg..."
"$AGG" --speed 1.0 --font-size 18 --theme monokai demo.cast .demo.gif

echo "[3/4] Convert .demo.gif -> .demo_native.mp4..."
ffmpeg -y -i .demo.gif -movflags +faststart -pix_fmt yuv420p \
  -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" .demo_native.mp4 2>/dev/null
NATIVE_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 .demo_native.mp4)
echo "    cast duration: ${NATIVE_DUR}s"

echo "[4/4] Stretch video to narration length and mux audio..."
PTS=$(python -c "print($NARR_DUR / $NATIVE_DUR)")
echo "    setpts factor: $PTS"
ffmpeg -y -i .demo_native.mp4 -i .demo_voiced.narration.mp3 \
  -filter_complex "[0:v]setpts=${PTS}*PTS,fps=20[v]" \
  -map "[v]" -map 1:a \
  -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -shortest \
  demo_voiced.mp4 2>/dev/null

FINAL_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 demo_voiced.mp4)
FINAL_SIZE=$(stat -c '%s' demo_voiced.mp4 2>/dev/null || stat -f '%z' demo_voiced.mp4)
echo
echo "OK demo_voiced.mp4 — ${FINAL_DUR}s, ${FINAL_SIZE} bytes"
