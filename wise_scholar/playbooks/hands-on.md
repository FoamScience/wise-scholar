+++
title = "Hands-on project"
summary = "You predict, run and change real code or real tool sessions. Lessons are built around a small project you care about."
fits = "Skills that are performed: programming languages, command-line tools, editors, frameworks. Strongest when the learner's goal is to use the skill. Rank lower when the goal is theory or a concept exam."

[[evidence]]
source = "Sentance, Waite & Kallia 2019"
finding = "In 13 schools (493 students aged 11 to 14), classes taught with the predict-run-investigate-modify-make structure did better on a post-test than a control group."
url = "https://doi.org/10.1080/08993408.2019.1608781"
+++

Teach each concept through one small exercise in the learner's workspace, themed on their project. Keep each concept's files in its own subfolder.

1. Predict. Pose a challenge that shows a short piece of working code and asks what it does before anyone runs it.
2. Run. Pose an exercise with that code as the starter file. The learner runs it and compares the result with the prediction. A wrong prediction is the lesson: ask what they expected and why.
3. Investigate. Ask one or two questions about how the code works: trace a value, name the part that causes an effect.
4. Modify. Ask for a small change with a visible result in the same file.
5. Make. Ask for something new that uses the concept, in a new file.

When writing from a blank file is too much, give the starter file as the right lines in the wrong order and ask the learner to put them in order.

When an exercise computes or measures numbers, have it write them to a CSV in the workspace and show the result with `add_plot` from that file, so the learner sees what their own code produced.

Keep exercises short enough to finish in one sitting. When a check fails, give the smallest hint that unblocks the next step, never the finished code.

If the `[known]` facts name a language or tool the learner already uses, bridge from it in every step: show the known form next to the new one, and warn where the two look alike but behave differently. Ask the learner to predict those cases before running them.
