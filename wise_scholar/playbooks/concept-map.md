+++
title = "Concept map and teach-back"
summary = "You get a map of the field and its prerequisites, learn one concept at a time through questions, and prove it by explaining it back."
fits = "Large conceptual fields where the relations between ideas matter: a science, a theory, a body of history or law. Strongest when the goal is to understand or explain. Rank lower when the goal is to perform a skill."

[[evidence]]
source = "Chi, de Leeuw, Chiu & LaVancher 1994"
finding = "Fourteen eighth-graders prompted to explain each line of a text to themselves gained more from pretest to posttest than ten controls who read the text twice."
url = "https://doi.org/10.1207/s15516709cog1803_3"

[[evidence]]
source = "Chi & Wylie 2014"
finding = "The ICAP hypothesis: learning increases as engagement moves from passive to active to constructive to interactive, supported with laboratory and classroom studies."
url = "https://doi.org/10.1080/00461520.2014.965823"

[[evidence]]
source = "Nesbit & Adesope 2006"
finding = "A meta-analysis of 55 studies (5,818 participants) found that using concept maps was associated with better knowledge retention, with effects from small to large depending on use and comparison."
url = "https://doi.org/10.3102/00346543076003413"
+++

Start by laying out the field as concepts with prerequisite links: draw it as a `mermaid` `flowchart LR` (or a `mindmap`) in a prose block, concepts as nodes and prerequisites as arrows, and agree on a path with the learner. Redraw the map at the start of each concept with the learned ones marked (`:::done` with a `classDef done`), and ask the learner to add the link they see.

For each concept:

1. Ask what the learner already believes about it. Start from that answer.
2. Lead with questions toward the idea. Give a short explanation only for what questions cannot reach.
3. Ask the learner to connect it to an earlier concept on the map.
4. Teach-back gate. `pose_teachback`: the learner explains the concept in plain words in about a minute, as if to a newcomer, spoken or typed. Probe the weakest part of the explanation with `give_hint`. The concept counts as learned only after a sound explanation (`mark_solved`).

When a concept is a structure with parts (an organ, a machine, a protocol stack), show it with `add_figure` before the questions, and ask the learner to point to the part a question is about.

Name common misconceptions directly and ask the learner why they are tempting.
