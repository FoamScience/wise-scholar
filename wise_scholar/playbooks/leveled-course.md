+++
title = "Leveled course"
summary = "A long course in levels with tracked progress: reading and listening, writing, grammar and vocabulary, and fluency practice in balance."
fits = "Natural languages, and other large skills with recognised proficiency levels that take months. Rank first for learning a natural language. Rank low for a topic that fits in a few sittings."

[[evidence]]
source = "Nation 2007"
finding = "A well designed language course balances four strands (meaning-focused input, meaning-focused output, language-focused learning, fluency development) with roughly equal time for each."
url = "https://doi.org/10.2167/illt039.0"

[[evidence]]
source = "Lyster & Saito 2010"
finding = "A meta-analysis of 15 classroom studies found that corrective feedback has lasting effects and that prompts have larger effects than recasts. It covers oral feedback only; this course applies it to writing."
url = "https://doi.org/10.1017/S0272263109990520"

[[evidence]]
source = "Lyster & Ranta 1997"
finding = "In immersion classrooms recasts were the most frequent feedback type and the least likely to lead to learner repair; elicitation, metalinguistic feedback, clarification requests and repetition led to more."
url = "https://doi.org/10.1017/s0272263197001034"
+++

Run the course as levels made of units. One concept in the course map is one unit. Each unit moves through four strands; the lesson-begins event gives this week's count per strand, so lean on the ones that are behind.

1. Meaning-focused input. Call `next_targets` for the words to work in, then `add_reading`: a short text on the unit's situation that uses each target at least three times, stays inside the learner's vocabulary (the tool refuses a text that does not and lists the words to replace), declares the names it uses, and carries a glossary for the few words above level. Then check understanding of the meaning with `pose_quiz`, in the target language.
2. Meaning-focused output. `pose_writing`: the learner writes a few sentences about the same situation. Push for full sentences and for the unit's structure.
3. Language-focused learning. One grammar point from the unit, taught briefly with `add_block` after the learner has met it in the text and tried it in writing. One `pose_quiz` on it.
4. Fluency. `pose_writing` with `fluency` set: easy, known language, written fast. No new language and no detail correction here.

Speaking, when the lesson-begins event says speaking tasks are available: after the reading, `pose_speaking` with `shadow` on one line of the text; in the output strand, alternate `pose_writing` and `pose_speaking` with `answer`; for fluency, `read` on a known passage. The attempt event lists the words whose sounds were weak. Comment with `give_hint`: marks on those words and a prompt about the sound (which letter group, a known word that has the same sound), never a respelling. `mark_solved` when the words score well enough for the level.

Correcting writing:

- Correct with prompts before recasts. After an attempt, call `give_hint` with `marks` on the faulty pieces and a prompt that names the kind of error and where to look, one error type at a time. Do not write the corrected form.
- The corrected text goes only through `reveal`, after a failed repair or a give-up. Then ask the learner to say what changed.
- When the attempt is good enough for the level, `mark_solved`. Ignore errors that belong to higher levels.

Language of the lesson:

- Write lesson material, quiz questions and chat in the target language at the learner's level. From B1 upward stay in the target language.
- Below B1, give grammar explanations and correction prompts in the learner's own language, and keep everything else in the target language.
- Short sentences, frequent words, one new structure per unit.
