"""A course as a folder of Markdown notes for Obsidian: one note per course, module, unit, lesson, card, mistake,
project and word, linked with wikilinks and carrying properties, so the learner's record becomes a graph."""

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import course_files, db

# Folder and property names are fixed in English so a re-export lands on the same files; the text inside a note
# follows the learner's language.
FOLDER = "Wise Scholar"
WORDS = {
    "en": {
        "course": "Course", "modules": "Modules", "units": "Units", "lessons": "Lessons", "cards": "Cards", "mistakes": "Mistakes",
        "projects": "Projects", "words": "Vocabulary", "interview": "Interview", "placement": "Placement", "scope": "Scope",
        "hours": "Planned teaching time: {} hours", "level": "Level", "mastery": "Mastery", "placed_out": "placed out",
        "builds_on": "Earlier unit", "attempts": "Attempts", "hints": "Hints", "solution": "Solution", "your_answer": "Your answer",
        "sure": "{}% sure", "right": "right", "wrong": "wrong", "answer": "Answer", "explanation": "Explanation",
        "feedback": "Feedback", "files": "Files", "run": "Run command", "output": "Last run", "tutor": "Tutor", "you": "You",
        "milestones": "Milestones", "done": "done", "open": "open", "note": "Your note", "said": "You said",
        "correct": "Right answer", "resolved": "resolved", "pinned": "pinned", "unit_covered": "Unit covered", "result": "Result",
        "glossary": "Glossary", "known": "known", "learning": "learning", "seen_in": "Seen in", "flashcards": "Review cards",
        "pretest": "Opening question", "gave_up": "gave up", "solved": "solved", "unanswered": "not answered", "cast": "Cast",
        "map": "Course map", "unknown": "I don't know",
    },
    "fr": {
        "course": "Cours", "modules": "Modules", "units": "Unités", "lessons": "Leçons", "cards": "Cartes", "mistakes": "Erreurs",
        "projects": "Projets", "words": "Vocabulaire", "interview": "Entretien", "placement": "Test de niveau", "scope": "Cadre",
        "hours": "Temps d'enseignement prévu : {} heures", "level": "Niveau", "mastery": "Maîtrise", "placed_out": "déjà acquis",
        "builds_on": "Unité précédente", "attempts": "Tentatives", "hints": "Indices", "solution": "Solution", "your_answer": "Votre réponse",
        "sure": "sûr à {} %", "right": "juste", "wrong": "faux", "answer": "Réponse", "explanation": "Explication",
        "feedback": "Retour", "files": "Fichiers", "run": "Commande d'exécution", "output": "Dernière exécution", "tutor": "Tuteur", "you": "Vous",
        "milestones": "Jalons", "done": "fait", "open": "ouvert", "note": "Votre note", "said": "Vous avez dit",
        "correct": "Bonne réponse", "resolved": "résolue", "pinned": "épinglée", "unit_covered": "Unité couverte", "result": "Résultat",
        "glossary": "Glossaire", "known": "connu", "learning": "en cours", "seen_in": "Vu dans", "flashcards": "Cartes de révision",
        "pretest": "Question d'ouverture", "gave_up": "abandon", "solved": "résolu", "unanswered": "sans réponse", "cast": "Émission",
        "map": "Plan du cours", "unknown": "Je ne sais pas",
    },
    "ar": {
        "course": "الدورة", "modules": "الوحدات الكبرى", "units": "الوحدات", "lessons": "الدروس", "cards": "البطاقات", "mistakes": "الأخطاء",
        "projects": "المشاريع", "words": "المفردات", "interview": "المقابلة", "placement": "اختبار تحديد المستوى", "scope": "النطاق",
        "hours": "وقت التدريس المخطط: {} ساعة", "level": "المستوى", "mastery": "الإتقان", "placed_out": "مُتقَن مسبقًا",
        "builds_on": "الوحدة السابقة", "attempts": "المحاولات", "hints": "التلميحات", "solution": "الحل", "your_answer": "جوابك",
        "sure": "واثق بنسبة {}٪", "right": "صحيح", "wrong": "خطأ", "answer": "الجواب", "explanation": "الشرح",
        "feedback": "الملاحظات", "files": "الملفات", "run": "أمر التشغيل", "output": "آخر تشغيل", "tutor": "المعلّم", "you": "أنت",
        "milestones": "المراحل", "done": "منجز", "open": "مفتوح", "note": "ملاحظتك", "said": "قلت",
        "correct": "الجواب الصحيح", "resolved": "تم حلّه", "pinned": "مثبّت", "unit_covered": "اكتملت الوحدة", "result": "النتيجة",
        "glossary": "المسرد", "known": "معروف", "learning": "قيد التعلم", "seen_in": "ورد في", "flashcards": "بطاقات المراجعة",
        "pretest": "سؤال البداية", "gave_up": "استسلام", "solved": "محلول", "unanswered": "بلا إجابة", "cast": "حلقة",
        "map": "خريطة الدورة", "unknown": "لا أعرف",
    },
}
CARD_KINDS = ("challenge", "exercise", "quiz", "speaking")
TITLE_CHARS = 80
# Canvas layout, in Obsidian canvas units.
NODE = (260, 70)
GAP = (40, 20)


def _name(text: str, limit: int = TITLE_CHARS) -> str:
    """A file name Obsidian and every filesystem accept: no link or path characters, one line, bounded."""
    text = re.sub(r"[\[\]#^|\\/:*?\"<>\r\n]+", " ", text.replace("`", ""))
    text = " ".join(text.split()).strip(" .")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return text.rstrip(" .") or "untitled"


def _yaml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_yaml(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def _front(props: dict) -> str:
    return "---\n" + "".join(f"{k}: {_yaml(v)}\n" for k, v in props.items() if v is not None) + "---\n"


def _callout(kind: str, title: str, body: str, folded: bool = True) -> str:
    lines = body.strip().splitlines() or [""]
    return f"> [!{kind}]{'-' if folded else ''} {title}\n" + "\n".join(f"> {line}" for line in lines) + "\n"


def _code(text: str, lang: str = "") -> str:
    fence = "`" * max(3, max((len(m) for m in re.findall(r"`{3,}", text)), default=0) + 1)
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}\n"


class Vault:
    """Builds the notes of one course; paths are vault-relative so links stay valid beside other courses."""

    def __init__(self, course_id: int):
        self.course = db.course(course_id)
        self.profile = db.profile(self.course["profile_id"])
        self.t = WORDS.get(self.profile["locale"], WORDS["en"])
        self.root = f"{FOLDER}/{_name(self.course['topic'])}"
        self.files: dict[str, bytes] = {}
        self.names: dict[tuple, str] = {}
        self.concepts = db.concept_view(course_id)
        self.lessons = db.rows("SELECT * FROM lessons WHERE course_id = ? ORDER BY id", course_id)
        for lesson in self.lessons:
            lesson["blocks"] = db.blocks(lesson["id"])
            lesson["messages"] = db.rows("SELECT * FROM messages WHERE lesson_id = ? ORDER BY id", lesson["id"])
        self.capstones = db.capstones(course_id)
        self.errors = db.errors(self.course["profile_id"], course_id)
        self.workspace = db.WORKSPACE / self.course["slug"]
        self.cards = {e["card_id"]: db.card(e["card_id"]) for e in self.errors if e.get("card_id")}
        self.by_card = {}
        for lesson in self.lessons:
            for block in lesson["blocks"]:
                if block["kind"] in CARD_KINDS and block["data"].get("card_id"):
                    self.by_card[block["data"]["card_id"]] = block
        self._assign_names()

    # --- names and links -------------------------------------------------------------------------------------------

    def _assign_names(self):
        taken: set[str] = set()

        def claim(key: tuple, folder: str, title: str, number: int | None = None):
            base = f"{self.root}/{folder}/" if folder else f"{self.root}/"
            name = f"{number} {_name(title)}" if number is not None else _name(title)
            path, n = f"{base}{name}", 1
            # Case-insensitive: the vault may unpack on a filesystem that folds case.
            while path.lower() in taken:
                n += 1
                path = f"{base}{name} ({n})"
            taken.add(path.lower())
            self.names[key] = path

        claim(("course",), "", self.course["topic"])
        for module in dict.fromkeys(c["module"] for c in self.concepts):
            claim(("module", module), "Modules", module)
        for c in self.concepts:
            claim(("unit", c["id"]), "Units", c["title"])
        n = 0
        for lesson in self.lessons:
            if lesson["phase"] in ("interview", "placement"):
                claim(("lesson", lesson["id"]), "", lesson["title"])
            else:
                n += 1
                claim(("lesson", lesson["id"]), "Lessons", lesson["title"], n)
            for block in lesson["blocks"]:
                if block["kind"] in CARD_KINDS:
                    claim(("card", block["id"]), "Cards", block["markdown"].splitlines()[0] if block["markdown"].strip() else block["kind"], block["id"])
        for e in self.errors:
            claim(("mistake", e["id"]), "Mistakes", e["prompt"].splitlines()[0] if e["prompt"].strip() else e["kind"], e["id"])
        for k in self.capstones:
            claim(("project", k["id"]), "Projects", k["title"])
        if self.course["lang"]:
            for word in self._words():
                claim(("word", word["lemma"]), "Vocabulary", word["lemma"])

    def link(self, key: tuple, label: str | None = None) -> str:
        path = self.names[key]
        return f"[[{path}|{_name(label)}]]" if label else f"[[{path}]]"

    def maybe_link(self, key: tuple, fallback: str = "") -> str | None:
        """A link to a note that may not exist any more (a module or unit removed by a revision)."""
        return self.link(key) if key in self.names else (fallback or None)

    def embed(self, key: tuple) -> str:
        return f"![[{self.names[key]}]]"

    def put(self, key: tuple, props: dict, body: str):
        self.files[self.names[key] + ".md"] = (_front(props) + "\n" + body.rstrip() + "\n").encode()

    # --- shared pieces ---------------------------------------------------------------------------------------------

    def unit_of_lesson(self, lesson: dict) -> dict | None:
        return next((c for c in self.concepts if c["id"] == lesson["concept_id"]), None)

    def _timeline(self, lesson: dict) -> list[dict]:
        """Blocks and chat in the order they happened; within one second the learner speaks, then cards, then the tutor."""
        rank = lambda item: 1 if "kind" in item else (0 if item["role"] == "learner" else 2)  # noqa: E731
        items = [*lesson["blocks"], *lesson["messages"]]
        return sorted(items, key=lambda i: (i["created"], rank(i), i["id"]))

    def _block_text(self, lesson: dict, block: dict) -> str:
        t, d, kind = self.t, block["data"], block["kind"]
        if kind in CARD_KINDS:
            return self.embed(("card", block["id"]))
        if kind == "figure":
            path = f"{self.root}/attachments/figure-{block['id']}.svg"
            self.files[path] = d["svg"].encode()
            return f"![[{path}]]\n" + (f"*{block['markdown']}*\n" if block["markdown"] else "")
        if kind == "plot":
            png = f"{self.root}/attachments/plot-{block['id']}.png"
            if png in self.files:
                return f"![[{png}]]\n*{block['markdown']}*\n"
            return f"**{block['markdown']}**\n\n" + _code(json.dumps(d["spec"], ensure_ascii=False, indent=2), "json")
        if kind == "reading":
            gloss = "\n".join(f"- **{g['word']}**: {g['meaning']}" for g in d.get("glossary", []) if "word" in g and "meaning" in g)
            return f"### {d['title']}\n\n{block['markdown']}\n" + (f"\n**{t['glossary']}**\n{gloss}\n" if gloss else "")
        if kind == "question":
            answer = d.get("answer")
            return f"**{block['markdown']}**\n\n{t['your_answer']}: {answer if answer is not None else t['unanswered']}\n"
        if kind == "placement":
            return f"**{t['result']}** · {t['level']}: {d.get('level', '')}\n\n{block['markdown']}\n"
        if kind == "done":
            return _callout("success", t["unit_covered"], block["markdown"], folded=False)
        if kind == "podcast":
            lines = "\n".join(f"**{l['speaker']}:** {l['text']}" for l in d.get("lines", []))
            return _callout("quote", f"{t['cast']} · {block['markdown']}", lines)
        if kind in ("network", "vocab"):
            return ""
        return block["markdown"] + "\n"

    def _card_body(self, lesson: dict, block: dict) -> str:
        t, d, kind = self.t, block["data"], block["kind"]
        out = [block["markdown"], ""]
        if kind == "quiz":
            if d.get("options"):
                out += [f"- {'**' if o == d.get('answer_key') else ''}{o}{'**' if o == d.get('answer_key') else ''}" for o in d["options"]] + [""]
            if d.get("answer") is None:
                out.append(f"*{t['unanswered']}*")
            else:
                shown = t["unknown"] if d.get("unknown") else d["answer"]
                sure = "" if d.get("unknown") else f" · {t['sure'].format(round(d.get('confidence', 0) * 100))}"
                out.append(f"**{t['your_answer']}**{sure}: {shown}")
                if d.get("correct") is not None:
                    out.append(f"**{t['result']}**: {t['right'] if d['correct'] else t['wrong']}")
                    out.append(f"**{t['answer']}**: {d.get('answer_key', '')}")
                    if d.get("feedback"):
                        out.append(f"**{t['feedback']}**: {d['feedback']}")
                    elif d.get("explanation"):
                        out.append(f"**{t['explanation']}**: {d['explanation']}")
        else:
            if kind == "exercise":
                out.append(f"**{t['run']}**: `{d.get('run', '')}`")
                out.append(f"**{t['files']}**:")
                for path in d.get("files", []):
                    kept = f"{self.root}/attachments/exercise-{block['id']}/{path}"
                    content = course_files.read_text(self.workspace, path) if self.workspace.exists() else None
                    if content is not None:
                        self.files[kept] = content.encode()
                        out.append(f"- [[{kept}|{_name(path)}]]")
                    else:
                        out.append(f"- `{path}`")
                if d.get("last_run"):
                    out += ["", f"**{t['output']}** (exit {d['last_run'].get('exit_code')})", _code(d["last_run"].get("output", ""))]
            if d.get("attempts"):
                out += ["", f"**{t['attempts']}**"] + [f"{i + 1}. {a}" for i, a in enumerate(d["attempts"])]
            if d.get("hints"):
                out += ["", f"**{t['hints']}**"] + [f"- {h}" for h in d["hints"]]
            if d.get("solution"):
                out += ["", _callout("solution", t["solution"], d["solution"])]
        mine = [e for e in self.errors if e.get("card_id") and self.by_card.get(e["card_id"], {}).get("id") == block["id"]]
        if mine:
            out += ["", f"**{t['mistakes']}**: " + ", ".join(self.link(("mistake", e["id"])) for e in mine)]
        return "\n".join(out)

    def _card_props(self, lesson: dict, block: dict) -> dict:
        d, kind = block["data"], block["kind"]
        unit = self.unit_of_lesson(lesson)
        props = {
            "type": "card", "id": block["id"], "kind": kind,
            "course": self.link(("course",)), "lesson": self.link(("lesson", lesson["id"])),
            "unit": self.link(("unit", unit["id"])) if unit else None,
            "pretest": bool(d.get("pretest")), "milestone": bool(d.get("milestone")),
            "created": block["created"], "tags": ["wise-scholar/card", f"wise-scholar/{kind}"],
        }
        if kind == "quiz":
            props.update({
                "answered": d.get("answer") is not None, "correct": d.get("correct"),
                "confidence": d.get("confidence"), "confident_miss": d.get("confident_miss"), "unknown": bool(d.get("unknown")),
            })
        else:
            props.update({
                "solved": bool(d.get("solved")), "gave_up": bool(d.get("gave_up")), "hints": len(d.get("hints", [])),
                "attempts": len(d.get("attempts", [])), "writing": bool(d.get("writing")), "teachback": bool(d.get("teachback")),
            })
        return props

    def _words(self) -> list[dict]:
        return db.rows(
            "SELECT lemma, state, source, exposures FROM vocab_knowledge WHERE profile_id = ? AND lang = ? ORDER BY lemma",
            self.course["profile_id"], self.course["lang"],
        )

    # --- notes -----------------------------------------------------------------------------------------------------

    def build(self) -> dict[str, bytes]:
        t = self.t
        for lesson in self.lessons:
            unit = self.unit_of_lesson(lesson)
            for block in lesson["blocks"]:
                if block["kind"] in CARD_KINDS:
                    self.put(("card", block["id"]), self._card_props(lesson, block), self._card_body(lesson, block))
            body = []
            for item in self._timeline(lesson):
                if "kind" in item:
                    body.append(self._block_text(lesson, item))
                else:
                    who = t["you"] if item["role"] == "learner" else t["tutor"]
                    body.append(_callout("quote", who, item["text"], folded=item["role"] == "tutor"))
            opening = lesson["phase"] in ("interview", "placement")
            props = {
                "type": "lesson", "id": lesson["id"], "phase": lesson["phase"], "course": self.link(("course",)),
                "unit": self.link(("unit", unit["id"])) if unit else None,
                "started": lesson["blocks"][0]["created"] if lesson["blocks"] else None,
                "finished": any(b["kind"] == "done" for b in lesson["blocks"]),
                "tags": ["wise-scholar/lesson"],
            }
            heading = t["interview"] if lesson["phase"] == "interview" else t["placement"] if lesson["phase"] == "placement" else lesson["title"]
            self.put(("lesson", lesson["id"]), props, f"# {heading}\n\n" + ("" if opening else f"{t['course']}: {self.link(('course',))}\n\n") + "\n".join(body))

        for e in self.errors:
            card = self.cards.get(e.get("card_id"))
            block = self.by_card.get(e.get("card_id"))
            props = {
                "type": "mistake", "id": e["id"], "kind": e["kind"], "course": self.link(("course",)),
                "unit": self.maybe_link(("unit", card["concept_id"])) if card else None,
                "card": self.link(("card", block["id"])) if block else None,
                "resolved": bool(e["resolved"]), "pinned": bool(e["pinned"]), "created": e["created"],
                "tags": ["wise-scholar/mistake"] + (["wise-scholar/resolved"] if e["resolved"] else []),
            }
            body = [e["prompt"], "", f"**{t['said']}**: {e['said']}", f"**{t['correct']}**: {e['correct']}"]
            if e["explanation"]:
                body.append(f"**{t['explanation']}**: {e['explanation']}")
            if e["note"]:
                body += ["", _callout("note", t["note"], e["note"], folded=False)]
            self.put(("mistake", e["id"]), props, "\n".join(body))

        for k in self.capstones:
            props = {
                "type": "project", "id": k["id"], "course": self.link(("course",)), "module": self.maybe_link(("module", k["module"])),
                "done": k["done"], "milestones": len(k["milestones"]), "tags": ["wise-scholar/project"],
            }
            lines = [k["brief"], "", f"**{t['milestones']}**"]
            for m in k["milestones"]:
                lines.append(f"- [{'x' if m['done'] else ' '}] {self.maybe_link(('unit', m['concept_id']), m['concept'])}: {m['deliverable']}")
            self.put(("project", k["id"]), props, "\n".join(lines))

        for c in self.concepts:
            lessons = [l for l in self.lessons if l["concept_id"] == c["id"]]
            cards = [b for l in lessons for b in l["blocks"] if b["kind"] in CARD_KINDS]
            mistakes = [e for e in self.errors if (self.cards.get(e.get("card_id")) or {}).get("concept_id") == c["id"]]
            index = self.concepts.index(c)
            earlier = self.concepts[index - 1] if index else None
            props = {
                "type": "unit", "id": c["id"], "course": self.link(("course",)), "module": self.link(("module", c["module"])),
                "position": self.concepts.index(c) + 1, "known": bool(c["known"]),
                "mastery": round(c["mastery"], 2) if c["mastery"] is not None else None,
                "builds_on": self.link(("unit", earlier["id"])) if earlier else None,
                "mistakes": len(mistakes), "tags": ["wise-scholar/unit"] + (["wise-scholar/placed-out"] if c["known"] else []),
            }
            lines = [f"# {c['title']}", ""]
            if c["known"]:
                lines.append(f"*{t['placed_out']}*")
            elif c["mastery"] is not None:
                lines.append(f"**{t['mastery']}**: {round(c['mastery'] * 100)}%")
            if earlier:
                lines.append(f"**{t['builds_on']}**: {self.link(('unit', earlier['id']))}")
            if lessons:
                lines += ["", f"## {t['lessons']}"] + [f"- {self.link(('lesson', l['id']))}" for l in lessons]
            if cards:
                lines += ["", f"## {t['cards']}"] + [f"- {self.link(('card', b['id']))} · {self._outcome(b)}" for b in cards]
            if mistakes:
                lines += ["", f"## {t['mistakes']}"] + [f"- {self.link(('mistake', e['id']))}" for e in mistakes]
            lines += self._flashcards(c)
            self.put(("unit", c["id"]), props, "\n".join(lines))

        for module in dict.fromkeys(c["module"] for c in self.concepts):
            units = [c for c in self.concepts if c["module"] == module]
            projects = [k for k in self.capstones if k["module"] == module]
            props = {"type": "module", "course": self.link(("course",)), "units": len(units), "tags": ["wise-scholar/module"]}
            lines = [f"# {module}", ""] + [f"- {self.link(('unit', c['id']))}" + (f" · *{t['placed_out']}*" if c["known"] else "") for c in units]
            if projects:
                lines += ["", f"## {t['projects']}"] + [f"- {self.link(('project', k['id']))}" for k in projects]
            self.put(("module", module), props, "\n".join(lines))

        if self.course["lang"]:
            self._word_notes()

        self._course_note()
        self._canvas()
        return self.files

    def _outcome(self, block: dict) -> str:
        t, d = self.t, block["data"]
        if block["kind"] == "quiz":
            if d.get("correct") is None:
                return t["unanswered"]
            return t["right"] if d["correct"] else t["wrong"]
        return t["solved"] if d.get("solved") else t["gave_up"] if d.get("gave_up") else t["open"]

    def _flashcards(self, concept: dict) -> list[str]:
        """The unit's scheduled quiz cards in the Spaced Repetition plugin's multi-line form; a copy, scheduling stays here."""
        cards = [c for c in db.rows("SELECT question, answer_key, kind, options FROM cards WHERE concept_id = ? AND scheduled = 1 ORDER BY id", concept["id"]) if c["answer_key"].strip()]
        if not cards:
            return []
        # The plugin ends a card at a blank line and reads a lone "?" as the separator: neither may appear inside a side.
        side = lambda text: "\n".join(line if line.strip() != "?" else "? " for line in text.strip().splitlines() if line.strip())  # noqa: E731
        lines = ["", f"## {self.t['flashcards']}", "", "#flashcards"]
        for c in cards:
            question = side(c["question"])
            if c["kind"] == "choice":
                question += "\n" + "\n".join(f"- {o}" for o in json.loads(c["options"]))
            lines += ["", question, "?", side(c["answer_key"])]
        return lines

    def _word_notes(self):
        t = self.t
        readings = [(l, b) for l in self.lessons for b in l["blocks"] if b["kind"] == "reading"]
        for w in self._words():
            seen = [(l, b) for l, b in readings if re.search(rf"(?<!\w){re.escape(w['lemma'])}(?!\w)", b["markdown"], re.IGNORECASE)]
            props = {
                "type": "word", "lemma": w["lemma"], "lang": self.course["lang"], "state": w["state"], "source": w["source"],
                "exposures": w["exposures"], "course": self.link(("course",)), "tags": ["wise-scholar/word", f"wise-scholar/{w['state']}"],
            }
            lines = [f"# {w['lemma']}", "", f"**{t[w['state']] if w['state'] in t else w['state']}** · {w['exposures']}×"]
            if seen:
                lines += ["", f"## {t['seen_in']}"] + [f"- {self.link(('lesson', l['id']))} · {b['data'].get('title', '')}" for l, b in seen]
            self.put(("word", w["lemma"]), props, "\n".join(lines))

    def _course_note(self):
        t, c = self.t, self.course
        props = {
            "type": "course", "id": c["id"], "topic": c["topic"], "mechanism": c["mechanism"], "level": c["level"], "lang": c["lang"],
            "hours": c["hours"], "exported": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tags": ["wise-scholar/course"],
        }
        lines = [f"# {c['topic']}", ""]
        if c["details"]:
            lines += [f"**{t['scope']}**: {c['details']}"]
        if c["hours"]:
            lines += [t["hours"].format(c["hours"])]
        if c["level"]:
            lines += [f"**{t['level']}**: {c['level']}"]
        opening = [l for l in self.lessons if l["phase"] in ("interview", "placement")]
        lines += [""] + [f"- {self.link(('lesson', l['id']))}" for l in opening]
        lines += ["", f"## {t['map']}", "", f"![[{self.root}/{_name(t['map'])}.canvas]]"]
        for module in dict.fromkeys(x["module"] for x in self.concepts):
            lines += ["", f"### {self.link(('module', module), module)}"]
            for u in (x for x in self.concepts if x["module"] == module):
                mark = t["placed_out"] if u["known"] else f"{round(u['mastery'] * 100)}%" if u["mastery"] is not None else "–"
                lines.append(f"- {self.link(('unit', u['id']))} · {mark}")
        if self.capstones:
            lines += ["", f"## {t['projects']}"] + [f"- {self.link(('project', k['id']))}" for k in self.capstones]
        if self.errors:
            lines += ["", f"## {t['mistakes']}"] + [f"- {self.link(('mistake', e['id']))}" for e in self.errors]
        extras = [l for l in self.lessons if l["concept_id"] is None and l["phase"] not in ("interview", "placement")]
        if extras:
            lines += ["", f"## {t['lessons']}"] + [f"- {self.link(('lesson', l['id']))}" for l in extras]
        if c["lang"]:
            words = self._words()
            if words:
                lines += ["", f"## {t['words']}"] + [f"- {self.link(('word', w['lemma']))}" for w in words]
        self.put(("course",), props, "\n".join(lines))

    def _canvas(self):
        """The map as an Obsidian canvas: one column per module, its units below, projects beside the module."""
        nodes, edges = [], []
        w, h = NODE
        gx, gy = GAP
        for col, module in enumerate(dict.fromkeys(c["module"] for c in self.concepts)):
            x = col * (w + gx)
            nodes.append({"id": f"module-{col}", "type": "text", "text": f"**{module}**", "x": x, "y": 0, "width": w, "height": h})
            units = [c for c in self.concepts if c["module"] == module]
            for row, u in enumerate(units):
                nodes.append({"id": f"unit-{u['id']}", "type": "file", "file": self.names[("unit", u["id"])] + ".md",
                              "x": x, "y": (row + 1) * (h + gy), "width": w, "height": h,
                              **({"color": "4"} if u["known"] else {})})
                above = f"unit-{units[row - 1]['id']}" if row else f"module-{col}"
                edges.append({"id": f"e-{u['id']}", "fromNode": above, "toNode": f"unit-{u['id']}", "fromSide": "bottom", "toSide": "top"})
            for k in (k for k in self.capstones if k["module"] == module):
                nodes.append({"id": f"project-{k['id']}", "type": "file", "file": self.names[("project", k["id"])] + ".md",
                              "x": x, "y": -(h + gy), "width": w, "height": h, "color": "6"})
                edges.append({"id": f"ep-{k['id']}", "fromNode": f"module-{col}", "toNode": f"project-{k['id']}", "fromSide": "top", "toSide": "bottom"})
        self.files[f"{self.root}/{_name(self.t['map'])}.canvas"] = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=1).encode()


def export(course_id: int, plots: dict[int, bytes] | None = None) -> bytes:
    """The zip the learner downloads: unpack it into any vault. plots: PNGs by block id, rendered by the caller."""
    vault = Vault(course_id)
    for block_id, png in (plots or {}).items():
        vault.files[f"{vault.root}/attachments/plot-{block_id}.png"] = png
    files = vault.build()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in sorted(files.items()):
            z.writestr(path, content)
    return buf.getvalue()


def plot_blocks(course_id: int) -> list[int]:
    return [b["id"] for b in db.rows(
        "SELECT b.id FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? AND b.kind = 'plot' ORDER BY b.id", course_id
    )]
