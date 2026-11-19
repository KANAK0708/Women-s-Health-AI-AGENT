"""Domains the research agent may read. Edit this list to widen or narrow scope.

Only HTTPS pages on these hosts (or their subdomains) are fetched. Search results
pointing anywhere else are discarded before any request is made.
"""

from urllib.parse import urlsplit

# domain -> source_type used for evidence ranking
ALLOWED_DOMAINS: dict[str, str] = {
    # Public health agencies and official guidance
    "who.int": "official_guidance",
    "cdc.gov": "official_guidance",
    "nih.gov": "official_guidance",          # incl. nichd.nih.gov
    "ncbi.nlm.nih.gov": "research_article",  # PubMed / PMC papers are studies, not guidance
    "womenshealth.gov": "official_guidance",
    "nice.org.uk": "official_guidance",
    "nhs.uk": "official_guidance",
    "fda.gov": "official_guidance",
    "healthdirect.gov.au": "official_guidance",
    # Professional societies
    "acog.org": "professional_society",
    "rcog.org.uk": "professional_society",
    "figo.org": "professional_society",
    "asrm.org": "professional_society",
    "endocrine.org": "professional_society",
    "menopause.org": "professional_society",
    "eshre.eu": "professional_society",
    # Consumer health references
    "medlineplus.gov": "consumer_health",
    "mayoclinic.org": "consumer_health",
    "clevelandclinic.org": "consumer_health",
    # Literature
    "europepmc.org": "research_article",
    "ebi.ac.uk": "research_article",
    "cochranelibrary.com": "systematic_review",
}


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def matched_domain(url: str) -> str | None:
    """Return the allowlisted domain covering an HTTPS URL, else None."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password:
        return None
    if parts.port not in (None, 443):
        return None
    host = host_of(url)
    matches = [d for d in ALLOWED_DOMAINS if host == d or host.endswith("." + d)]
    return max(matches, key=len) if matches else None  # most specific wins


def is_allowed(url: str) -> bool:
    return matched_domain(url) is not None


def source_type_for(url: str) -> str:
    domain = matched_domain(url)
    return ALLOWED_DOMAINS[domain] if domain else "web"
