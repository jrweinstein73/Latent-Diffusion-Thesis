#!/usr/bin/env bash
# Downloads the two checkpoints the thesis uses into <cosmos repo>/checkpoints/.
# Run from anywhere:  bash thesis/download_checkpoints.sh
set -euo pipefail
cd "$(dirname "$0")/.."            # repo root

BUCKET="s3://cosmos-latent-diffusion/checkpoints"
FILES=(
  "autoencoder-num_latents=16-wikipedia-final-128/100000.pth"
  "diffusion-rocstories-16-d=5-final/180000.pth"
)

for f in "${FILES[@]}"; do
  mkdir -p "checkpoints/$(dirname "$f")"
  if [ -s "checkpoints/$f" ]; then echo "already have $f"; continue; fi
  echo "downloading $f"
  # Try anonymous access first; if the bucket needs credentials, fall back
  # to whatever `aws configure` set up.
  aws s3 cp "$BUCKET/$f" "checkpoints/$f" --region eu-north-1 --no-sign-request \
    || aws s3 cp "$BUCKET/$f" "checkpoints/$f" --region eu-north-1
done
ls -lh checkpoints/*/*.pth
