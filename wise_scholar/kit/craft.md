# Crafted figures

A crafted figure draws the thing as itself, in volume, shaded, painted from the site's own palette: a machine as a machine
with its feet and rails, a chromosome as two chromatids pinched at the centromere, a cell as a soft body with a
membrane and what lies inside it, a heart as chambers and vessels, a bridge as deck and cables. You write a small
script against the kit; the server runs it and shows the SVG it exports as a figure. The reader names the thing at
a glance, and its parts show what it is and how it works.

The kit has three families of parts. Use the one the thing is made of:

- **Prisms** (`iso-kit.mjs`): anything that stands on a floor with flat faces and round posts. Machines, devices,
  furniture, buildings.
- **Tubes and turned bodies** (`tube.mjs`, `lathe.mjs`): anything bent or round. A chromatid, a vessel, a neurite,
  a bone, a pipe, a cable, a bell, a lens, a ball.
- **Soft bodies** (`blob.mjs`): anything without a hard edge. A cell, an organelle, a drop, a membrane, an organ.

Never give a thing parts it does not have. No base plate under a cell, no feet under a chromosome, no frame
around an organ, no screws on a bone. A built thing has feet, rails and fasteners because the real one does.
An abstraction has no body to craft: layers, a data structure, a protocol, a relation are flat drawings for
`add_figure` or Mermaid, not objects.

## The script

An ES module. It imports the kit from `./kit/` and exports as default the string `figureSvg` returns, or an array
of 2 to 6 such strings for an animation. Nothing else runs: no network, no files, no page script. Keep the script
under 30 000 characters and the SVG it makes under 120 000. Never pass `standalone` to `figureSvg`: the site's
theme styles the figure.

A built thing, from prisms:

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

A living thing, from tubes:

```js
import * as k from "./kit/iso-kit.mjs";
import { fillet } from "./kit/lathe.mjs";
import { tubePieces, tubeSvg } from "./kit/tube.mjs";

const W = 600, H = 380;
// Two sister chromatids, each a bent rod pinched at the centromere: the lower arm long, the upper one short.
const legs = [[30, -10, 0], [8, -1, 30], [0, 0, 38], [5, 3, 46], [16, 10, 62]];
const chromatid = (side) => fillet(legs.map(([x, y, z]) => [side * x, y, z]), 9);
const length = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
const spans = legs.slice(1).map((p, i) => length(legs[i], p));
const centromere = (spans[0] + spans[1]) / spans.reduce((a, b) => a + b);  // where along the rod it sits, 0 to 1
const pinch = (t) => 6.5 - 3.2 * Math.exp(-((t - centromere) ** 2) / 0.012);
const routes = [chromatid(-1), chromatid(1)];
const P = k.fitProjection(routes.flat(), W, H, { pad: 44, azimuth: 40, elevation: 24 });
const pieces = routes.flatMap((route, n) => tubePieces(route, pinch, P, { maxLength: 8 }).map((piece) => ({ piece, depth: k.depthOf(piece.mid, P), n })));
pieces.sort((a, b) => a.depth - b.depth);
const parts = pieces.map(({ piece, n }) => tubeSvg(piece, { tone: n ? "hi" : "mid" }));
export default k.figureSvg({ width: W, height: H, label: "A metaphase chromosome: two sister chromatids, each pinched at the centromere where they join", body: parts });
```

World coordinates are `[x, y, z]`: x and y on the floor, z up, in units of about one pixel. Screen points are
`[sx, sy]` in the viewBox. Every function that draws takes the projection `P` and returns an SVG `d` string or a
markup string. A plan is a rounded rectangle on the floor: `{ x, y, w, d, r }`.

## Animation

A thing that changes (a press closing, a valve opening, a cell dividing, a packet moving through a switch) is
the same script exporting an array of 2 to 6 strings, each what `figureSvg` returns for one state of the same
thing, in order. The server plays them as one animation, three seconds a stage, each fading in over the one
before, the first again after the last; the stage buttons hold any one of them. Build the figure in a function
of the state and call it once per stage: same size, same camera, same parts, only the moving ones at their new
place (rebuild them there; `translateAlong` moves a built group by a world offset). Say in the alt text what
changes from stage to stage.

## Camera

| Function | What it does |
|---|---|
| `fitProjection(points, width, height, { pad = 24, headroom = 0, azimuth = 45, elevation = 30 })` | A projection that centres and fits these points in the viewBox. Pass every extreme point: `boxCorners(plan, z0, z1)` of a base, the tallest tip, every route point of a tube. |
| `iso(point, P)` | World to screen. |
| `depthOf(point, P)` | Larger means nearer the viewer. Sort ascending to paint back to front. |
| `towardViewer(P)` | The floor direction pointing at the viewer. |
| `screenRise(h, P)` | How many screen px a height of `h` covers. |

Default camera: azimuth 45°, elevation 30°. Turn the azimuth (35° to 60°) so the side that shows the most points at
the viewer; raise the elevation to look into something open. A viewBox of 600 × 340 to 380 reads well.
The thing fills about 60% of the figure, with air around it.

## Prisms

All prisms stand on the floor: a floor outline extruded straight up. Each returns paths for `solidSvg`.

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

Lines on their faces:

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
| `knurl(cx, cy, r, z0, z1, count, P)` | Vertical lines on the visible half of a cylinder: a grip. |
| `sideArc(cx, cy, r, z, P, steps)` | The visible front half of a horizontal circle on a cylinder: seams and bands. |
| `sideSeam(plan, z, P, steps = 8)` | The visible near half of a plan at height `z`, wrapping its corners and ending on the slab's silhouette: a weld bead, a lid seam, a trim line on a box. Draw it as the slab's `inner`. |
| `sideRing(centre, r, "x" or "y", P)` | A circle on a vertical face: bores, rod ends, lenses. |
| `coil(from, to, [cy, cz], r, turns, "x" or "y", P)` | `{ back, front }` halves of a spring, painted back, then the rod, then front. |
| `topTicks(from, to, step, every, edge, z, [minor, major], P, axis)` | `{ minor, major }` ruler ticks on a top face. `sideTicks` hangs them down a vertical face; `radialTicks(cx, cy, r, count, every, z, [minor, major], P)` makes a dial. |
| `translateAlong(P, [dx, dy, dz])` | A `transform` string that moves a built group by a world offset, for a part shown displaced. |

## Tubes

`import { tubePieces, tubeSvg } from "./kit/tube.mjs"` and `import { fillet } from "./kit/lathe.mjs"`.

| Function | What it does |
|---|---|
| `fillet(points, radius)` | Rounds every corner of a 3D polyline with a bend of `radius`. Lay a route out as a few straight legs, then fillet it. |
| `tubePieces(points, radius, P, { maxLength = 30, closed = false, gaps = [], breaks = [], caps = true, stripes = "auto" })` | A 3D route as pieces of a round rod, each with a paper body, a shine band toward the light, a shade band away from it and its edges. `radius` is a number or a function of `t` (0 to 1 along the route): a taper, a pinch, a bulge. `gaps` are `[from, to]` arc lengths left undrawn where a collar or another part covers the rod; `breaks` are arc lengths where a piece must end, such as a crossing. Each piece has `mid`, its centre in world space: sort pieces by `depthOf(mid, P)` with everything else. Short pieces (6 to 12) where a rod weaves among other parts. A rod thinner than about 1.5 px on screen draws flat unless you pass `stripes: true`. |
| `tubeSvg(piece, { tone = "hi" })` | One piece as markup. |
| `tubePieces(…, { rings: { pitch = 3, twist = 0, fade = [0.1, 0.55] } })` | A texture following the rod's cross-section: ridges on a trachea, a braid, a corrugation, with `twist` for a helix. |

## Turned bodies

`import * as G from "./kit/lathe.mjs"`. A frame is an axis in space: `G.frameAlong(origin, axis)` (any direction,
radial directions chosen for you) or `G.frameOf(origin, axis, u, v)`. Along it, a profile is a list of `[s, r]`
points (`s` along the axis, `r` the radius); mark a point `[s, r, 1]` where the surface is smooth, so no crease is
drawn and the shading follows the curve. Each returns paths for `solidSvg`.

| Function | What it does |
|---|---|
| `solidOf(profile, F, P, options)` | A body of revolution closed at both ends: a bone shaft, a bell, a vase, a bulb, a cone, a flask. `G.solidOf([[0, 12], [6, 12], [8, 9, 1], [20, 9]], F, P)`. |
| `disc(s0, s1, r, F, P)` | A short cylinder on the axis: a puck, a flange, a pin, a cap. |
| `ringBand(s0, s1, rIn, rOut, F, P)` | An annulus with thickness: a collar around something, a ring. |
| `sphereOf(centre, r, P, { steps = 48 })` | A ball with smooth tones: a nucleus, an eye, a bearing, a planet. |
| `lathe(meridian, F, P, { hole, bevel, rims })` | The general solid of revolution; `hole: [s, r]` opens the end of a tube. |
| `arcOf(F, s, r, P, { slope = 0 })` | The visible arc of a ring on the surface: a seam, a band, a lip. Draw it as the solid's `inner`. |
| `ribsOf(F, s0, s1, r, count, P, { fade })` | Visible lines along the axis: ribs, fins, a knurl, the ridges of a muscle. With `fade` they come back as `[{ d, alpha }]` for `fadedSvg`. |
| `dotsOf(F, s, r, count, P, { fade })` | Screen points of a circle of dots on the visible side, for `dotsSvg`. |
| `resample(points, spacing)`, `pathLength(points)`, `pointAlong(points, at)`, `tangentAlong(points, at)` | Along a route: even spacing, its length, a point and its direction at an arc length, to place something on a tube. |

## Soft bodies

`import { blobOf, blobSvg, membraneOf, membraneSvg, blobPath } from "./kit/blob.mjs"`.

| Function | What it does |
|---|---|
| `blobOf(points, P, { tone = "hi" })` | A soft body from a closed ring of 3D points (eight to sixteen, slightly uneven, so it reads as living): a smooth curve through them, with a shade and a highlight inside. Sort blobs with everything else by their `depth`. |
| `blobSvg(blob)` | The body as markup. |
| `membraneOf(outer, inner, P, { tone })` and `membraneSvg(membrane)` | A flat ring between two closed rings of points: a membrane or a wall seen in cross-section, the cut surface of a cutaway. |
| `blobPath(points, P)` | Just the curve through projected points, as a `d` string, for your own line. |

Lay a cell out as a blob for the body, blobs for the organelles sorted by depth inside it, a membrane where a
cross-section shows the wall, and tubes for anything thread-like.

## Markup

| Function | Notes |
|---|---|
| `solidSvg(paths, { tone = "hi", crease = "faint", halo, lit, flat, inner })` | A prism or turned body: paper fill, shaded sides, lighter top, crease, outline. `inner` is line markup placed under the outline, for seams. |
| `lineSvg(d, { tone = "lo", dotted, dashed, flow })` | A line. `flow` animates its dashes along the path: use it only for something that really moves along it. |
| `dotsSvg(points, { size = 0.5, tone = "mid", pulse })` | Dots from screen points: screws, pores, ribosomes, perforations. A point may carry a third value, its opacity. `pulse` blinks them in turn. |
| `fadedSvg(list, style)` | Lines that each carry an opacity, `[d, alpha]`, for a texture that fades out toward a limb. |
| `wireSvg(from, to, { via, tone, dotted, dashed, flow, ends })` | A connector between screen points, with terminal dots. |
| `faceTextSvg(transform, text, { size = 3, tone = "mid", anchor })` | One small engraved label on a face. |
| `groupSvg(children, { transform })` | A group. |
| `figureSvg({ width, height, label, body })` | The `<svg>`. `label` says what the thing is and what it shows. `body` is the list of parts in painting order. |

`fadeLineSvg` loses its gradient here; use `fadedSvg` instead.

## Paint

The kit draws in the site's greys until you paint. `groupSvg(parts, { "data-paint": "teal" })` recolours every
part inside the group, prism, tube or soft body alike, keeping its shading, and the colour follows the theme.
The paints are the site's own colours:

| Paint | What it is | Use it for |
|---|---|---|
| `teal`, `teal-full` | The site's accent, as a tint or in full | The subject, what the reader follows, water, living tissue |
| `amber`, `amber-full` | Warm, as a tint or in full | Heat, energy, light, wood, the second thing when two must be told apart |
| `danger`, `danger-full` | The site's alert colour | Harm, a fault, blood, what must not happen |
| `dark` | The site's code background, dark in both themes | A dark material: rubber, iron, a shadow cavity, a nucleus |
| `muted` | A grey from the text palette | Inactive, past, background parts |

Paint carries meaning: one colour per role, the same colour for the same thing in every stage and every figure
of a lesson. Parts that have no role stay unpainted. Nested paints work: a teal cell with a dark nucleus is
`groupSvg([body, groupSvg([nucleus], { "data-paint": "dark" })], { "data-paint": "teal" })`. A name that is
not in the table paints nothing.

```js
const chromatids = pieces.map(({ piece, n }) => k.groupSvg([tubeSvg(piece)], { "data-paint": n ? "teal" : "amber" }));
```

## Tones

Within a paint, or in the plain greys, every stroke is a tone: how much it stands out, resolved by the theme.

| Element | Tone |
|---|---|
| Ground, support, surroundings, where the thing has them; minor ticks | `lo` |
| Structure around the subject: a frame, a case, a vessel wall, a membrane; major ticks | `mid` |
| The subject: the thing being explained; zero mark, pointer | `hi` |
| The one part the reader should watch now | `lit` (one only; a solid with `lit: true` gets a bright edge and a lighter top) |
| Grooves, inset outlines, floor grid, faint texture | `faint` |
| Small dots: screws, pores, ribosomes | dots `mid` at 0.4 to 0.55 |
| A line that carries meaning on its own: a flow, a force, a signal | `accent` (the site's teal), `warm` (amber), `alert` (danger) |

## Painter's order

- Whatever holds the rest first, then everything on or in it.
- Within a level, sort by `depthOf(centre, P)` ascending: far before near. A tube piece carries `mid` and a blob carries `depth`; sort them with the solids.
- A part that wraps another (a spring around a rod, a frame around a carriage, a sheath around a cable) is split: back half, the inner part, front half.
- A vertical part passing through a horizontal one (a post through a clamp) is two segments, below and above.
- On a stepped surface, taller steps go further back.

## What makes it crafted

1. **The real thing, drawn as itself.** Named at a glance, invented for the subject, made of the family of parts it is made of: a cell is a soft body, not a box; a chromosome is two bent rods, not posts on a plate.
2. **The parts it really has, each with a job.** A built thing: feet, rails, stops, bushings, knobs, a label plate; thirty to sixty solids is a good figure. A living thing: arms, lobes, vessels, organelles, as many as it has. Density comes from structure, not texture.
3. **Volume.** Real thickness, shaded sides, lighter tops, a bevel that catches light on a hard edge, a halo under a thing that stands on a floor.
4. **Calm.** Thin lines, one lit accent, nothing moving unless it moves in the real thing.
5. **Every line lands on something.** No connector that stops short, no crease that ends before a corner, no texture that stops dead on a surface: a seam runs edge to edge round the visible corners, ticks hang from a ruler's edge, a texture that must end fades out.

Not in the drawing: leader lines, numbered balloons, dimension arrows, hatching, dashed hidden edges, see-through
boxes, floating labels. At most one tiny engraved label on a face. The names of the parts go in the caption and
the alt text.
