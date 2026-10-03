# The research behind wise-scholar

This page lists what each teaching behaviour in the app relies on, what the cited source reports, and how far that finding reaches. It was checked on 2026-10-02.

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

### The opening interview

| Source | What it reports | Limits |
|---|---|---|
| Pashler, McDaniel, Rohrer & Bjork 2008, *Psychological Science in the Public Interest* 9(3), 105–119. [doi:10.1111/j.1539-6053.2009.01038.x](https://doi.org/10.1111/j.1539-6053.2009.01038.x). Abstract read. | Virtually no evidence that matching instruction to a learner's preferred style improves learning; the evidence does not justify style assessments in education. | "Insufficient evidence", not "disproven": few studies of the required design exist. This is why the interview asks about knowledge, goals and interests and never about a learning style. |
| Walkington 2013, *Journal of Educational Psychology* 105(4), 932–945. [doi:10.1037/a0031882](https://doi.org/10.1037/a0031882). Record and summary read. | 145 algebra students given story problems matched to their interests performed better, wrote expressions faster and gamed the tutoring system less than students given standard problems. | One study in one tutoring system. The reported gains are performance and process measures; a separate learning gain was not confirmed. |
| Ausubel 1968, *Educational Psychology: A Cognitive View*. Holt, Rinehart and Winston. Secondary sources only. | The book's epigraph is quoted as: "The most important single factor influencing learning is what the learner already knows. Ascertain this and teach him accordingly." | Quoted from secondary sources; the book itself was not opened. A statement of principle, not a measured effect. |

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
