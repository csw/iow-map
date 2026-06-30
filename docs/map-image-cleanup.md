# Map Image Cleanup

JPEG artifacts in the source map scans are reduced using
[waifu2x-ncnn-vulkan](https://github.com/nihui/waifu2x-ncnn-vulkan), a neural-network
denoiser that works well on illustration/game-art style images.

Cleaned images live in `maps/cleanup/` and are what the app serves.

## Command

```bash
WAIFU=~/tools/waifu2x/waifu2x-ncnn-vulkan-20220728-macos/waifu2x-ncnn-vulkan
MODELS=~/tools/waifu2x/waifu2x-ncnn-vulkan-20220728-macos/models-cunet

# Denoise only (no upscale). -n 2 = medium denoise; try -n 1 if lines suffer.
$WAIFU -i maps/input.jpg -o /tmp/denoised.png -n 2 -s 1 -m "$MODELS"

# Convert PNG output to high-quality JPEG
python3 -c "
import cv2
img = cv2.imread('/tmp/denoised.png')
cv2.imwrite('maps/cleanup/input.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 92])
"
```

## Installation

```bash
curl -L -o /tmp/waifu2x.zip \
  "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20220728/waifu2x-ncnn-vulkan-20220728-macos.zip"
mkdir -p ~/tools/waifu2x
unzip /tmp/waifu2x.zip -d ~/tools/waifu2x
```

## Parameters

- `-n 2` — denoise level (0–3). Level 2 works well for these maps. Use 3 for heavier
  artifacts, 1 if fine lines are being softened.
- `-s 1` — scale factor 1 (denoise only, no upscale).
- `-m models-cunet` — best-quality model, suited for illustration/game art.
