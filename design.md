# Design: wise-scholar

The locked system. Every Hallmark run reads this first and screens share it. Change it on purpose; the file is the rule.

## System
- Genre: modern-minimal
- Shape of the first page: app screen (the home screen leads with the sitting agenda)
- Theme: brand (the logo's teal and amber spark, kept)
- Axes: light/grotesk-sans/chromatic-teal · posture: restrained · modes: light+dark (`data-theme`, else the system)

## Tokens
`web/src/tokens.css` is the source of truth. Colours are hex because Mermaid, cytoscape and the print header read them through `getComputedStyle`. The components read the project's own names (`--ground`, `--panel`, `--ink`, `--teal`…), which alias the roles:
```css
:root {
  --color-paper: #f7f9f8;  --color-paper-2: #eef2f1;  --color-paper-3: #e2e8e6;  --color-raised: #fcfdfd;
  --color-ink: #16201f;  --color-ink-2: #2f3b3a;  --color-muted: #52605e;  --color-rule: #d8dfdd;  --color-rule-strong: #7d8a88;
  --color-accent: #0b5f5a;  --color-accent-ink: #f4faf9;  --color-focus: #0e7a72;  --color-warm: #6b3a00;  --color-spark: #f0b35c;
  --font-display: 'Instrument Sans', 'IBM Plex Sans Arabic', system-ui, sans-serif;  --font-body: same;  --font-outlier: 'JetBrains Mono' (code and figures only);
  --radius-card: 10px;  --radius-input: 6px;  --radius-pill: 999px;  --rule-hair: 1px;  --shadow-card: none;  --shadow-float: menus and overlays only;
  --measure: 40rem (reading column);  --page: 72rem (home with its rail);
}
```
The spacing scale (`--space-3xs` 2px to `--space-4xl` 144px), the 1.2 type scale from 16px, the easings and the durations live in `tokens.css`. Weights: 400 and 600.

## Surfaces
Whitespace, then a hairline (`.block` is a ruled section), then a well (`--well`: hints, answers, the sitting agenda, the course map), then a card (course cards, a question awaiting its answer, the claim panel). Never a card in a card.

## Controls
- Primary: teal fill · 6px radius · 44px (48px in the topic form) · one per screen
- Secondary: raised fill, `--line-strong` edge · same radius and height
- Labels: the body face at 14px, 600, sentence case; no tracked capitals, no middle-dot meta strings

## Motion
- Character: brisk; colour and a 1px press only; under reduced motion everything ends at once.

## Exports
`web/src/tokens.css` in this project.
