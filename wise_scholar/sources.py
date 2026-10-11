"""Text out of a learner's own files, cut into sections the tutor can search and read one at a time. Parsing runs
in a child process with a time and memory limit: a crafted PDF or EPUB then costs one child, not the server."""
import json
import os
import re
import resource
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

SECTION_CHARS = 3200  # about 800 tokens
MAX_PARTS = 2000  # pages or chapters read from one file
MAX_TEXT = 20_000_000  # characters kept from one file
EXTRACT_SECONDS = 120
EXTRACT_MEMORY = 2 * 1024**3


class Unreadable(ValueError):
    """A file the learner can be told about: the message is theirs to see."""
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".py", ".rs", ".js", ".ts", ".tsx", ".c", ".cpp", ".h", ".hs", ".go",
                 ".java", ".kt", ".rb", ".sh", ".toml", ".yaml", ".yml", ".json", ".csv", ".tex"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("h1", "h2", "h3"):
            self.parts.append("\n# ")
        elif tag in ("p", "div", "li", "br", "tr", "h4", "h5", "h6", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    return "".join(parser.parts)


def extract(path: Path) -> list[tuple[str, str]]:
    """(title, text) pages or chapters of a file, read in a child process; raises ValueError with a message fit for
    the learner when the file cannot be read."""
    suffix = path.suffix.lower()
    if suffix not in HEADING_SUFFIXES | TEXT_SUFFIXES:
        raise Unreadable(f"unsupported file type {suffix or path.name!r}; use PDF, EPUB, HTML, Markdown, text or source code")
    try:
        run = subprocess.run(
            [sys.executable, "-m", "wise_scholar.sources", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=EXTRACT_SECONDS,
            cwd=Path(__file__).resolve().parents[1],
            env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        raise Unreadable("the file took too long to read") from None
    if run.returncode != 0:
        raise Unreadable("the file could not be read (" + (run.stderr.strip().splitlines() or ["the reader failed"])[-1][:80] + ")")
    try:
        return [(title, text) for title, text in json.loads(run.stdout)]
    except (ValueError, TypeError):
        raise RuntimeError(f"the reader gave no usable answer: {run.stdout[:200]!r}") from None


def _limit_memory() -> None:
    """In the child: a ceiling on its address space where the platform has one (Linux); elsewhere the time limit alone."""
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (EXTRACT_MEMORY, EXTRACT_MEMORY))


def _read(path: Path) -> list[tuple[str, str]]:
    """The parsing itself, in the child: bounded in pages and in text kept."""
    suffix = path.suffix.lower()
    parts: list[tuple[str, str]] = []
    if suffix == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            for i, page in enumerate(doc):
                if i >= MAX_PARTS:
                    break
                parts.append((f"page {i + 1}", page.get_text()))
    elif suffix == ".epub":
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if len(parts) >= MAX_PARTS:
                break
            parts.append((item.get_name(), html_text(item.get_content().decode("utf-8", "ignore"))))
    elif suffix in (".html", ".htm"):
        parts = [(path.name, html_text(path.read_text(errors="ignore")))]
    else:
        parts = [(path.name, path.read_text(errors="ignore"))]
    kept, total = [], 0
    for title, text in parts:
        if total >= MAX_TEXT:
            break
        text = text[: MAX_TEXT - total]
        total += len(text)
        kept.append((title, text))
    if len(parts) >= MAX_PARTS or total >= MAX_TEXT:
        kept.append(("note", f"The rest of this file was not read: the tutor reads at most {MAX_PARTS} pages and {MAX_TEXT // 1_000_000} million characters of a file."))
    return kept


HEADING_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".html", ".htm", ".epub", ".pdf"}


def sections(parts: list[tuple[str, str]], name: str) -> list[tuple[str, str]]:
    """Cut extracted parts at headings (prose files only; '#' is a comment in code), then into windows of about
    800 tokens; each section carries a title."""
    out: list[tuple[str, str]] = []
    prose = Path(name).suffix.lower() in HEADING_SUFFIXES
    for part_title, text in parts:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            continue
        pieces = re.split(r"\n(?=#{1,3} )", text) if prose else [text]
        for piece in pieces:
            first, _, rest = piece.partition("\n")
            title = first.lstrip("# ").strip()[:120] if first.startswith("#") else part_title
            body = rest if first.startswith("#") else piece
            body = body.strip()
            if not body:
                continue
            windows = [body[i : i + SECTION_CHARS] for i in range(0, len(body), SECTION_CHARS)]
            for i, window in enumerate(windows):
                suffix = f" · part {i + 1}" if len(windows) > 1 else ""
                out.append((f"{name} · {title}{suffix}", window))
    return out


if __name__ == "__main__":
    try:
        _limit_memory()
        print(json.dumps(_read(Path(sys.argv[1]))))
    except Exception as e:  # the kind of failure for the parent; the parser's own message may name server paths
        print(type(e).__name__, file=sys.stderr)
        sys.exit(1)
