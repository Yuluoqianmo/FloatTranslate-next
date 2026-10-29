"""Coordinate-based OCR regions. All bounds are in source image pixels."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextRegion:
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class OverlayRegion:
    source: TextRegion
    translation: str


def merge_lines(lines: list[TextRegion]) -> list[TextRegion]:
    """Join adjacent lines in one paragraph without merging nearby columns."""
    groups: list[TextRegion] = []
    for line in sorted(lines, key=lambda item: (item.y, item.x)):
        if not line.text.strip():
            continue
        candidate = None
        for index in range(len(groups) - 1, -1, -1):
            group = groups[index]
            gap = line.y - (group.y + group.height)
            left_aligned = abs(line.x - group.x) <= max(12, line.height * 0.7)
            # Compare the current line against the previous paragraph's average line height.
            average = group.height / max(1, group.text.count("\n") + 1)
            similar_size = 0.65 <= line.height / max(1, average) <= 1.45
            if left_aligned and similar_size and -2 <= gap <= max(5, line.height * 0.65):
                candidate = index
                break
        if candidate is None:
            groups.append(line)
        else:
            previous = groups[candidate]
            right = max(previous.x + previous.width, line.x + line.width)
            bottom = max(previous.y + previous.height, line.y + line.height)
            groups[candidate] = TextRegion(previous.text + "\n" + line.text, min(previous.x, line.x),
                                           previous.y, right - min(previous.x, line.x), bottom - previous.y)
    return sorted(groups, key=lambda item: (item.y, item.x))
