# The research behind wise-scholar

This page lists what each teaching behaviour in the app relies on, what the cited source reports, and how far that finding reaches. It was checked on 2026-10-02; the practice forms on 2026-10-13.

How each source was checked:

- **Abstract read**: the bibliographic record and the abstract (or the paper) were opened, and the finding below restates what the abstract reports.
- **Record only**: authors, year, venue and DOI were confirmed, but the content was not read. The description comes from secondary sources or from the general reputation of the work, and is marked as such.

Nothing here is cited from memory alone. Sources that could not be confirmed are listed at the end and are not used as evidence in the app.

## What the app does not claim

The app does not promise the "two sigma" effect. Bloom (1984) reported that one-to-one tutoring with mastery learning put students about two standard deviations above conventional classes, based on small, short studies by his own graduate students ([doi:10.3102/0013189X013006004](https://doi.org/10.3102/0013189X013006004), record only). VanLehn's later review found a much smaller effect for human tutoring, d = 0.79, and d = 0.76 for intelligent tutoring systems ([doi:10.1080/00461520.2011.611369](https://doi.org/10.1080/00461520.2011.611369), abstract read). A realistic expectation for good tutoring is well under one standard deviation.

## Always-on behaviours

### A pretest before each concept

| Source | What it reports | Limits |
|---|---|---|
| Richland, Kornell & Kao 2009, *Journal of Experimental Psychology: Applied* 15(3), 243–257. [doi:10.1037/a0016496](https://doi.org/10.1037/a0016496). Record only. | Described as finding that answering questions about a text before reading it, even wrongly, improved later recall of those points compared with reading alone. | The record was confirmed on 2026-10-03; the abstract was not retrieved, so the description comes from secondary sources. Laboratory reading studies. |
| Kapur 2008, *Cognition and Instruction* 26(3), 379–424. [doi:10.1080/07370000802212669](https://doi.org/10.1080/07370000802212669). Record only. | Described as finding that students who first struggled with ill-structured problems, then received instruction, outperformed students taught first, on later problems. | Record confirmed on 2026-10-03; abstract not retrieved. School mathematics classes. |

The app opens every concept lesson with a pretest the learner attempts before any explanation; the attempt is recorded but creates no review card and does not count toward mastery.

### The error notebook

| Source | What it reports | Limits |
|---|---|---|
| Metcalfe 2017, *Annual Review of Psychology* 68, 465–489. [doi:10.1146/annurev-psych-010416-044022](https://doi.org/10.1146/annurev-psych-010416-044022). Abstract read. | A review: errorful learning followed by corrective feedback helps learning, and errors made with high confidence are corrected more readily than low-confidence ones; feedback that analyses the reasoning behind the mistake matters. | A review of laboratory studies, mostly with typical adult learners; it argues from the literature rather than testing a notebook. |

Confident misses and corrected texts go into a notebook with the learner's own note; open entries lead the review queue and are named to the tutor at the start of later lessons.

### Hints before answers

| Source | What it reports | Limits |
|---|---|---|
| Sinha & Kapur 2021, *Review of Educational Research* 91, 761–798. [doi:10.3102/00346543211019105](https://doi.org/10.3102/00346543211019105). Abstract read. | A meta-analysis of 53 studies (166 comparisons) found a moderate effect in favour of solving problems before instruction, Hedges g = 0.36 (95% CI 0.20 to 0.51), rising to 0.37–0.58 when the design followed productive-failure principles closely. | The benefit depends on how faithfully the method is implemented and on age; the abstract notes a contrasting trend for grades 2–5. |
| Kapur 2008, *Cognition and Instruction* 26(3), 379–424. [doi:10.1080/07370000802212669](https://doi.org/10.1080/07370000802212669). Record only. | Described as an existence proof that attempting problems before instruction can pay off even when the attempts fail. | Content not read beyond that framing. |
| Kornell, Hays & Bjork 2009, *JEP: Learning, Memory, and Cognition* 35(4), 989–998. [doi:10.1037/a0015729](https://doi.org/10.1037/a0015729). Abstract summary read. | Trying to retrieve an answer and failing, then being told it, led to better later learning than studying the answer alone. | Laboratory work with word pairs and trivia-style items. Applying it to programming or conceptual learning is an extrapolation. |
| Bastani et al. 2025, *PNAS* 122. [doi:10.1073/pnas.2422633122](https://doi.org/10.1073/pnas.2422633122). Abstract read. | In a field experiment with nearly 1,000 high-school mathematics students, access to GPT-4 raised practice grades by 48% (plain chat) and 127% (a tutor version with safeguards). Once access was removed, the plain-chat group scored 17% below students who never had access; the tutor version's safeguards largely removed that harm. | One study, one subject. The abstract says the safeguards were designed to protect learning; it was not checked whether the paper describes them as "hints instead of answers". |

The reveal gate in the app (the solution opens after attempts or a give-up) is this app's own design. No source above tests that exact rule.

### Confidence-rated quick checks

| Source | What it reports | Limits |
|---|---|---|
| Butterfield & Metcalfe 2001, *JEP: Learning, Memory, and Cognition* 27(6), 1491–1494. [doi:10.1037/0278-7393.27.6.1491](https://doi.org/10.1037/0278-7393.27.6.1491). Abstract read. | After correct-answer feedback, errors made with high confidence were the most likely to be corrected on a later test. | A short report on general-knowledge questions. |
| Roediger & Karpicke 2006, *Psychological Science* 17(3), 249–255. [doi:10.1111/j.1467-9280.2006.01693.x](https://doi.org/10.1111/j.1467-9280.2006.01693.x). Abstract read. | Students who took recall tests on prose passages remembered more after 2 days and after 1 week than students who restudied. After 5 minutes, restudying was better, and it also made students more confident. | Prose passages and free recall. |

The hypercorrection finding says confident errors are corrected readily once feedback is given. It does not say they need shorter review intervals. The app therefore re-teaches a confident miss at once and lists it first in the review queue, but schedules it like any other miss.

The mapping from correctness and confidence to a review rating (wrong = again, right but unsure = hard, right = good, right and certain = easy) is a heuristic of this app, not a research result.

### Spaced review

| Source | What it reports | Limits |
|---|---|---|
| Cepeda, Pashler, Vul, Wixted & Rohrer 2006, *Psychological Bulletin* 132(3), 354–380. [doi:10.1037/0033-2909.132.3.354](https://doi.org/10.1037/0033-2909.132.3.354). Abstract read. | A synthesis of 839 assessments from 317 experiments found that the gap between study sessions that gives the best retention grows with the retention interval. | Verbal recall tasks only. |
| Ye, Su & Cao 2022, KDD '22, 4381–4390. [doi:10.1145/3534678.3539081](https://doi.org/10.1145/3534678.3539081). Abstract read. | A memory model built from the review logs of 220 million learners and a scheduler that minimises review cost, reported as 12.6% better than earlier methods. | This paper is the ancestor of the scheduler, not the scheduler itself. The [FSRS project](https://github.com/open-spaced-repetition/free-spaced-repetition-scheduler) states that FSRS "springs from MaiMemo's DHP model" from this paper, a variant of Wozniak's DSR model. The app uses the `fsrs` library with its default parameters. |

### A warm-up at the start of a sitting

| Source | What it reports | Limits |
|---|---|---|
| Pastötter & Frings 2019, *Journal of Cognition* 2(1), 37. [doi:10.5334/joc.82](https://doi.org/10.5334/joc.82). Abstract read. | Participants studied three word lists. Being tested on lists 1 and 2, instead of restudying them, improved immediate recall of list 3, which the authors call the forward testing effect. The effect held on retest between two sessions and did not depend on working-memory capacity. | Word lists recalled within one session. Whether reviews of other courses help a different lesson that follows is an extrapolation. |

After two hours or more with no answer, no run of their own code and no tutor turn, the sitting opens with up to 5 due review cards from all the learner's courses, mixed, with confident misses and open notebook errors first, whether it starts from Today's Start or from opening a course. A skipped warm-up is not offered again within the sitting, and the rest of the due cards wait on the review page. The reviews themselves rest on the spacing and testing sources above. Placing them before the lesson rests on the forward testing effect, which was measured with word lists, not with lessons. The cap of 5 and the two-hour gap are this app's own choices, not taken from any source; they are an experiment to drop if the warm-up turns out to keep learners from starting the lesson.

### A recap after a break

Back at an unfinished unit after three days or more, the learner first gets a short "where you were" note, then two recall checks on what came before the break, then the unit goes on. The checks are retrieval practice after a delay, which rests on the testing and spacing sources under "Confidence-rated quick checks" and "Spaced review". The note itself, and the three-day threshold, are this app's own choices with no source behind them: an experiment, to drop if learners skip past the note or the checks keep them from going on.

### A unit's outline and step counter

| Source | What it reports | Limits |
|---|---|---|
| Luiten, Ames & Ackerson 1980, *American Educational Research Journal* 17(2), 211–218. [doi:10.3102/00028312017002211](https://doi.org/10.3102/00028312017002211). Abstract read. | Across 135 published and unpublished studies, advance organizers (an overview given before the material) helped both learning and retention; grade level, subject, how the organizer was presented and ability level were examined as influences. | Advance organizers as studied are introductory material that relates the new content to what learners know, which is more than a list of steps. The abstract gives no effect size here. |

Each unit opens with 3 to 6 named steps, and a counter shows the step the learner is on. The outline's link to advance organizers is loose, since a list of steps relates little to prior knowledge. The counter, the cap of one added step and the rule that the tutor says why it added one rest on no source: they answer the learner's complaint that units felt long with no visible end, and are an experiment to drop if they do not help learners finish units.

### Progress on the course map

The course map tops its list with the units done and how many units have reviews due, and each unit shows where the learner stands: not started, the step it is on, or done, with its mastery squares and its due reviews. No source above tests a progress display like this; it answers the learner's complaint that they could not see where they stood, and is an experiment to drop if it does not help learners come back to their reviews and finish units.

### One lesson stream, the chat on demand

The tutor's messages and the learner's run inline in the lesson, between the cards they belong to, and the box to write to the tutor opens as a drawer only when the learner asks (it starts open in the interview, which is a conversation). The aim is to keep what the tutor says next to what it is about instead of in a second column, which is the idea behind the split-attention and spatial-contiguity research; no abstract of that research was read for this, so it is not cited, and the layout is an experiment to drop if learners lose track of the conversation.

### Momentum and speed

Each course runs at the pace the learner picks, momentum by default. Momentum keeps units to about 15 minutes with no step skipped; speed allows longer units and lets the learner test out of a step or a whole unit by answering its checks before its teaching, a check counting as known when right at 70% confidence or more. Testing out rests on the expertise reversal source under "Worked example, then solo" (Kalyuga, Ayres, Chandler & Sweller 2003): guidance that helps novices can hinder learners who already know the material. The unit lengths, the 70% bar and the choice between two paces are this app's own and an experiment, to drop if speed mode skips steps learners later miss in reviews.

### How sure against how right, at the end of a sitting

"End sitting" (and, when the learner just left, the next sitting's warm-up) shows one line for the sitting, how sure the learner said they were on average against how often they were right, and lists the questions they were sure of and missed. It builds on the confidence ratings and the hypercorrection source under "Confidence-rated quick checks", which make the confident misses worth a second look. Whether showing the gap itself makes learners better calibrated is not tested by any source read here; it is an experiment, to drop if the learner's confidence and accuracy do not move closer over sittings.

### The opening interview

| Source | What it reports | Limits |
|---|---|---|
| Pashler, McDaniel, Rohrer & Bjork 2008, *Psychological Science in the Public Interest* 9(3), 105–119. [doi:10.1111/j.1539-6053.2009.01038.x](https://doi.org/10.1111/j.1539-6053.2009.01038.x). Abstract read. | Virtually no evidence that matching instruction to a learner's preferred style improves learning; the evidence does not justify style assessments in education. | "Insufficient evidence", not "disproven": few studies of the required design exist. This is why the interview asks about knowledge, goals and interests and never about a learning style. |
| Walkington 2013, *Journal of Educational Psychology* 105(4), 932–945. [doi:10.1037/a0031882](https://doi.org/10.1037/a0031882). Record and summary read. | 145 algebra students given story problems matched to their interests performed better, wrote expressions faster and gamed the tutoring system less than students given standard problems. | One study in one tutoring system. The reported gains are performance and process measures; a separate learning gain was not confirmed. |
| Ausubel 1968, *Educational Psychology: A Cognitive View*. Holt, Rinehart and Winston. Secondary sources only. | The book's epigraph is quoted as: "The most important single factor influencing learning is what the learner already knows. Ascertain this and teach him accordingly." | Quoted from secondary sources; the book itself was not opened. A statement of principle, not a measured effect. |

## Practice forms

Forms added on 2026-10-13, each checked the same way.

### Successive relearning

| Source | What it reports | Limits |
|---|---|---|
| Rawson & Dunlosky 2011, *Journal of Experimental Psychology: General* 140(3), 283–302. [doi:10.1037/a0023956](https://doi.org/10.1037/a0023956). Abstract read. | Across 3 experiments, 533 students learned conceptual material by retrieval practice with restudy. Items were practised to 1 to 4 correct recalls in a first session and then relearned to 1 correct recall in 1 to 5 later sessions. Relearning had pronounced effects on long-term retention (tested 1 to 4 months later) at a relatively small cost in extra practice trials. The authors' advice is to practise to 3 correct recalls and then relearn 3 times at widely spaced intervals. | Laboratory work with short-answer recall of concept definitions. The advice is three relearning sessions at wide spacing; the app's rule (right on three separate days, interval held to a day until then) is its own adaptation, not a tested schedule. |
| Rawson, Dunlosky & Sciartelli 2013, *Educational Psychology Review* 25(4), 523–548. [doi:10.1007/s10648-013-9240-4](https://doi.org/10.1007/s10648-013-9240-4). Record only. | Described as testing successive relearning with introductory psychology students using a flashcard program, comparing it with ordinary study on in-class exam performance and later retention. | The record was confirmed on 2026-10-13 and only the first sentence of the abstract was retrieved (practice tests and spacing across days combined are called successive relearning). The results come from secondary descriptions, so no effect is quoted. One course, one subject. |

Each review card must be recalled correctly on three separate days before its interval may grow past a day, a miss starts the count over, and a vocabulary word tied to a card counts as known only once it has been relearned that way.

### Mixed practice units

| Source | What it reports | Limits |
|---|---|---|
| Rohrer & Taylor 2007, *Instructional Science* 35(6), 481–498. [doi:10.1007/s11251-007-9015-8](https://doi.org/10.1007/s11251-007-9015-8). Abstract read. | Two experiments. Practice spread over several sessions beat practice massed into one session on a test a week later. Students who practised a mix of problem types did far better a week later than students who practised one type at a time. | The abstract was read through a repository record that gives it in part and as a summary. Adult students and mathematics problems with a fixed procedure per type. |
| Taylor & Rohrer 2010, *Applied Cognitive Psychology* 24(6), 837–848 (first published online 2009). [doi:10.1002/acp.1598](https://doi.org/10.1002/acp.1598). Abstract read. | Interleaving practice impaired performance during practice yet doubled scores on a test one day later. Interleaving improved the ability to pair each problem with the right procedure, and the study separates this from the effect of spacing. | The abstract was read in excerpts, so the sample and the exact scores were not confirmed. Short delay (one day); mathematics problems. |
| Rohrer, Dedrick & Stershic 2015, *Journal of Educational Psychology* 107(3), 900–908. [doi:10.1037/edu0000001](https://doi.org/10.1037/edu0000001). Abstract read. | In a classroom experiment, 126 seventh-grade students had the same practice problems over 3 months, interleaved or blocked. On an unannounced test 1 or 30 days after a review session, interleaving scored higher on both tests (Cohen's d 0.42 after 1 day and 0.79 after 30 days). | One school subject (mathematics), school-age pupils. The app mixes tasks across units in a practice unit that teaches nothing; the study did not test that format. |

After every third unit, a practice unit poses varied versions of the earlier units' solved tasks, mixed across units and with no teaching; a miss brings that unit's review cards forward. The every-third-unit cadence and the card pull-forward are this app's own design. No source above tests them.

### Compare two solutions

| Source | What it reports | Limits |
|---|---|---|
| Rittle-Johnson & Star 2009, *Journal of Educational Psychology* 101(3), 529–544. [doi:10.1037/a0014224](https://doi.org/10.1037/a0014224). Abstract read. | 162 seventh- and eighth-grade students learned to solve equations by comparing equivalent problems solved the same way, different problem types solved the same way, or different methods for the same problem. Conceptual knowledge and procedural flexibility were best supported by comparing solution methods, and to a lesser extent by comparing problem types. | One topic (algebra equations) with school pupils. The app applies it to programming and other technical solutions, which is an extrapolation. |
| Rittle-Johnson & Star 2007, *Journal of Educational Psychology* 99(3), 561–574. [doi:10.1037/0022-0663.99.3.561](https://doi.org/10.1037/0022-0663.99.3.561). Record only. | Described, by papers that cite it, as an experiment in which seventh-graders compared solution methods side by side or studied the same methods one after the other, with comparison giving more procedural flexibility. | Record confirmed on 2026-10-13; the abstract was not retrieved. The description comes from citing papers, and no sample size or effect is quoted here. |
| Schwartz & Bransford 1998, *Cognition and Instruction* 16(4), 475–522. [doi:10.1207/s1532690xci1604_4](https://doi.org/10.1207/s1532690xci1604_4). Abstract read. | In 3 classroom studies, college students who analysed contrasting cases (simplified experimental designs and data) and then heard a lecture or read a text predicted outcomes of a new experiment more accurately a week later than students who read about the distinctions, summarised a text, or analysed the cases twice without a lecture. The authors say noticing the distinctions creates "a time for telling". | College students and psychology concepts. The study compares cases then telling with other orders; it does not test two correct solutions to one task or a prompt for when each wins. |

In a technical course, after a solved task, the app shows two correct solutions side by side; the learner says what differs and when each one wins. The "when each one wins" prompt is this app's own design.

### Sort into categories

| Source | What it reports | Limits |
|---|---|---|
| Kornell & Bjork 2008, *Psychological Science* 19(6), 585–592. [doi:10.1111/j.1467-9280.2008.02127.x](https://doi.org/10.1111/j.1467-9280.2008.02127.x). Abstract read. | Participants studied paintings by several artists, either one artist at a time or interleaved. Later, when asked which artist painted new paintings, they did better after interleaved study, even though they rated the one-at-a-time study as more effective. | Adults learning painting styles, a perceptual category task. Applying it to text or code categories is an extrapolation. |
| Kang & Pashler 2012, *Applied Cognitive Psychology* 26(1), 97–103 (first published online 2011). [doi:10.1002/acp.1801](https://doi.org/10.1002/acp.1801). Abstract read. | Spacing paintings out in time while keeping them blocked by artist did no better than massed study, and both did worse than interleaving. Showing paintings by different artists at the same time did as well as interleaving. The authors conclude the benefit comes from discriminative contrast between the styles, not from time spacing as such. | Same painting-style task as above. |
| Chi, Feltovich & Glaser 1981, *Cognitive Science* 5(2), 121–152. [doi:10.1207/s15516709cog0502_2](https://doi.org/10.1207/s15516709cog0502_2). Abstract read. | In four experiments using sorting tasks and protocols, experts and novices began from different problem categories: experts abstracted physics principles, novices relied on the problem's literal features. | A description of how experts and novices sort, not a test of whether sorting practice teaches. Physics problems. |

The learner places 6 to 12 items into 2 to 4 categories. The server grades placement by placement and marks misplaced items without naming their category. The tutor then shows one pair of items that tells the categories apart, the misplaced items are sorted again, and the sort comes back in spaced reviews. No source above tests this exact sequence. Hiding the correct category and the single contrasting pair are this app's own design, and their link to discriminative contrast is an inference.

### Units taken offline

| Source | What it reports | Limits |
|---|---|---|
| Butler, Karpicke & Roediger 2007, *Journal of Experimental Psychology: Applied* 13(4), 273–281. [doi:10.1037/1076-898X.13.4.273](https://doi.org/10.1037/1076-898X.13.4.273). Abstract read. | After reading 12 prose passages, participants took a six-option multiple-choice test, with feedback on some items given immediately and on others after a delay. On a delayed cued-recall test, delayed feedback led to better performance than immediate feedback. Showing the right answer and letting the participant answer until correct worked equally well. The authors attribute the benefit to the spaced presentation of the information. | Multiple-choice questions on general-knowledge passages, in a lab session. The tutor's later remediation of open answers was not tested. |

The tutor writes the rest of a unit in one turn, with every check carrying its key. The learner answers on the device and sees the key and explanation right after each answer, which is immediate feedback. The tutor comes back to the misses only when the answers are sent, which is delayed. The source supports the delayed part. It gives no reason to prefer the immediate display, which is kept so that a learner offline is not left without any answer. Losing the tutor's adaptation within a unit is a cost that no source above measures.

## Teaching mechanisms

Each playbook in `wise_scholar/playbooks/` carries its own evidence entries, and the plan screen shows them with links. This section repeats them with their limits.

### Hands-on project

| Source | What it reports | Limits |
|---|---|---|
| Sentance, Waite & Kallia 2019, *Computer Science Education* 29(2–3), 136–176. [doi:10.1080/08993408.2019.1608781](https://doi.org/10.1080/08993408.2019.1608781). Abstract read. | In 13 schools (493 students aged 11 to 14, over 8 to 12 weeks), classes taught with the predict-run-investigate-modify-make structure did better on a post-test than a control group, and teachers found it useful in mixed-ability classes. | One study with school pupils, a post-test comparison plus teacher interviews. No effect size was retrieved. Adult learners were not studied. |

Exercises that ask the learner to put scrambled lines in order go back to Parsons & Haden (2006, ACE '06). That paper describes the puzzle tool and argues that it motivates; it is not an effectiveness study, no DOI was found for it, and it is not used as evidence here. Ericson, Margulieux & Rick (2017, [doi:10.1145/3141880.3141895](https://doi.org/10.1145/3141880.3141895)) compare such problems with writing code; that record was confirmed but its finding was not read.

### Crossover from what you know

| Source | What it reports | Limits |
|---|---|---|
| Tshukudu & Cutts 2020, ICER '20, 227–237. [doi:10.1145/3372782.3406270](https://doi.org/10.1145/3372782.3406270). Abstract read. | Students moving between Python and Java had little or no difficulty with concepts whose syntax and meaning both carried over, and the most difficulty where the syntax matched but the meaning differed. Where the syntax differed, little of the meaning transferred even when it was the same. | A model built on two studies of near-novices. |
| Shrestha, Botta, Barik & Parnin 2020, ICSE '20, 691–701. [doi:10.1145/3377811.3380352](https://doi.org/10.1145/3377811.3380352). Abstract read. | 276 of 450 sampled Stack Overflow questions across 18 languages showed interference from assumptions carried over from another language. Sixteen interviewed professionals tried, and often failed, to relate a new language to one they knew. | Observational. The sampled questions were ones where people already had trouble. |

The general idea that analogies carry relational structure from a known domain to a new one is Gentner's structure-mapping theory (1983, [doi:10.1016/S0364-0213(83)80009-3](https://doi.org/10.1016/S0364-0213(83)80009-3), record only).

### Leveled course

| Source | What it reports | Limits |
|---|---|---|
| Nation 2007, *Innovation in Language Learning and Teaching* 1(1), 2–13. [doi:10.2167/illt039.0](https://doi.org/10.2167/illt039.0). Abstract read. | The activities of a language course fall into four strands: meaning-focused input, meaning-focused output, language-focused learning and fluency development. A well designed course gives roughly equal time to each. | A course-design framework argued from the research literature, not an experiment comparing balanced and unbalanced courses. |
| Lyster & Saito 2010, *Studies in Second Language Acquisition* 32(2), 265–302. [doi:10.1017/S0272263109990520](https://doi.org/10.1017/S0272263109990520). Abstract read. | A meta-analysis of 15 classroom studies (827 learners): corrective feedback had lasting effects, prompts had larger effects than recasts, and younger learners benefited more. | Oral feedback in classrooms only. The app applies the prompts-before-recasts idea to written work, which the meta-analysis does not cover. |
| Lyster & Ranta 1997, *Studies in Second Language Acquisition* 19(1), 37–66. [doi:10.1017/s0272263197001034](https://doi.org/10.1017/s0272263197001034). Abstract read. | In 18.3 hours of primary immersion lessons, recasts were the most frequent feedback type and the least likely to lead to learner repair. Elicitation, metalinguistic feedback, clarification requests and repetition led to more. | Oral classroom talk with children. |
| Swain 1985, in Gass & Madden (eds.), *Input in Second Language Acquisition*, 235–253. Secondary sources only. | Described as arguing that comprehensible input alone does not produce full competence and that producing language has its own role, based on immersion students who stayed weak in grammar after years of input. | The chapter was not read. It stresses that output has its own role; it does not measure accuracy gains from writing tasks. |
| Krashen 1985, *The Input Hypothesis: Issues and Implications*. Longman. Record and secondary sources only. | Described as holding that learners acquire language by understanding input one step beyond their current level. | Contested: critics found "comprehensible input" and the one-step-beyond idea too vague to test. The app uses it only as the reason reading texts sit slightly above the learner's level. |

The count of activities per strand shown in the course map is this app's own rough measure. Nation's framework is about time, not counts.

### Worked example, then solo

| Source | What it reports | Limits |
|---|---|---|
| Sweller & Cooper 1985, *Cognition and Instruction* 2(1), 59–89. [doi:10.1207/s1532690xci0201_3](https://doi.org/10.1207/s1532690xci0201_3). Abstract read. | Across five experiments, studying worked algebra examples took less time than solving the same problems, and similar problems were later solved faster and with fewer errors. | The benefit held for problems with the same structure as the examples, so it does not show general transfer. |
| Renkl & Atkinson 2003, *Educational Psychologist* 38(1), 15–22. [doi:10.1207/s15326985ep3801_3](https://doi.org/10.1207/s15326985ep3801_3). Abstract read. | Proposes fading: problem-solving steps are added to example study gradually until the learner solves problems alone, and says empirical evidence supports the procedure. | A theoretical and review article. The abstract does not report a direct comparison with an abrupt switch. |
| Kalyuga, Ayres, Chandler & Sweller 2003, *Educational Psychologist* 38(1), 23–31. [doi:10.1207/s15326985ep3801_4](https://doi.org/10.1207/s15326985ep3801_4). Abstract read. | Techniques that are highly effective for inexperienced learners can lose their effect, or have negative consequences, for more experienced learners. | A review. This is why the mechanism ranks lower for learners with strong prior knowledge. |

### Concept map and teach-back

| Source | What it reports | Limits |
|---|---|---|
| Chi, de Leeuw, Chiu & LaVancher 1994, *Cognitive Science* 18(3), 439–477. [doi:10.1207/s15516709cog1803_3](https://doi.org/10.1207/s15516709cog1803_3). Abstract read. | Fourteen eighth-graders prompted to explain each line of a text to themselves gained more from pretest to posttest than ten controls who read the text twice. | A very small sample. |
| Chi & Wylie 2014, *Educational Psychologist* 49(4), 219–243. [doi:10.1080/00461520.2014.965823](https://doi.org/10.1080/00461520.2014.965823). Abstract read. | The ICAP hypothesis predicts that learning increases as engagement moves from passive to active to constructive to interactive, and supports this with laboratory and classroom studies. | A hypothesis with supporting evidence; the authors discuss its limits. No effect sizes in the abstract. |
| Nesbit & Adesope 2006, *Review of Educational Research* 76(3), 413–448. [doi:10.3102/00346543076003413](https://doi.org/10.3102/00346543076003413). Abstract read. | A meta-analysis of 55 studies (5,818 participants, 67 effect sizes) found concept-map use associated with better knowledge retention, with effects from small to large depending on how the maps were used and what they were compared with. | The abstract states a retention benefit. A transfer benefit was not confirmed. |

## Not confirmed, and not used as evidence

- **Fiorella & Mayer 2013**, *Contemporary Educational Psychology* 38(4), 281–288 ([doi:10.1016/j.cedpsych.2013.06.001](https://doi.org/10.1016/j.cedpsych.2013.06.001)): the record was confirmed, but no abstract could be retrieved, so the claim that teaching others improves one's own learning is not cited. The teach-back step rests on the self-explanation work above.
- **Dunlosky, Rawson, Marsh, Nathan & Willingham 2013**, *Psychological Science in the Public Interest* 14(1), 4–58 ([doi:10.1177/1529100612453266](https://doi.org/10.1177/1529100612453266)): the record and the list of ten techniques were confirmed, but the retrieved abstract does not state which techniques were rated high or low, so the ratings are not cited.
- **Parsons & Haden 2006** and **Ericson, Margulieux & Rick 2017**: see the hands-on section.
