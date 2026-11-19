"""Deterministic checks that keep LLM output tied to what sources actually say.

1. The quote must appear verbatim (after whitespace/punctuation normalization) in
   the document text that was actually read.
2. The claim must be supported by the quote: most of its content words appear in
   the quote, every number in the claim appears in the quote, and no high-risk
   wording ("cure", "guaranteed", ...) is added that the quote lacks.
3. Report prose keeps only sentences citing a verified finding.
"""

import re
import unicodedata

from app.verification.verifier import HIGH_RISK_CLAIM_TOKENS

MIN_SUPPORT = 0.5
MIN_QUOTE_CHARS = 25

_STOP = set("""a an the and or but if of to in on at by for with from as is are was were be been
being it its this that these those there their they them can may might will would should could
not no also than then such into about over more most less very often usually some any each per
which who whom whose what when where how why do does did has have had having women woman
while during using like such both however although though among within non""".split())

_TRANSLATE = str.maketrans({
    "\u2010": "-", "\u2011": "-",  # hyphen, non-breaking hyphen ("self\u2011management")
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
    "−": "-", " ": " ", " ": " ",
})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_TRANSLATE).casefold()
    text = re.sub(r"\[\d+(?:[,–-]\d+)*\]", " ", text)  # drop numeric reference markers
    return " ".join(text.split())


def _segments(quote: str) -> list[str]:
    stripped = normalize(quote).strip(" \"'")
    return [part.strip(" .,;:") for part in re.split(r"\.\.\.|…", stripped) if part.strip(" .,;:")]


def quote_in_document(quote: str, document_text: str) -> bool:
    segments = _segments(quote)
    if not segments or sum(len(s) for s in segments) < MIN_QUOTE_CHARS:
        return False
    haystack = normalize(document_text)
    if all(segment in haystack for segment in segments):
        return True
    # PDF text breaks hyphens and spacing at line ends ("terms-and-\nconditions" ->
    # "terms-andconditions"). Fall back to comparing letters and digits only: the same
    # characters must still appear in the same order.
    compact = _alnum(haystack)
    return all(_alnum(segment) in compact for segment in segments)


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text)


def _stems(text: str) -> set[str]:
    words = re.findall(r"[a-z][a-z\-]+", normalize(text))
    return {w[:6] for w in words if len(w) > 2 and w not in _STOP}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", normalize(text)))


def support_score(claim: str, quote: str) -> float:
    claim_terms = _stems(claim)
    if not claim_terms:
        return 0.0
    return len(claim_terms & _stems(quote)) / len(claim_terms)


def claim_supported(claim: str, quote: str) -> tuple[bool, float, str]:
    score = support_score(claim, quote)
    if not _numbers(claim) <= _numbers(quote):
        return False, score, "claim has numbers not in the quote"
    lowered_claim, lowered_quote = normalize(claim), normalize(quote)
    for token in HIGH_RISK_CLAIM_TOKENS:
        if token in lowered_claim and token not in lowered_quote:
            return False, score, f"high-risk wording '{token}' not in source"
    if score < MIN_SUPPORT:
        return False, score, "claim is not supported by the quote"
    return True, score, "supported"


_CITE = re.compile(r"\[(F\d+)\]")

# Words a summary may use to describe evidence without them counting as new facts.
_META = set("""evidence evidenced research article articles study studies trial trials randomized
randomised controlled systematic review reviews meta-analysis meta-analyses guideline guidelines
individual single small large several multiple source sources data finding findings report reports
reported reporting show shows shown showed suggest suggests suggested indicate indicates indicated
found find demonstrate demonstrated derive derives derived come comes based rather while whereas
however though although overall both including include includes particularly especially generally
compared comparable option options approach approaches strategy strategies treatment treatments
therapy therapies intervention interventions method methods used use using also likely appear
appears limited quality certainty moderate low high effective effectiveness
provide provides provided providing greater alternative alternatives additional offer offers offering
make makes making considered notable carry carries potential available""".split())

MIN_SENTENCE_SUPPORT = 0.6
MAX_NEW_TERMS = 3


def _stems5(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", normalize(text))  # hyphenated words split into parts
    return {w[:5] for w in words if len(w) > 2 and w not in _STOP and w not in _META}


def sentence_supported(sentence: str, reference: str, uncited: str = "") -> bool:
    """A summary sentence may rephrase and combine its cited findings, but may not add
    more than a few new content words, new numbers, or high-risk wording. It also may
    not borrow content found only in findings it does not cite (misattribution)."""
    body = _CITE.sub(" ", sentence)
    terms = _stems5(body)
    if not terms:
        return True
    reference_terms = _stems5(reference)
    new_terms = terms - reference_terms
    if len(new_terms & _stems5(uncited)) >= 2:  # borrows content from findings it doesn't cite
        return False
    score = 1 - len(new_terms) / len(terms)
    if not _numbers(body) <= _numbers(reference):
        return False
    lowered_body, lowered_ref = normalize(body), normalize(reference)
    if any(token in lowered_body and token not in lowered_ref for token in HIGH_RISK_CLAIM_TOKENS):
        return False
    return score >= MIN_SENTENCE_SUPPORT and len(new_terms) <= MAX_NEW_TERMS


def check_sentences(text: str, valid_ids: set[str], references: dict[str, str] | None = None
                    ) -> tuple[str, list[str], list[str]]:
    """Return (kept text, cited ids, rejected sentences).

    Unknown citations are removed; sentences citing no verified finding are rejected.
    With `references` (finding id -> its claim and quote), each sentence must also be
    supported by the text of the findings it cites.
    """
    kept, cited, rejected = [], [], []
    # "Claim. [F1] Next claim." -> "Claim [F1]. Next claim." so citations stay with their sentence.
    text = re.sub(r"([.!?])\s*((?:\[F\d+\]\s*)+)", lambda m: " " + m.group(2).strip() + m.group(1) + " ", text or "")
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not sentence:
            continue
        ids = [i for i in _CITE.findall(sentence) if i in valid_ids]
        cleaned = _CITE.sub(lambda m: m.group(0) if m.group(1) in valid_ids else "", sentence)
        cleaned = re.sub(r"\s+([.,;])", r"\1", " ".join(cleaned.split()))
        supported = bool(ids)
        if supported and references is not None:
            cited_text = " ".join(references[i] for i in ids)
            uncited_text = " ".join(v for k, v in references.items() if k not in ids)
            supported = sentence_supported(cleaned, cited_text, uncited_text)
        if not supported:
            rejected.append(sentence.strip())
            continue
        kept.append(cleaned)
        cited.extend(i for i in ids if i not in cited)
    return " ".join(kept), cited, rejected


def keep_cited_sentences(text: str, valid_ids: set[str],
                         references: dict[str, str] | None = None) -> tuple[str, list[str]]:
    kept, cited, _ = check_sentences(text, valid_ids, references)
    return kept, cited


_REFERENCE_MARKER = re.compile(
    r"\[\s*\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*\s*\]"          # [10, 21]  [3-5]
    r"|(?<![A-Za-z])\(\s*\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*\s*\)"  # (2, 6)  (5), but not I(2)
    r"|\bet al\.?"                                              # Smith et al.
)


def cites_other_work(quote: str) -> bool:
    """True when a quote restates other papers (an introduction/background sentence)
    rather than reporting this source's own findings or recommendations."""
    return bool(_REFERENCE_MARKER.search(quote or ""))


def near_duplicate(claim_a: str, claim_b: str) -> bool:
    """True when every content word of the shorter claim already appears in the other.

    Deliberately strict: "better than placebo" and "better than paracetamol" differ by
    one word and must stay separate. Claims with different numbers never match.
    """
    if _numbers(claim_a) != _numbers(claim_b):
        return False
    a, b = _stems5(claim_a), _stems5(claim_b)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 3 and shorter <= longer
