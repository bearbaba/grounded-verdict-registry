# { "Depends": "py-genlayer:test" }

from genlayer import *
from dataclasses import dataclass
import json
import typing

MAX_SOURCES = 5
MAX_PAGE_CHARS = 6000
MAX_QUESTION = 500
MAX_RUBRIC = 800
ALLOWED = ("SUPPORTED", "REFUTED", "INCONCLUSIVE")


@allow_storage
@dataclass
class Case:
    clerk: Address
    question: str
    rubric: str
    sources_csv: str
    source_count: u32
    sealed: bool
    status: str
    cited_url: str
    justification: str
    round_no: u32


def _split_sources(csv: str) -> list[str]:
    seen = []
    for raw in csv.split(","):
        url = raw.strip()
        if url and url not in seen:
            seen.append(url)
    return seen


def _join_sources(urls: list[str]) -> str:
    return ",".join(urls)


class GroundedVerdictRegistry(gl.Contract):
    cases: TreeMap[str, Case]
    next_id: u32

    def __init__(self):
        self.next_id = u32(1)

    @gl.public.write
    def open_case(self, question: str, rubric: str, sources_csv: str) -> u32:
        q = question.strip()
        r = rubric.strip()
        if not q or not r:
            raise Exception("question and rubric required")
        if len(q) > MAX_QUESTION or len(r) > MAX_RUBRIC:
            raise Exception("question or rubric too long")
        urls = _split_sources(sources_csv)
        if not urls:
            raise Exception("at least one source required")
        if len(urls) > MAX_SOURCES:
            raise Exception("too many sources")
        case_id = self.next_id
        self.next_id = u32(int(self.next_id) + 1)
        self.cases[str(int(case_id))] = Case(
            clerk=gl.message.sender_address,
            question=q,
            rubric=r,
            sources_csv=_join_sources(urls),
            source_count=u32(len(urls)),
            sealed=False,
            status="OPEN",
            cited_url="",
            justification="",
            round_no=u32(0),
        )
        return case_id

    @gl.public.write
    def add_source(self, case_id: u32, url: str) -> u32:
        key = str(int(case_id))
        if key not in self.cases:
            raise Exception("unknown case")
        rec = self.cases[key]
        if rec.sealed:
            raise Exception("sources sealed")
        if rec.clerk != gl.message.sender_address:
            raise Exception("only clerk can add sources")
        clean = url.strip()
        if not clean:
            raise Exception("empty url")
        urls = _split_sources(rec.sources_csv)
        if clean not in urls:
            if len(urls) >= MAX_SOURCES:
                raise Exception("too many sources")
            urls.append(clean)
        rec.sources_csv = _join_sources(urls)
        rec.source_count = u32(len(urls))
        self.cases[key] = rec
        return rec.source_count

    @gl.public.write
    def seal_sources(self, case_id: u32) -> bool:
        key = str(int(case_id))
        if key not in self.cases:
            raise Exception("unknown case")
        rec = self.cases[key]
        if rec.clerk != gl.message.sender_address:
            raise Exception("only clerk can seal")
        if rec.source_count == u32(0):
            raise Exception("no sources")
        rec.sealed = True
        rec.status = "SEALED"
        self.cases[key] = rec
        return True

    @gl.public.write
    def adjudicate(self, case_id: u32) -> str:
        key = str(int(case_id))
        if key not in self.cases:
            raise Exception("unknown case")
        rec_mem = gl.storage.copy_to_memory(self.cases[key])
        if not rec_mem.sealed:
            raise Exception("seal sources first")
        if rec_mem.status in ALLOWED:
            raise Exception("already final")
        urls = _split_sources(rec_mem.sources_csv)
        question = rec_mem.question
        rubric = rec_mem.rubric

        def collect_evidence() -> str:
            chunks = []
            for url in urls:
                try:
                    page = gl.nondet.web.render(url, mode="text")
                    chunks.append(
                        f"URL: {url}\nSTATUS: OK\nTEXT:\n{page[:MAX_PAGE_CHARS]}\n===="
                    )
                except Exception as err:
                    chunks.append(
                        f"URL: {url}\nSTATUS: FETCH_FAILED\nERROR: {err}\n===="
                    )
            return "\n".join(chunks)

        raw = gl.eq_principle.prompt_non_comparative(
            collect_evidence,
            task=(
                "Adjudicate the QUESTION using ONLY the fetched pages.\n"
                f"QUESTION: {question}\n"
                f"RUBRIC: {rubric}\n"
                "Return JSON only with keys status, cited_url, justification.\n"
                "status must be exactly SUPPORTED, REFUTED, or INCONCLUSIVE.\n"
                "SUPPORTED: at least one successful page clearly supports the question under the rubric.\n"
                "REFUTED: pages clearly contradict the question and none support it.\n"
                "INCONCLUSIVE: fetch failures, silence, or unresolved conflict.\n"
                "cited_url must be one of the fetched URLs when status is SUPPORTED or REFUTED.\n"
                "justification: at most two sentences, grounded in page text."
            ),
            criteria=(
                f"Rubric: {rubric}\n"
                "Leader output must be JSON with status, cited_url, justification.\n"
                "status must be exactly SUPPORTED, REFUTED, or INCONCLUSIVE.\n"
                "SUPPORTED only if fetched text supports the question under the rubric.\n"
                "REFUTED only if fetched text contradicts the question and none supports it.\n"
                "INCONCLUSIVE required if pages are missing, silent, or conflicting.\n"
                "If status is SUPPORTED or REFUTED, cited_url must be one of the sealed sources.\n"
                "justification must not invent facts absent from the pages.\n"
                "Do not accept format-valid JSON that ignores the pages."
            ),
        )

        if isinstance(raw, dict):
            parsed = raw
        else:
            text = str(raw).strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.lower().startswith("json"):
                    text = text[4:]
                text = text.strip()
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = {
                    "status": "INCONCLUSIVE",
                    "cited_url": "",
                    "justification": "unparseable leader payload",
                }

        status = str(parsed.get("status", "INCONCLUSIVE")).upper()
        if status not in ALLOWED:
            status = "INCONCLUSIVE"
        cited = str(parsed.get("cited_url", "")).strip()
        if status in ("SUPPORTED", "REFUTED") and cited not in urls:
            status = "INCONCLUSIVE"
            cited = ""

        rec = self.cases[key]
        rec.status = status
        rec.cited_url = cited[:300]
        rec.justification = str(parsed.get("justification", ""))[:500]
        rec.round_no = u32(int(rec.round_no) + 1)
        self.cases[key] = rec
        return status

    @gl.public.write
    def challenge(self, case_id: u32, reason: str) -> bool:
        key = str(int(case_id))
        if key not in self.cases:
            raise Exception("unknown case")
        rec = self.cases[key]
        if rec.status not in ALLOWED:
            raise Exception("nothing to challenge")
        if not reason.strip():
            raise Exception("reason required")
        rec.status = "CHALLENGED"
        rec.justification = reason.strip()[:500]
        self.cases[key] = rec
        return True

    @gl.public.view
    def get_case(self, case_id: u32) -> TreeMap[str, typing.Any]:
        key = str(int(case_id))
        if key not in self.cases:
            return {}
        rec = self.cases[key]
        out: TreeMap[str, typing.Any] = {}
        out["clerk"] = str(rec.clerk)
        out["question"] = rec.question
        out["rubric"] = rec.rubric
        out["sources_csv"] = rec.sources_csv
        out["source_count"] = int(rec.source_count)
        out["sealed"] = rec.sealed
        out["status"] = rec.status
        out["cited_url"] = rec.cited_url
        out["justification"] = rec.justification
        out["round_no"] = int(rec.round_no)
        return out

    @gl.public.view
    def get_status(self, case_id: u32) -> str:
        key = str(int(case_id))
        if key not in self.cases:
            return ""
        return self.cases[key].status
