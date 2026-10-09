// Reads a JSON job on stdin and writes a JSON result: {domain, style, substance} → {ok, svg, seed} for one diagram,
// {domain, style, stages: [substance...]} → {ok, svg, frames} for an animation whose frames are laid out one after the
// other with continuity and joined by SMIL. Failures: {ok: false, error, rules}. Penrose lays a diagram out from a
// random start, so several seeds are tried and the first settled one is kept.
import "global-jsdom/register";
import { compile, evalFns, optimize, showError, toSVG } from "@penrose/core";

// jsdom has no 2D canvas; text is measured as 0.55 em per character, enough for placement.
HTMLCanvasElement.prototype.getContext = function () {
  const ctx = { font: "", textBaseline: "" };
  ctx.measureText = (text) => {
    const size = Number(/(\d+(?:\.\d+)?)px/.exec(ctx.font)?.[1] ?? 16);
    return { width: text.length * size * 0.55, actualBoundingBoxAscent: size * 0.8, actualBoundingBoxDescent: size * 0.2 };
  };
  return ctx;
};

// Penrose scores each constraint as a penalty that is 0 when met and grows with the violation (squared for `equal`,
// in canvas units for `contains` and `disjoint`); a penalty up to 1 is below a pixel of the 900-wide canvas.
const SETTLED = 1;
const MARGIN = 16;
const ANIMATED = ["x", "y", "cx", "cy", "x1", "y1", "x2", "y2", "width", "height", "r", "rx", "ry", "fill", "stroke", "opacity", "fill-opacity", "stroke-width"];
const ENOUGH = 4; // settled candidates to choose the most continuous one from, for the stages after the first
const HOLD = 0.3; // share of a stage's time spent still before gliding to the next
const SECONDS_PER_STAGE = 3;
const SVG_NS = "http://www.w3.org/2000/svg";

class Refused extends Error {
  constructor(error, rules = []) {
    super(error);
    this.rules = rules;
  }
}

async function main() {
  const input = JSON.parse(await new Promise((resolve) => {
    let data = "";
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
  }));
  const attempts = input.attempts ?? 12;
  const styleLines = input.style.split("\n");
  const ruleText = (fn) => {
    const line = fn?.ast?.start?.line;
    return line ? styleLines[line - 1]?.trim() ?? `style line ${line}` : "a rule";
  };

  // Every seed is laid out; a stage of an animation then keeps, among the settled ones, the layout whose shapes moved
  // least since the previous frame, so the frames glide instead of crossing.
  async function layout(substance, previousFrame) {
    const previous = previousFrame ? named(previousFrame) : null;
    const candidates = [];
    let lastError = "";
    for (let seed = 1; seed <= attempts; seed++) {
      const compiled = await compile({ domain: input.domain, style: input.style, substance, variation: `seed-${seed}` });
      if (compiled.isErr()) throw new Refused(showError(compiled.error));
      const optimized = optimize(compiled.value);
      if (optimized.isErr()) {
        lastError = showError(optimized.error);
        continue;
      }
      const state = optimized.value;
      // evalFns scores state.constrFns in order, one penalty per constraint.
      const { constrEngs } = evalFns(state);
      const broken = constrEngs.map((energy, i) => ({ energy, rule: ruleText(state.constrFns[i]) })).filter((c) => c.energy > SETTLED);
      const worst = Math.max(0, ...broken.map((c) => c.energy));
      const svg = await toSVG(state, async () => "", "diagram");
      candidates.push({ seed, worst, broken, svg, moved: previous ? displacement(previous, named(svg)) : 0 });
      const settledSoFar = candidates.filter((c) => c.broken.length === 0).length;
      if (settledSoFar >= (previous ? ENOUGH : 1)) break;
    }
    if (!candidates.length) throw new Refused(`the layout never converged: ${lastError}`);
    const settled = candidates.filter((c) => c.broken.length === 0);
    if (!settled.length) {
      candidates.sort((a, b) => a.worst - b.worst);
      const rules = [...new Set(candidates[0].broken.map((c) => c.rule))];
      throw new Refused(`could not lay the diagram out: ${rules.length} rule(s) stay broken after ${attempts} attempts`, rules);
    }
    settled.sort((a, b) => a.moved - b.moved);
    return settled[0];
  }

  if (input.stages) {
    const frames = [];
    for (const [i, substance] of input.stages.entries()) {
      try {
        frames.push((await layout(substance, frames.at(-1))).svg);
      } catch (e) {
        if (e instanceof Refused) throw new Refused(`stage ${i + 1}: ${e.message}`, e.rules);
        throw e;
      }
    }
    const animation = animate(frames);
    const box = animation.querySelector("penrose croppedViewBox")?.textContent;
    return { ok: true, svg: finish(animation), frames: frames.map((f) => finish(f, box)) };
  }
  const best = await layout(input.substance);
  return { ok: true, svg: finish(best.svg), seed: best.seed };
}

/** The SVG as stored: cropped to its content (or to the box given, the same for every frame of an animation),
 * Penrose metadata and shape titles gone. */
function finish(svg, box) {
  const cropped = box ?? svg.querySelector("penrose croppedViewBox")?.textContent;
  if (cropped) {
    const [x, y, w, h] = cropped.split(/\s+/).map(Number);
    svg.setAttribute("viewBox", `${x - MARGIN} ${y - MARGIN} ${w + 2 * MARGIN} ${h + 2 * MARGIN}`);
  }
  svg.querySelector("penrose")?.remove();
  for (const t of svg.querySelectorAll("title")) t.remove();
  return svg.outerHTML;
}

/** Shapes by the Substance object and field they stand for, which Penrose writes as each shape's <title>. */
function named(svg) {
  const map = new Map();
  for (const el of svg.querySelectorAll("*")) {
    const title = el.querySelector(":scope > title")?.textContent;
    if (title) map.set(title, el);
  }
  return map;
}

function displacement(a, b) {
  let total = 0;
  for (const [title, el] of a) {
    const other = b.get(title);
    if (!other) continue;
    for (const attr of ["x", "y", "cx", "cy", "x1", "y1", "x2", "y2"]) {
      const u = el.getAttribute(attr), v = other.getAttribute(attr);
      if (u !== null && v !== null) total += Math.abs(Number(u) - Number(v));
    }
  }
  return total;
}

/** The first frame with SMIL animations onto every attribute that changes across frames; texts whose string changes
 * are switched. The viewBox grows to hold every frame. */
function animate(frames) {
  const master = frames[0].cloneNode(true); // the first frame stays a plain frame
  const maps = [named(master), ...frames.slice(1).map(named)];
  const doc = master.ownerDocument;
  const n = frames.length;
  const dur = SECONDS_PER_STAGE * n;
  const stageTimes = Array.from({ length: n }, (_, i) => (i / n).toFixed(3));
  for (const [title, el] of maps[0]) {
    if (/^rotate\(0[,\s]/.test(el.getAttribute("transform") ?? "")) el.removeAttribute("transform"); // an identity Penrose writes on every rect
    const others = maps.slice(1).map((m) => m.get(title));
    if (others.some((o) => !o)) continue;
    for (const attr of ANIMATED) {
      const values = [el, ...others].map((e) => e.getAttribute(attr));
      if (values[0] === null || values.every((v) => v === values[0])) continue;
      const seq = [], times = [];
      values.forEach((v, i) => {
        seq.push(v, v);
        times.push((i / n).toFixed(3), ((i + HOLD) / n).toFixed(3));
      });
      seq.push(values[0]);
      times.push("1");
      const a = doc.createElementNS(SVG_NS, "animate");
      a.setAttribute("attributeName", attr);
      a.setAttribute("values", seq.join(";"));
      a.setAttribute("keyTimes", times.join(";"));
      a.setAttribute("dur", `${dur}s`);
      a.setAttribute("repeatCount", "indefinite");
      a.setAttribute("calcMode", "spline");
      a.setAttribute("keySplines", Array(seq.length - 1).fill("0.4 0 0.2 1").join(";"));
      el.appendChild(a);
    }
    const texts = [el, ...others].map((e) => (e.tagName === "text" ? ownText(e) : null));
    if (el.tagName === "text" && texts.some((t) => t !== texts[0])) {
      for (const node of [...el.childNodes]) if (node.nodeType === 3) node.remove();
      texts.forEach((text, i) => {
        const span = doc.createElementNS(SVG_NS, "tspan");
        span.textContent = text;
        span.setAttribute("opacity", i === 0 ? "1" : "0");
        const a = doc.createElementNS(SVG_NS, "animate");
        a.setAttribute("attributeName", "opacity");
        const shown = stageTimes.map((_, j) => (j === i ? "1" : "0"));
        a.setAttribute("values", [...shown, shown[0]].join(";"));
        a.setAttribute("keyTimes", [...stageTimes, "1"].join(";"));
        a.setAttribute("calcMode", "discrete");
        a.setAttribute("dur", `${dur}s`);
        a.setAttribute("repeatCount", "indefinite");
        span.appendChild(a);
        el.appendChild(span);
      });
    }
  }
  const boxes = frames.map((f) => f.querySelector("penrose croppedViewBox")?.textContent.split(/\s+/).map(Number)).filter(Boolean);
  if (boxes.length === frames.length) {
    const x = Math.min(...boxes.map((b) => b[0])), y = Math.min(...boxes.map((b) => b[1]));
    const right = Math.max(...boxes.map((b) => b[0] + b[2])), bottom = Math.max(...boxes.map((b) => b[1] + b[3]));
    master.querySelector("penrose croppedViewBox").textContent = `${x} ${y} ${right - x} ${bottom - y}`;
  }
  master.setAttribute("data-stages", String(n));
  master.setAttribute("data-seconds", String(dur));
  return master;
}

function ownText(el) {
  return [...el.childNodes].filter((c) => c.nodeType === 3).map((c) => c.textContent).join("");
}

let result;
try {
  result = await main();
} catch (e) {
  result = { ok: false, error: e instanceof Refused ? e.message : `the renderer failed: ${e?.message ?? e}`, rules: e instanceof Refused ? e.rules : [] };
}
process.stdout.write(JSON.stringify(result));
