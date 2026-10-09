// Reads {domain, style, substance, attempts?} as JSON on stdin; writes {ok, svg, seed, attempts} or {ok: false, error, rules}.
// Penrose lays a diagram out from a random start, so several seeds are tried and the first settled one is kept.
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

  let best = null;
  let lastError = "";
  for (let seed = 1; seed <= attempts; seed++) {
    const compiled = await compile({ domain: input.domain, style: input.style, substance: input.substance, variation: `seed-${seed}` });
    if (compiled.isErr()) return { ok: false, error: showError(compiled.error), rules: [] };
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
    if (!best || worst < best.worst) best = { state, seed, worst, broken };
    if (broken.length === 0) break;
  }
  if (!best) return { ok: false, error: `the layout never converged: ${lastError}`, rules: [] };
  if (best.broken.length) {
    const rules = [...new Set(best.broken.map((c) => c.rule))];
    return { ok: false, error: `could not lay the diagram out: ${rules.length} rule(s) stay broken after ${attempts} attempts`, rules };
  }
  const svg = await toSVG(best.state, async () => "", "diagram");
  const cropped = svg.querySelector("penrose croppedViewBox")?.textContent;
  if (cropped) {
    const [x, y, w, h] = cropped.split(/\s+/).map(Number);
    svg.setAttribute("viewBox", `${x - MARGIN} ${y - MARGIN} ${w + 2 * MARGIN} ${h + 2 * MARGIN}`);
  }
  svg.querySelector("penrose")?.remove();
  return { ok: true, svg: svg.outerHTML, seed: best.seed };
}

let result;
try {
  result = await main();
} catch (e) {
  result = { ok: false, error: `the renderer failed: ${e?.message ?? e}`, rules: [] };
}
process.stdout.write(JSON.stringify(result));
