"""Counting keyframes drawn by code instead of an image model.

Video and image models both miscount: seen live, every image edit asked for "four
apples" came back with 9, 5 or 1, and one clip that placed two apples at once was
carried into every later shot. So once a clip of a counting sequence is checked to
end right, its last frame becomes the base: the object it just placed is cut out
(where it differs from the clip's first frame) and pasted into the next free spots
of the row. Every later shot then starts and ends on a frame with exactly the
count it needs, and the video model only animates the hand between the two.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from statistics import median

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels

DIFF_THRESHOLD = 30  # 0-255; a pixel the placing changed
MIN_COVER = 0.35  # share of the object's ellipse the difference must fill to be trusted
MIN_GAP = 0.1  # free space between two objects, in object widths
DEFAULT_GAP = 0.45  # spacing when the row has one object to learn from


class RigError(Exception):
    pass


@dataclass
class Rig:
    base: Image.Image
    sprite: Image.Image  # RGBA, the newest object with its shadow
    offset: tuple[int, int]  # sprite's top-left relative to its object's box
    count: int  # objects already in ``base``
    slots: list[Box] = field(default_factory=list)  # spots for count + 1, count + 2, ...

    @property
    def capacity(self) -> int:
        return self.count + len(self.slots)


def parse_boxes(raw, width: int, height: int) -> list[Box]:
    """``[[ymin, xmin, ymax, xmax], ...]`` on a 0-1000 grid (how vision models
    give boxes) → pixel boxes; malformed entries are dropped."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not (isinstance(item, (list, tuple)) and len(item) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in item)):
            continue
        ymin, xmin, ymax, xmax = (max(0.0, min(1000.0, float(v))) for v in item)
        if xmax - xmin < 5 or ymax - ymin < 5:
            continue
        out.append((round(xmin * width / 1000), round(ymin * height / 1000),
                    round(xmax * width / 1000), round(ymax * height / 1000)))
    return out


def _open(png: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(png)).convert("RGB")
    except Exception as exc:  # noqa: BLE001 — any undecodable image
        raise RigError("gambar tidak terbaca") from exc


def _changed(after: Image.Image, before: Image.Image | None, box: Box) -> float:
    if before is None:
        return 0.0
    a = np.asarray(after.crop(box), dtype=np.int16)
    b = np.asarray(before.crop(box), dtype=np.int16)
    return float((np.abs(a - b).max(axis=2) > DIFF_THRESHOLD).mean())


def _cut(after: Image.Image, before: Image.Image | None, box: Box) -> tuple[Image.Image, tuple[int, int]]:
    """The object in ``box`` with its contact shadow, as an RGBA sprite."""
    width, height = after.size
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    pad_x, pad_top, pad_bottom = round(w * 0.15), round(h * 0.1), round(h * 0.3)
    region = (max(0, x0 - pad_x), max(0, y0 - pad_top), min(width, x1 + pad_x), min(height, y1 + pad_bottom))
    rx, ry = region[0], region[1]
    shape = Image.new("L", (region[2] - rx, region[3] - ry), 0)
    draw = ImageDraw.Draw(shape)
    grow_x, grow_y = w * 0.05, h * 0.05
    draw.ellipse((x0 - grow_x - rx, y0 - grow_y - ry, x1 + grow_x - rx, y1 + grow_y - ry), fill=255)
    draw.ellipse((x0 - pad_x / 2 - rx, y1 - h * 0.18 - ry, x1 + pad_x / 2 - rx, y1 + h * 0.22 - ry), fill=255)
    mask = shape
    if before is not None:
        diff = np.abs(np.asarray(after.crop(region), dtype=np.int16) - np.asarray(before.crop(region), dtype=np.int16))
        changed = Image.fromarray(((diff.max(axis=2) > DIFF_THRESHOLD) * 255).astype(np.uint8), "L")
        changed = changed.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
        both = np.minimum(np.asarray(changed), np.asarray(shape))
        cover = (both > 0).sum() / max(1, (np.asarray(shape) > 0).sum())
        # a weak difference (the frames barely differ there) says nothing about the outline
        if cover >= MIN_COVER:
            mask = Image.fromarray(both, "L")
    mask = mask.filter(ImageFilter.GaussianBlur(max(1.0, w * 0.03)))
    sprite = after.crop(region).convert("RGBA")
    sprite.putalpha(mask)
    return sprite, (rx - x0, ry - y0)


def _overlaps(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def build(after_png: bytes, before_png: bytes | None, boxes: list[Box], container: Box | None, *,
          total: int, surface: Box | None = None) -> Rig:
    """A rig from a frame with ``len(boxes)`` counted objects in a row, able to draw
    the row up to ``total``. ``before_png`` (the same shot's first frame) finds the
    newest object and its outline; the new spots stay off ``container`` (where the
    objects come from) and on ``surface`` (the table). Raises :class:`RigError` when
    the boxes do not look like one row or the free space cannot hold the rest."""
    after = _open(after_png)
    before = _open(before_png) if before_png else None
    if before is not None and before.size != after.size:
        before = None
    width, height = after.size
    if not boxes:
        raise RigError("tidak ada objek")
    boxes = sorted(boxes, key=lambda b: b[0])
    w = median(b[2] - b[0] for b in boxes)
    h = median(b[3] - b[1] for b in boxes)
    if any(abs((b[2] - b[0]) - w) > 0.4 * w or abs((b[3] - b[1]) - h) > 0.4 * h for b in boxes):
        raise RigError("ukuran objek tidak seragam")
    centres = [(b[1] + b[3]) / 2 for b in boxes]
    if max(centres) - min(centres) > 0.5 * h:
        raise RigError("objek tidak sebaris")
    if any(_overlaps(a, b) for a, b in zip(boxes, boxes[1:])):
        raise RigError("objek bertumpuk")
    # the newest object is where the shot changed most; a row grows on that side
    scores = [_changed(after, before, b) for b in boxes]
    newest = max(range(len(boxes)), key=lambda i: scores[i]) if max(scores) > 0 else len(boxes) - 1
    placed = [i for i, s in enumerate(scores) if s > 0 and s >= 0.5 * max(scores)]
    if len(placed) <= 1:
        step_dir = -1 if len(boxes) > 1 and newest == 0 else 1
    elif len(placed) < len(boxes):  # a shot that placed several next to older ones
        old = [i for i in range(len(boxes)) if i not in placed]
        step_dir = -1 if sum(placed) / len(placed) < sum(old) / len(old) else 1
    else:  # the whole row is new: it grows toward where the objects come from, else right
        centre = (boxes[0][0] + boxes[-1][2]) / 2
        step_dir = -1 if container and (container[0] + container[2]) / 2 < centre else 1
    if len(placed) > 1:
        newest = max(placed) if step_dir > 0 else min(placed)
    edge = boxes[newest]
    if len(boxes) > 1:
        step = median(abs(b[0] - a[0]) for a, b in zip(boxes, boxes[1:]))
    else:
        step = w * (1 + DEFAULT_GAP)
    need = total - len(boxes)
    slots: list[Box] = []
    if need > 0:
        if step_dir > 0:
            room = width - 2 - edge[2]
            if surface and surface[2] > edge[2]:
                room = min(room, surface[2] - w * MIN_GAP - edge[2])
            if container and container[0] > edge[2] and container[1] < edge[3] and container[3] > edge[1]:
                room = min(room, container[0] - w * MIN_GAP - edge[2])
        else:
            room = edge[0] - 2
            if surface and surface[0] < edge[0]:
                room = min(room, edge[0] - surface[0] - w * MIN_GAP)
            if container and container[2] < edge[0] and container[1] < edge[3] and container[3] > edge[1]:
                room = min(room, edge[0] - container[2] - w * MIN_GAP)
        step = min(step, room / need)  # the last new object must end inside the free space
        if step < w * (1 + MIN_GAP):
            raise RigError("ruang kosong tidak cukup")
        for i in range(1, need + 1):
            dx = round(step * i) * step_dir
            slots.append((edge[0] + dx, edge[1], edge[2] + dx, edge[3]))
        if container and any(_overlaps(s, container) for s in slots):
            raise RigError("tempat baru menimpa wadah")
    sprite, offset = _cut(after, before, edge)
    return Rig(base=after, sprite=sprite, offset=offset, count=len(boxes), slots=slots)


def compose(rig: Rig, count: int) -> bytes:
    """The base frame with the row filled up to ``count`` objects, as PNG."""
    if not rig.count <= count <= rig.capacity:
        raise RigError(f"jumlah {count} di luar {rig.count}-{rig.capacity}")
    image = rig.base.copy()
    for slot in rig.slots[:count - rig.count]:
        image.paste(rig.sprite, (slot[0] + rig.offset[0], slot[1] + rig.offset[1]), rig.sprite)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
