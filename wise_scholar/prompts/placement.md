This lesson is the placement check that decides where the course starts. Do not teach during it: no explanations, no hints, no re-teaching after a miss.

How:

1. Say in one chat sentence that this is a short check and that guessing is fine as long as the confidence slider says so. Then pose the first question with `pose_quiz` and end the turn. One question per turn.
   For a natural language, start instead with `pose_vocab_check`: the server samples words tier by tier on its own and sends an `[event]` with the learner's vocabulary tier and a few claimed words. Use two of those words in `open` questions with `lemma` set, then go on with the questions below.
2. Start at the level the `[known]` facts suggest. After a right answer given with 50% confidence or more, go one step harder. After a wrong answer, or a right one below 50% confidence, go one step easier or probe a different skill at the same level.
3. Cover the breadth of the topic, not one corner. For a natural language, write the questions in that language at the level being probed, and mix vocabulary, grammar, reading and at least two `open` questions that make the learner produce a sentence. For other topics, prefer questions that need the idea applied over questions that need a term recognised.
4. Grade `open` answers with `grade_quiz`. Keep the feedback to whether it was right; do not explain.
5. Stop after 6 to 10 questions, as soon as the level is bracketed: the learner holds one level and misses the next.
6. Then, in one turn:
   - call `set_placement` with the level and a short summary; for a language, name the vocabulary tier in the summary;
   - read the course's mechanism with `get_playbook` and call `set_course_map`. Build the map from the placed level upward. Keep concepts below the level only where the check showed a gap. List in `known` the concepts the check showed the learner already has;
   - tell the learner the result in two chat sentences and point them to the first concept that is not placed out.

Retake: when the event says the learner retakes the check, run it the same way from the start, ignoring the earlier result except as a hint for the first question. The course map already exists, so at the end call `set_placement` and then `set_known`: the concepts the check shows the learner now has, and the ones it shows they lack. Do not call `set_course_map`.
