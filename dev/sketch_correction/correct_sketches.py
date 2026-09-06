#!/usr/bin/env python3
"""
Turn phone photos of sketchbook pages into flat, square, colour-matched gallery images.

Pipeline per photo
  1. decode (HEIC/JPEG/PNG), honour EXIF rotation
  2. coarse page detection: largest bright, low-saturation blob -> 4 hull corners
  3. refine: perspective-warp, cut away the facing page / spine seam / cover on the
     inner (left) and bottom sides, map the corrected corners back through the homography
  4. dewarp: trace the four (curved) page edges, fit smooth polynomials, and remap the
     bowed page onto a true square with a Coons patch (rounded outer corners are
     extrapolated to sharp virtual corners)
  5. colour: flatten lighting, white-balance bare paper to TARGET_PAPER, deepen ink,
     inpaint the two rounded outer corners
  6. write <name>.jpg to --out, plus debug images and before/after previews to --work

Assumes the spine is on the LEFT of the page (rounded corners on the right). For pages shot
with the book opened vertically (spine below), list them under --spine-bottom.

Usage
  python3 dev/sketch_correction/correct_sketches.py \
      --in tmp/sketches/originals --work tmp/sketches/work --out tmp/sketches/out \
      --refs static/sketches

Nothing here writes into static/ or data/ - copy the finished files over and add the
YAML entries yourself once the previews look right.
"""
import argparse, glob, os, sys
import cv2, numpy as np
from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # HEIC input just won't decode
    pass

TARGET_PAPER = np.array([225, 205, 172], float)  # RGB of the cream paper in the existing gallery
OUT = 2048    # output side length
WARP = 3000   # working res for facing-page cuts
DW = 1500     # working res for edge tracing


# ---------------------------------------------------------------- geometry helpers
def inset_quad(quad, inset):
    c = quad.mean(0)
    return c + (quad - c) * (1 - inset)


def homography_to_square(quad, size):
    dst = np.array([[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]], np.float32)
    return cv2.getPerspectiveTransform(quad.astype(np.float32), dst)


# ---------------------------------------------------------------- 2. coarse page detection
def find_page(img):
    h, w = img.shape[:2]
    scale = 1000 / max(h, w)
    small = cv2.resize(img, None, fx=scale, fy=scale)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    mask = ((v > 0.6 * np.percentile(v, 97)) & (hsv[..., 1] < 90)).astype(np.uint8) * 255  # bright (relative) & low-sat
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    pts = cv2.convexHull(max(cnts, key=cv2.contourArea)).reshape(-1, 2).astype(float)
    s, d = pts.sum(1), pts[:, 0] - pts[:, 1]
    quad = np.array([pts[s.argmin()], pts[d.argmax()], pts[s.argmax()], pts[d.argmin()]])  # tl,tr,br,bl
    return quad / scale


# ---------------------------------------------------------------- 3. cut away facing page / seam
def facing_fracs(w):
    """Per-column and per-row fraction of pixels that are a white facing page (bright AND cool)
    or dark (seam / cover / laptop). The sketch page itself is bright AND warm."""
    b, g, r = [c.astype(np.float32) for c in cv2.split(w)]
    lum, yel = (r + g + b) / 3, r - b
    core = slice(int(WARP * .3), int(WARP * .7))
    pl = np.percentile(lum[core, core], 75)
    py = np.percentile(yel[core, core][lum[core, core] > pl - 25], 50)
    facing = (lum > pl - 45) & (yel < py * 0.72)
    dark = lum < pl * 0.55
    band = slice(int(WARP * .1), int(WARP * .9))
    return (facing[band, :].mean(0), dark[band, :].mean(0)), (facing[:, band].mean(1), dark[:, band].mean(1))


def find_cut(frac, from_end, lim_frac=0.3, thr=0.5, margin=10):
    n, lim = len(frac), int(len(frac) * lim_frac)
    idx = np.where(frac > thr)[0]
    idx = idx[idx >= n - lim] if from_end else idx[idx < lim]
    if len(idx) == 0:
        return n if from_end else 0
    return (int(idx.min()) - margin) if from_end else (int(idx.max()) + margin)


def refine_quad(img, quad):
    M = homography_to_square(quad, WARP)
    w = cv2.warpPerspective(img, M, (WARP, WARP), flags=cv2.INTER_LINEAR)
    (cf, cd), (rf, rd) = facing_fracs(w)
    x0 = max(find_cut(cf, False), find_cut(cd, False, thr=0.9))   # white page needs 50% of a column, a dark seam 90%
    y1 = min(find_cut(rf, True), find_cut(rd, True, thr=0.9))
    new_dst = np.array([[x0, 0], [WARP - 1, 0], [WARP - 1, y1], [x0, y1]], np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(new_dst, np.linalg.inv(M)).reshape(-1, 2), (x0, y1)


# ---------------------------------------------------------------- 4. curved-page dewarp
def robust_polyfit(x, y, deg=2, iters=4):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        raise ValueError("too few edge points to fit")
    deg = min(deg, len(x) - 1)
    keep = np.ones(len(x), bool)
    for _ in range(iters):
        p = np.polyfit(x[keep], y[keep], deg)
        r = y - np.polyval(p, x)
        new_keep = np.abs(r) < 3 * (np.median(np.abs(r[keep])) + 1e-6)
        if new_keep.sum() < deg + 2:
            break
        keep = new_keep
    return p


def trace_edges(w):
    """Fit top(x), bottom(x), left(y), right(y) polynomials to the page boundary, searching only a
    band near each side of the frame (the refined quad is already close).
    Top/right/bottom border on dark background -> brightness alone separates page from background.
    Left (spine side) may border a white facing page -> use warmth, calibrated against that page."""
    b, g, r = [c.astype(np.float32) for c in cv2.split(w)]
    lum, yel = (r + g + b) / 3, r - b
    lum = cv2.blur(lum, (15, 15)); yel = cv2.blur(yel, (15, 15))
    c = slice(int(DW * .3), int(DW * .7))
    pl = np.percentile(lum[c, c], 75)
    py = np.percentile(yel[c, c][lum[c, c] > pl - 25], 50)
    bright = (lum > 0.6 * pl).astype(np.uint8)
    band = int(DW * 0.15)
    lb_lum, lb_yel = lum[:, :band], yel[:, :band]           # spine-side band: may hold a white facing page
    cool = (lb_lum > 0.8 * pl) & (lb_yel < py - 4)
    if cool.mean() > 0.04:                                  # a white facing page is present
        fy = np.median(lb_yel[cool])
        left_mask = (bright & (yel > (py + fy) / 2)).astype(np.uint8)
    else:
        left_mask = bright
    xs = np.arange(int(DW * .05), int(DW * .95))

    def first_hit(sub, axis):
        return sub.argmax(axis=axis), sub.max(axis=axis) > 0

    t, ok = first_hit(bright[:band, :], 0);               top = (xs[ok[xs]], t[xs][ok[xs]])
    bb, ok = first_hit(bright[::-1][:band, :], 0);        bot = (xs[ok[xs]], DW - 1 - bb[xs][ok[xs]])
    l, ok = first_hit(left_mask[:, :band], 1);            left = (xs[ok[xs]], l[xs][ok[xs]])
    rr, ok = first_hit(bright[:, ::-1][:, :band], 1);     right = (xs[ok[xs]], DW - 1 - rr[xs][ok[xs]])
    fit = lambda e: robust_polyfit(e[0], e[1])
    return fit(top), fit(bot), fit(left), fit(right)


def corners_from_edges(pT, pB, pL, pR):
    """Virtual sharp corners: intersections of the fitted edge curves (fixed-point iteration)."""
    def corner(px_of_y, py_of_x, x0, y0):
        for _ in range(10):
            x0 = np.polyval(px_of_y, y0); y0 = np.polyval(py_of_x, x0)
        return x0, y0
    return (corner(pL, pT, 0, 0), corner(pR, pT, DW, 0), corner(pR, pB, DW, DW), corner(pL, pB, 0, DW))


def coons_maps(pT, pB, pL, pR, inset=0.006, spine_inset=0.014):
    """OUT x OUT grid of DW-space sample points following the four boundary curves (Coons patch).
    The spine side is trimmed a little more to lose the stitching."""
    u = np.linspace(spine_inset, 1 - inset, OUT)
    v = np.linspace(inset, 1 - inset, OUT)
    (xTL, yTL), (xTR, yTR), (xBR, yBR), (xBL, yBL) = corners_from_edges(pT, pB, pL, pR)
    xt = xTL + (xTR - xTL) * u; yt = np.polyval(pT, xt)
    xb = xBL + (xBR - xBL) * u; yb = np.polyval(pB, xb)
    yl = yTL + (yBL - yTL) * v; xl = np.polyval(pL, yl)
    yr = yTR + (yBR - yTR) * v; xr = np.polyval(pR, yr)
    U, V = np.meshgrid(u, v)
    T = np.stack([xt, yt], -1)[None]; B = np.stack([xb, yb], -1)[None]
    L = np.stack([xl, yl], -1)[:, None]; R = np.stack([xr, yr], -1)[:, None]
    P00, P10, P01, P11 = map(np.array, [(xTL, yTL), (xTR, yTR), (xBL, yBL), (xBR, yBR)])
    Uu, Vv = U[..., None], V[..., None]
    P = ((1 - Vv) * T + Vv * B + (1 - Uu) * L + Uu * R
         - ((1 - Uu) * (1 - Vv) * P00 + Uu * (1 - Vv) * P10 + (1 - Uu) * Vv * P01 + Uu * Vv * P11))
    return P.astype(np.float32)


def dewarp(img, quad, debug_path=None):
    """Two passes: trace edges in a generously expanded frame, recentre the frame on the virtual
    corners found, trace again with a tighter frame, then remap with a Coons patch."""
    for expand in (0.10, 0.05):
        q = inset_quad(quad, -expand)
        M = homography_to_square(q, DW)
        w = cv2.warpPerspective(img, M, (DW, DW), flags=cv2.INTER_AREA)
        pT, pB, pL, pR = trace_edges(w)
        c = np.array(corners_from_edges(pT, pB, pL, pR), np.float32).reshape(-1, 1, 2)   # tl,tr,br,bl in DW space
        quad = cv2.perspectiveTransform(c, np.linalg.inv(M)).reshape(-1, 2)
    P = coons_maps(pT, pB, pL, pR)
    src = cv2.perspectiveTransform(P.reshape(-1, 1, 2), np.linalg.inv(M)).reshape(OUT, OUT, 2)
    out = cv2.remap(img, src[..., 0], src[..., 1], interpolation=cv2.INTER_CUBIC)
    if debug_path:
        d, xs = w.copy(), np.arange(DW)
        for p, horiz, col in [(pT, True, (0, 0, 255)), (pB, True, (0, 255, 0)), (pL, False, (255, 0, 0)), (pR, False, (0, 255, 255))]:
            pts = np.stack([xs, np.polyval(p, xs)], -1) if horiz else np.stack([np.polyval(p, xs), xs], -1)
            cv2.polylines(d, [pts.astype(np.int32)], False, col, 3)
        cv2.imwrite(debug_path, cv2.resize(d, (600, 600)))
    return out


# ---------------------------------------------------------------- 5. colour
def color_match(bgr, corners=("tr", "br"), pencil=False, lines=0.5, warmth=None):
    """pencil=True: gentle treatment for graphite pages - keep the page's own tone (only half-way to
    TARGET_PAPER), no black-point stretch; strokes are darkened with a tone curve instead.
    lines: 0..1 line-darkening strength (0.5 = default look).
    warmth: 0..1 how far to move the paper from its own tone to TARGET_PAPER (default 1.0 ink, 0.5 pencil)."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
    # flatten uneven lighting using a heavily blurred field of the bright (paper) pixels
    lum = rgb.mean(2)
    m = (lum > np.percentile(lum, 55)).astype(np.float32)
    num, den = cv2.GaussianBlur(lum * m, (0, 0), 150), cv2.GaussianBlur(m, (0, 0), 150)
    prior = 0.15  # where few paper pixels exist (dense shading), fall back toward the global paper level
    glob = num.sum() / max(den.sum(), 1e-6)
    field = (num + prior * glob) / (den + prior)
    gain = np.clip(glob / field, 0.85, 1.2)
    rgb *= gain[..., None]
    # white-balance: bare paper = bright AND least-saturated pixels (ignores coloured pencil)
    lum, sat = rgb.mean(2), rgb.max(2) - rgb.min(2)
    bright = lum > np.percentile(lum, 70)
    sel = bright & (sat < np.percentile(sat[bright], 50))
    paper = np.median(rgb[sel], 0)
    if warmth is None:
        warmth = 0.5 if pencil else 1.0
    warmth = float(np.clip(warmth, 0, 1))
    target = paper * (1 - warmth) + TARGET_PAPER * warmth
    rgb *= target / paper
    lines = float(np.clip(lines, 0, 1))
    if pencil:
        # darken graphite without moving the paper: tones below paper luminance follow a power curve
        P = target.mean(); l = np.clip(rgb.mean(2), 1, None)
        k = 1.0 + 1.2 * lines                            # 0 -> untouched, 0.5 -> ^1.6, 1 -> ^2.2
        factor = np.where(l < P, (l / P) ** (k - 1), 1.0)
        rgb *= factor[..., None]
    else:
        # deepen ink: stretch the darkest 0.5% to black, then a gamma set by the slider
        lo = np.percentile(rgb.mean(2), 0.5)
        rgb = np.clip((rgb - lo) / (1 - lo / 255.0), 0, 255)
        rgb = 255 * (rgb / 255) ** (1.0 + 0.16 * lines)  # 0.5 -> 1.08 (previous default)
    return fill_corners(np.clip(rgb, 0, 255).astype(np.uint8), corners)


def fill_corners(rgb, which=("tr", "br"), frac=0.07):
    """Inpaint background showing in rounded page corners. which: subset of tl,tr,br,bl."""
    h, w = rgb.shape[:2]
    n = int(w * frac)
    lum = rgb.astype(np.float32).mean(2)
    paper = np.percentile(lum, 75)
    mask = np.zeros((h, w), np.uint8)
    boxes = {"tl": (slice(0, n), slice(0, n), 0, 0), "tr": (slice(0, n), slice(w - n, w), 0, n - 1),
             "bl": (slice(h - n, h), slice(0, n), n - 1, 0), "br": (slice(h - n, h), slice(w - n, w), n - 1, n - 1)}
    for k in which:
        ys, xs, cy, cx = boxes[k]
        sub = (lum[ys, xs] < paper - 70).astype(np.uint8)
        _, lab = cv2.connectedComponents(sub)
        if sub[cy, cx]:
            mask[ys, xs] = (lab == lab[cy, cx]).astype(np.uint8)
    if mask.any():
        rgb = cv2.inpaint(rgb, cv2.dilate(mask, np.ones((7, 7), np.uint8)), 7, cv2.INPAINT_TELEA)
    return rgb


def fill_outer_corners(rgb):
    return fill_corners(rgb, ("tr", "br"))


# ---------------------------------------------------------------- manual border (from annotate.py)
def densify_loop(pts, n=3000):
    """Resample a hand-drawn closed polyline to n evenly spaced points (mouse strokes bunch up at corners)."""
    loop = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(loop, axis=0), axis=1)
    t = np.concatenate([[0], np.cumsum(seg)])
    if t[-1] <= 0:
        return pts
    u = np.linspace(0, t[-1], n, endpoint=False)
    return np.stack([np.interp(u, t, loop[:, 0]), np.interp(u, t, loop[:, 1])], 1)


def dewarp_from_border(img, pts, debug_path=None):
    """pts: dense freehand polyline around the page edge, in photo pixels. Splits it into four edge
    curves, fits them, Coons-remaps to a square, and reports which corners are rounded
    (the stroke cuts inside the virtual corner where the fitted edges would meet)."""
    pts = densify_loop(np.asarray(pts, float))
    hull = cv2.convexHull(pts.astype(np.float32)).reshape(-1, 2)
    sm, df = hull.sum(1), hull[:, 0] - hull[:, 1]
    quad = np.array([hull[sm.argmin()], hull[df.argmax()], hull[sm.argmax()], hull[df.argmin()]])
    M = homography_to_square(inset_quad(quad, -0.08), DW)
    fp = cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float32), M).reshape(-1, 2)
    fq = cv2.perspectiveTransform(quad.reshape(-1, 1, 2).astype(np.float32), M).reshape(-1, 2)
    # assign each stroke point to the nearest side of the coarse quad (in frame space)
    sides = [(fq[0], fq[1]), (fq[1], fq[2]), (fq[2], fq[3]), (fq[3], fq[0])]  # top, right, bottom, left

    def dist_to_seg(p, a, b):
        ab, ap = b - a, p - a
        t = np.clip((ap @ ab) / (ab @ ab + 1e-9), 0, 1)
        return np.linalg.norm(ap - t[:, None] * ab, axis=1)

    d = np.stack([dist_to_seg(fp, a, b) for a, b in sides], 1)
    side = d.argmin(1)
    # drop points close to the coarse corners so rounded corners don't bend the edge fits
    near_corner = np.min(np.linalg.norm(fp[:, None, :] - fq[None], axis=2), axis=1) < 0.09 * DW

    def fit(k, xcol, ycol):
        sel = (side == k) & ~near_corner
        if sel.sum() < 8:            # thin side: allow the corner points back in
            sel = side == k
        if sel.sum() >= 3:
            deg = 2 if sel.sum() >= 8 else 1
            return robust_polyfit(fp[sel][:, xcol], fp[sel][:, ycol], deg=deg)
        a, b = sides[k]              # nothing drawn on this side: straight line through the coarse corners
        return np.polyfit([a[xcol], b[xcol]], [a[ycol], b[ycol]], 1)

    pT, pR, pB, pL = fit(0, 0, 1), fit(1, 1, 0), fit(2, 0, 1), fit(3, 1, 0)
    corners = corners_from_edges(pT, pB, pL, pR)  # tl,tr,br,bl (virtual, sharp)
    names = ["tl", "tr", "br", "bl"]
    rounded = [nm for nm, c in zip(names, corners) if np.min(np.linalg.norm(fp - np.array(c), axis=1)) > 0.012 * DW]
    P = coons_maps(pT, pB, pL, pR, inset=0.004, spine_inset=0.004)
    src = cv2.perspectiveTransform(P.reshape(-1, 1, 2), np.linalg.inv(M)).reshape(OUT, OUT, 2)
    out = cv2.remap(img, src[..., 0], src[..., 1], interpolation=cv2.INTER_CUBIC)
    if debug_path:
        w = cv2.warpPerspective(img, M, (DW, DW), flags=cv2.INTER_AREA)
        xs = np.arange(DW)
        for p, horiz, col in [(pT, True, (0, 0, 255)), (pB, True, (0, 255, 0)), (pL, False, (255, 0, 0)), (pR, False, (0, 255, 255))]:
            line = np.stack([xs, np.polyval(p, xs)], -1) if horiz else np.stack([np.polyval(p, xs), xs], -1)
            cv2.polylines(w, [line.astype(np.int32)], False, col, 3)
        for q in fp[::4].astype(int):
            cv2.circle(w, (int(q[0]), int(q[1])), 3, (255, 0, 255), -1)
        for nm, c in zip(names, corners):
            cv2.circle(w, (int(round(c[0])), int(round(c[1]))), 12, (0, 0, 255) if nm in rounded else (0, 255, 0), 3)
        cv2.imwrite(debug_path, cv2.resize(w, (600, 600)))
    return out, rounded


# ---------------------------------------------------------------- driver
def load(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def rotate_points_cw(pts, h):
    """Rotate (x,y) points by 90 degrees clockwise, matching cv2.ROTATE_90_CLOCKWISE on an image of height h."""
    pts = np.asarray(pts, float)
    return np.stack([h - 1 - pts[:, 1], pts[:, 0]], 1)


def process(path, work, out_dir, quality, spine_bottom=False, corners=None, border=None, pencil=False, lines=0.5, warmth=None):
    """corners: optional manual page corners [[x,y] tl, tr, br, bl] in the (EXIF-upright) photo's pixels,
    ordered as the drawing reads. When given, automatic detection and the facing-page cut are skipped."""
    n = os.path.splitext(os.path.basename(path))[0]
    img = load(path)
    if spine_bottom:  # book opened vertically: rotate so the spine is on the left like every other page
        if corners is not None:
            c = rotate_points_cw(corners, img.shape[0])
            corners = [c[3], c[0], c[1], c[2]]         # after rotating CW, the drawing's bl becomes the new tl
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if border is not None:  # freehand border from annotate.py: edges and rounded corners come from the stroke
        flat, rounded = dewarp_from_border(img, border, debug_path=os.path.join(work, f"{n}_edges.jpg"))
        out = color_match(flat, rounded, pencil, lines, warmth)
        quad = np.zeros((4, 2))
        print(f"{n}: manual border, rounded corners: {rounded or 'none'}")
    else:
        if corners is not None:
            quad = np.asarray(corners, float)
        else:
            quad = inset_quad(find_page(img), 0.012)
            for _ in range(3):
                quad, cut = refine_quad(img, quad)
        flat = dewarp(img, quad, debug_path=os.path.join(work, f"{n}_edges.jpg"))
        out = color_match(flat, pencil=pencil, lines=lines, warmth=warmth)
    if spine_bottom:
        out = cv2.rotate(out, cv2.ROTATE_90_COUNTERCLOCKWISE)
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    Image.fromarray(out).save(os.path.join(out_dir, f"{n}.jpg"), quality=quality)
    # before/after preview
    before = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)); before.thumbnail((1000, 1000))
    after = Image.fromarray(out).resize((1000, 1000))
    sbs = Image.new("RGB", (before.width + 1030, 1020), "white")
    sbs.paste(before, (10, 10)); sbs.paste(after, (before.width + 20, 10))
    sbs.save(os.path.join(work, f"{n}_before_after.png"))
    if border is None:
        print(f"{n}: page quad {quad.astype(int).tolist()}")
    return after


def grid(refs_dir, news, path, tile=380, cols=4):
    olds = [Image.open(f).convert("RGB") for f in sorted(glob.glob(os.path.join(refs_dir, "*.jp*g")))] if refs_dir else []
    tiles = []
    for im in olds + news:
        im = im.copy(); im.thumbnail((tile, tile))
        t = Image.new("RGB", (tile, tile), (235, 235, 235)); t.paste(im, ((tile - im.width) // 2, (tile - im.height) // 2))
        tiles.append(t)
    rows = (len(tiles) + cols - 1) // cols
    g = Image.new("RGB", (cols * (tile + 10) + 10, rows * (tile + 10) + 10), "white")
    for i, t in enumerate(tiles):
        g.paste(t, (10 + (i % cols) * (tile + 10), 10 + (i // cols) * (tile + 10)))
    g.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True, help="folder of phone photos (HEIC/JPG/PNG)")
    ap.add_argument("--out", required=True, help="folder for finished 2048x2048 JPEGs")
    ap.add_argument("--work", required=True, help="folder for debug images, before/after previews and the grid")
    ap.add_argument("--refs", default=None, help="existing gallery folder (e.g. static/sketches) to include in the grid")
    ap.add_argument("--quality", type=int, default=82)
    ap.add_argument("--only", nargs="*", help="basenames (without extension) to process; default all")
    ap.add_argument("--spine-bottom", nargs="*", default=[],
                    help="basenames of photos where the book was opened vertically (spine below the page, rounded corners on top)")
    ap.add_argument("--pencil", nargs="*", default=[], help="basenames of graphite pages: gentler colour treatment")
    ap.add_argument("--corners", default=None,
                    help="JSON written by annotate.py: {name: {border: [[x,y],...]} or {corners: [[x,y]x4], spine_bottom: bool}}")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True); os.makedirs(a.work, exist_ok=True)
    files = sorted(f for f in glob.glob(os.path.join(a.inp, "*")) if f.lower().endswith((".heic", ".jpg", ".jpeg", ".png")))
    if a.only:
        files = [f for f in files if os.path.splitext(os.path.basename(f))[0] in a.only]
    if not files:
        sys.exit(f"no images found in {a.inp}")
    manual = {}
    if a.corners and os.path.exists(a.corners):
        import json
        manual = json.load(open(a.corners))
    news = []
    for f in files:
        n = os.path.splitext(os.path.basename(f))[0]
        m = manual.get(n, {})
        news.append(process(f, a.work, a.out, a.quality,
                            spine_bottom=(n in a.spine_bottom) or m.get("spine_bottom", False),
                            corners=m.get("corners"), border=m.get("border"),
                            pencil=(n in a.pencil) or m.get("pencil", False), lines=m.get("lines", 0.5), warmth=m.get("warmth")))
    grid(a.refs, news, os.path.join(a.work, "grid_old_and_new.png"))
    print(f"finished -> {a.out}\npreviews -> {a.work}")


if __name__ == "__main__":
    main()
