/*
MIT License
Copyright (c) 2026 Bilawal Sidhu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Adapted from src/ui/panelRailGeometry.js at
https://github.com/bilawalsidhu/gods-eye-view/tree/591f299d11f38a612629a274463196d57ae3862e
Changes: classic browser global instead of ES module export; only the pure rail
layout resolver is included. No upstream services, data, or media are bundled.
*/
(function(global){
"use strict";
function resolveHudRailLayout({
  viewportHeight,
  panelHeight,
  laneLeft,
  laneRight,
  obstacles = [],
  baseTop,
  baseBottom,
  gap = 12,
  align = "center",
}) {
  if (
    ![
      viewportHeight,
      panelHeight,
      laneLeft,
      laneRight,
      baseTop,
      baseBottom,
    ].every(Number.isFinite) ||
    viewportHeight <= 0 ||
    laneRight <= laneLeft
  )
    return null;
  const midpoint = viewportHeight * 0.5;
  let safeTop = Math.max(0, baseTop);
  let safeBottom = Math.min(viewportHeight, baseBottom);

  for (const rect of obstacles) {
    if (
      ![rect?.left, rect?.right, rect?.top, rect?.bottom].every(Number.isFinite)
    )
      continue;
    if (
      rect.right <= laneLeft ||
      rect.left >= laneRight ||
      rect.bottom <= rect.top
    )
      continue;
    if (rect.bottom <= midpoint) safeTop = Math.max(safeTop, rect.bottom + gap);
    else if (rect.top >= midpoint)
      safeBottom = Math.min(safeBottom, rect.top - gap);
  }

  safeBottom = Math.max(safeTop, safeBottom);
  const availableHeight = Math.max(0, safeBottom - safeTop);
  const renderedHeight = Math.min(Math.max(0, panelHeight), availableHeight);
  return {
    top:
      align === "start"
        ? safeTop
        : safeTop + Math.max(0, (availableHeight - renderedHeight) * 0.5),
    maxHeight: availableHeight,
    safeTop,
    safeBottom,
    constrained: panelHeight > availableHeight,
  };
}
global.KnightHudRail = Object.freeze({resolveHudRailLayout});
})(window);
