#!/bin/sh
# Cross-compile detect for the Pi. Run on the Mac. Needs Docker and the SDP.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cp "$ROOT/detect.cpp" "$HOME/qnxprojects/qnx_workspace/detect.cpp"
docker run --platform linux/amd64 --rm \
  -v "$HOME/qnxprojects/qnx_workspace:/work" \
  -v "$HOME/qnx800:/opt/qnx800:ro" \
  -v "$HOME/.qnx:/root/.qnx" \
  -w /work \
  qnx-tflite-env \
  bash -lc '. /opt/qnx800/qnxsdp-env.sh && qcc -Vgcc_ntoaarch64le -lang-c++ -O2 -o detect detect.cpp -I$QNX_TARGET/usr/local/include/tensorflow -L$QNX_TARGET/aarch64le/usr/local/lib -L$QNX_TARGET/aarch64le/usr/lib -L$QNX_TARGET/aarch64le/lib -ltensorflow-lite -lcamapi -ljpeg -lsocket'
cp "$HOME/qnxprojects/qnx_workspace/detect" "$ROOT/detect"
echo "built $ROOT/detect"
