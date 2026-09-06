# sketch_correction

Turns phone photos of sketchbook pages into flat, square, colour-matched images for the
`/scrapbook` gallery. One script, no project state: everything it produces lands in `tmp/`
(gitignored). You copy the finished files into `static/scrapbook/` and add YAML entries
yourself once the previews look right.

## Setup (once per machine)

```bash
sudo apt-get install -y python3-pip libheif-examples
pip3 install --break-system-packages pillow pillow-heif opencv-python-headless numpy
```

## Workflow

1. Drop the phone photos (HEIC is fine) into `tmp/sketches/originals/`.
2. Run:

   ```bash
   python3 dev/sketch_correction/correct_sketches.py \
       --in tmp/sketches/originals \
       --work tmp/sketches/work \
       --out tmp/sketches/out \
       --refs static/scrapbook
   ```

   Add `--spine-bottom IMG_1234` for any photo where the book was opened vertically
   (spine below the drawing, rounded corners on top). Use `--only IMG_1234 IMG_1235`
   to reprocess a subset.

3. Review `tmp/sketches/work/`:
   - `grid_old_and_new.png` — existing gallery images first, then the new ones, so you
     can check tone and alignment side by side.
   - `<name>_before_after.png` — one per photo.
   - `<name>_edges.jpg` — the traced page edges (red top, green bottom, blue left/spine,
     yellow right) on the working frame. If a line is off, that's where the crop went wrong.
4. Copy the good ones with a descriptive name and append entries to `data/scrapbook.yaml`:

   ```bash
   cp tmp/sketches/out/IMG_1234.jpg static/scrapbook/some_cafe.jpeg
   ```

   ```yaml
   - image: /scrapbook/some_cafe.jpeg
     alt: "Some Cafe"
     note: "Neighborhood, City, ST"
     variant: float        # tilt-left | tilt-right | float | tall | wide
     enabled: true
   ```

## Manual borders (when auto detection is off)

```bash
python3 dev/sketch_correction/annotate.py --in tmp/sketches/originals \
    --work tmp/sketches/work --out tmp/sketches/out          # http://localhost:8766/
```

Pick a photo, trace the paper's edge with the pencil in one loop (follow the rounded corners as
they are), tick **pencil page** for graphite sketches (gentler colour: keeps the page's own tone,
no ink deepening), press **Submit**. The server splits your stroke into four edge curves, fits them,
Coons-warps the page, colour-matches it, and works out which corners are rounded by checking
where your stroke cuts inside the virtual corner. The result appears on the right; re-trace and
resubmit until it looks right. Strokes are saved to `tmp/sketches/work/annotations.json`, and
`correct_sketches.py --corners tmp/sketches/work/annotations.json` replays them in a batch run
(photos without an annotation still go through auto detection).

## How it works

| Step | What | Where in the script |
|------|------|---------------------|
| Detect | Largest bright, low-saturation blob; four hull extremes become a rough quad | `find_page` |
| Refine | Warp to a square, cut off the white facing page / dark spine seam / cover on the spine and bottom sides, map the corrected corners back through the homography (3 passes) | `refine_quad`, `facing_fracs`, `find_cut` |
| Dewarp | Trace the four actual page edges (brightness for the three outer edges, warmth vs. the facing page for the spine edge), fit robust quadratic curves (two passes: trace, recentre the frame on the found corners, trace again), remap the bowed page onto a true square with a Coons patch | `trace_edges`, `coons_maps`, `dewarp` |
| Colour | Flatten lighting, white-balance bare paper to `TARGET_PAPER`, deepen ink, inpaint the rounded corners. `--pencil` / the annotator's checkbox switches to a gentle mode for graphite pages | `color_match`, `fill_corners` |

Assumptions baked in: pages are square-ish, the spine is on the left (or rotated there via
`--spine-bottom`), paper is cream, and the background is darker than the page.

## Known limits

- A white facing page that is lit to almost the same warmth as the sketch page can survive
  the spine-side cut (seen on a hand-held page shot with the book open vertically).
  Check `<name>_edges.jpg`; if the blue line does not follow the seam, use `annotate.py`.
- Heavy coloured pencil along a page edge can confuse the edge tracer for that edge.
- Bare paper is estimated from bright, low-saturation pixels, so pages that are almost
  entirely coloured may white-balance oddly. Adjust `TARGET_PAPER` if the tone drifts.
