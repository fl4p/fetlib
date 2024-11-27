
for f in docs/power-loss/img/*.png; do cwebp "$f" -q 70 -o "${f%.png}.webp"  && rm $f; done