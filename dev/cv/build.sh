#!/usr/bin/env bash
# neilkale_cv.tex -> static/cv.pdf
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
OUT="$ROOT/tmp/cv"
mkdir -p "$OUT"

pdflatex -interaction=nonstopmode -halt-on-error -output-directory "$OUT" neilkale_cv.tex > "$OUT/pdflatex.log" 2>&1 \
  || { tail -30 "$OUT/pdflatex.log"; exit 1; }
cp "$OUT/neilkale_cv.pdf" "$ROOT/static/cv.pdf"
echo "wrote static/cv.pdf"
