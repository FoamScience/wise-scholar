# Crafted figures

A crafted figure is a real object you could build, drawn as a shaded isometric object: a test rig, a dial gauge, a
lock, a pump, a chest of drawers, a stack of memory cells as a rack of trays. You write a small script against the
kit; the server runs it and shows the SVG it exports as a figure, coloured by the site's theme. The reader names the
object at a glance, and its parts show how it works.

## The script

An ES module. It imports the kit from `./kit/iso-kit.mjs` and exports as default the string `figureSvg` returns.
Nothing else runs: no network, no files, no page script. Keep the script under 30 000 characters and the SVG it
makes under 120 000. Never pass `standalone` to `figureSvg`: the site's theme styles the figure.

```js
import * as k from "./kit/iso-kit.mjs";

const W = 600, H = 360;
const base = { x: 0, y: 0, w: 120, d: 80, r: 6 };
const post = [90, 40];
const P = k.fitProjection([...k.boxCorners(base, -4, 6), [post[0], post[1], 72]], W, H, { pad: 30, azimuth: 50 });
const parts = [];
for (const [x, y] of k.corners(base, 10)) parts.push(k.solidSvg(k.cylinder(x, y, 4, -4, 4, P, 16), { tone: "lo" }));
parts.push(k.solidSvg(k.slabOf(base, 0, 6, P, 8, 0.6), { tone: "mid", halo: true }));
parts.push(k.lineSvg(k.planOutline(k.insetPlan(base, 8), 6, P), { tone: "faint" }));
parts.push(k.dotsSvg(k.pointsAt(k.corners(base, 4).map(([x, y]) => [x, y, 6]), P), { tone: "mid" }));
parts.push(k.solidSvg(k.cylinder(post[0], post[1], 6, 6, 60, P, 24), { tone: "mid" }));
parts.push(k.solidSvg(k.cylinder(post[0], post[1], 10, 66, 6, P, 24), { tone: "hi", lit: true }));
export default k.figureSvg({ width: W, height: H, label: "A knob on a post, standing on a base plate with four feet", body: parts });
```

World coordinates are `[x, y, z]`: x and y on the floor, z up, in units of about one pixel. Screen points are
`[sx, sy]` in the viewBox. Every function that draws takes the projection `P` and returns an SVG `d` string or a
markup string. A plan is a rounded rectangle on the floor: `{ x, y, w, d, r }`.

## Camera

| Function | What it does |
|---|---|
| `fitProjection(points, width, height, { pad = 24, headroom = 0, azimuth = 45, elevation = 30 })` | A projection that centres and fits these points in the viewBox. Pass every extreme point: `boxCorners(plan, z0, z1)` of the base and the tallest tip. |
| `iso(point, P)` | World to screen. |
| `depthOf(point, P)` | Larger means nearer the viewer. Sort ascending to paint back to front. |
| `towardViewer(P)` | The floor direction pointing at the viewer. |
| `screenRise(h, P)` | How many screen px a height of `h` covers. |

Default camera: azimuth 45°, elevation 30°. Turn the azimuth (35° to 60°) so the face that carries the mechanism
points at the viewer; raise the elevation to look into something open. A viewBox of 600 × 340 to 380 reads well.
The object fills about 60% of the figure, with air around it.

## Solids

All solids are prisms: a floor outline extruded straight up. Each returns paths for `solidSvg`.

| Function | What it does |
|---|---|
| `slabOf(plan, z, h, P, steps = 8, bevel = 0)` | A rounded box. `steps` is the points per corner (2 to 4 for small parts, 8 to 10 for large rounded ones). `bevel` (0.3 to 1.6) adds a highlight line on the top along the visible edges. |
| `cylinder(cx, cy, r, z, h, P, steps = 32, bevel = 0)` | A round post, puck, foot, knob or pad. 16 to 20 steps for small ones, 56 to 72 for big discs. |
| `extrude(ring, z, h, P, { convex = true, bevel })` | Any floor outline, as a list of `[x, y]` points. Pass `convex: false` for a concave outline. |
| `ringOf(plan, steps)` | A rounded-rectangle outline as points. `circleRing(cx, cy, r, steps)` is the same for a circle. |
| `insetPlan(plan, by)` | Shrinks a plan; a negative `by` grows it. |
| `corners(plan, inset)` | Four floor points inset from the corners, for feet and screws. |
| `boxCorners(plan, z0, z1)` | The eight corners, for `fitProjection`. |
| `haloOf(plan, z, h, P)` | A fill path for a soft shadow under a base, or pass `halo: true` to `solidSvg`. |

## Lines on faces

| Function | What it draws |
|---|---|
| `onTop(points, z, P, closed?)` | A polyline on a horizontal face, from `[x, y]` points. |
| `lineOnTop(a, b, z, P)` | One segment on a horizontal face. |
| `planOutline(plan, z, P, steps)` | A rounded-rectangle outline on a face: grooves and inlays, with `insetPlan`. |
| `ring(cx, cy, r, z, P, steps)` | A circle on a face: screw rings, bezels, seats. |
| `segment(a, b, P)` | Any segment between two world points. `rise(at, z0, z1, P)` is a vertical one. |
| `pointsAt(points, P)` | Projects world points, for screw and rivet dots. |
| `dotGrid(x, y, cols, rows, gap, z, P)` | Projected perforations. |
| `topMatrix(at, z, P, along = "x")` | A transform that lays `faceTextSvg` flat on a top face; `sideMatrix(at, z, P, "left" or "right")` on a vertical face. |

## Parts

| Function | Returns |
|---|---|
| `knurl(cx, cy, r, z0, z1, count, P)` | Vertical lines on the visible half of a cylinder: a grip. |
| `sideArc(cx, cy, r, z, P, steps)` | The visible front half of a horizontal circle on a cylinder: seams and bands. |
| `sideSeam(plan, z, P, steps = 8)` | The visible near half of a plan at height `z`, wrapping its corners and ending on the slab's silhouette: a weld bead, a lid seam, a trim line on a box. Draw it as the slab's `inner`. Never a segment inset from the corners. |
| `ringSeam(ring, z, P)` | `sideSeam` for any floor outline. |
| `sideRing(centre, r, "x" or "y", P)` | A circle on a vertical face: bores, rod ends, lenses. |
| `coil(from, to, [cy, cz], r, turns, "x" or "y", P)` | `{ back, front }` halves of a spring, painted back, then the rod, then front. |
| `topTicks(from, to, step, every, edge, z, [minor, major], P, axis)` | `{ minor, major }` ruler ticks on a top face. `sideTicks` hangs them down a vertical face; `radialTicks(cx, cy, r, count, every, z, [minor, major], P)` makes a dial. |
| `translateAlong(P, [dx, dy, dz])` | A `transform` string that moves a built group by a world offset, for a part shown displaced. |

## Markup

| Function | Notes |
|---|---|
| `solidSvg(paths, { tone = "hi", crease = "faint", halo, lit, flat, inner })` | A solid: paper fill, four shaded sides, lighter top, crease, outline. `inner` is line markup placed under the outline, for seams. |
| `lineSvg(d, { tone = "lo", dotted, dashed, flow })` | A line. `flow` animates its dashes along the path: use it only for something that really moves along it. |
| `dotsSvg(points, { size = 0.5, tone = "mid", pulse })` | Screws, rivets, perforations, from screen points. A point may carry a third value, its opacity. `pulse` blinks them in turn. |
| `fadedSvg(list, style)` | Lines that each carry an opacity, `[d, alpha]`, for a texture that fades out toward a limb. |
| `wireSvg(from, to, { via, tone, dotted, dashed, flow, ends })` | A connector between screen points, with terminal dots. |
| `faceTextSvg(transform, text, { size = 3, tone = "mid", anchor })` | One small engraved label on a face. |
| `groupSvg(children, { transform })` | A group. |
| `figureSvg({ width, height, label, body })` | The `<svg>`. `label` says what the object is and what it shows. `body` is the list of parts in painting order. |

`fadeLineSvg` loses its gradient here; use `fadedSvg` instead.

## Tones

Every stroke and fill is a tone, resolved by the site's theme, so a figure reads in light and dark alike.

| Element | Tone |
|---|---|
| Base, feet, floors, minor ticks | `lo` |
| Structure: posts, rails, frame, carriage, case; major ticks | `mid` |
| The subject: the thing being explained; zero mark, pointer | `hi` |
| The one part the reader should watch now | `lit` (one only; a solid with `lit: true` gets a bright edge and a lighter top) |
| Grooves, inset outlines, floor grid | `faint` |
| Screws and rivets | dots `mid` at 0.4 to 0.55 |
| Meaning carried by colour | `accent` (the site's teal), `warm` (amber), `alert` (danger); lines only, and only when the colour says something |

Keep the figure monochrome otherwise. Colour everywhere is the mark of a poor figure.

## Painter's order

- The base first, then everything resting on it.
- Within a level, sort by `depthOf(centre, P)` ascending: far before near.
- A part that wraps another (a spring around a rod, a frame around a carriage) is split: back half, the inner part, front half.
- A vertical part passing through a horizontal one (a post through a clamp) is two segments, below and above.
- On a stepped surface, taller steps go further back.

## What makes it crafted

1. **A real object.** Invented for the subject, named at a glance. Never a floating abstraction: layers are drawers, trays in a rack or plates on guide pillars, not stacked slabs.
2. **Many small, precise parts.** Thirty to sixty solids is a good figure. Every part rests on another, aligns to its neighbours and has a job: feet, rails, stops, bushings, knobs, a label plate. Density comes from structure, not texture.
3. **Volume.** Real thickness, shaded sides, lighter tops, a bevel that catches light, a halo under the base.
4. **Calm.** Thin lines, one lit accent, nothing moving unless it moves in the real thing.
5. **Every line lands on something.** No connector that stops short, no crease that ends before a corner, no texture that stops dead on a surface: a seam runs edge to edge round the visible corners, ticks hang from a ruler's edge, a texture that must end fades out.

Not in the drawing: leader lines, numbered balloons, dimension arrows, hatching, dashed hidden edges, see-through
boxes, floating labels. At most one tiny engraved label on a face. The names of the parts go in the caption and
the alt text.
