# Allowed research sources — reviewer decisions blank

These are the current code settings, not clinical approvals. The inclusion rationale below is an explanation inferred from the configured source role, not a recorded clinician decision or verification of each site's content.

Source: [allowlist.py](../../health_tools/research/allowlist.py). All 22 configured domains are listed, including subdomain access.

| Domain | Code evidence type | What the site is | Intended reason for inclusion (review required) | Reviewer decision |
| --- | --- | --- | --- | --- |
| who.int | `official_guidance` | World Health Organization | International public-health background and guidance. | |
| cdc.gov | `official_guidance` | US Centers for Disease Control and Prevention | Public-health education, screening and prevention material. | |
| nih.gov | `official_guidance` | US National Institutes of Health, including NICHD | Government health education; the more specific NCBI mapping takes precedence. | |
| ncbi.nlm.nih.gov | `research_article` | NCBI / National Library of Medicine, including PubMed and PMC | Literature records and papers; being hosted by NIH does not make a paper official guidance. | |
| womenshealth.gov | `official_guidance` | US Office on Women's Health | Women-focused public-health education. | |
| nice.org.uk | `official_guidance` | UK National Institute for Health and Care Excellence | Clinical guidance and related public information. | |
| nhs.uk | `official_guidance` | UK National Health Service | Public-facing health explanations and care information. | |
| fda.gov | `official_guidance` | US Food and Drug Administration | Regulatory safety and medical-product information. | |
| healthdirect.gov.au | `official_guidance` | Healthdirect Australia | Australian public-facing health information. | |
| acog.org | `professional_society` | American College of Obstetricians and Gynecologists | Specialist obstetric and gynecologic education and guidance. | |
| rcog.org.uk | `professional_society` | Royal College of Obstetricians and Gynaecologists | Specialist obstetric and gynecologic education and guidance. | |
| figo.org | `professional_society` | International Federation of Gynecology and Obstetrics | International professional-society material. | |
| asrm.org | `professional_society` | American Society for Reproductive Medicine | Professional reproductive-health and fertility material. | |
| endocrine.org | `professional_society` | Endocrine Society | Professional endocrine-health material relevant to reproductive conditions. | |
| menopause.org | `professional_society` | The Menopause Society | Professional menopause education and guidance. | |
| eshre.eu | `professional_society` | European Society of Human Reproduction and Embryology | Professional reproductive-health material. | |
| medlineplus.gov | `consumer_health` | MedlinePlus / US National Library of Medicine | Consumer health explanations; not assigned the same tier as formal guidelines. | |
| mayoclinic.org | `consumer_health` | Mayo Clinic | Consumer-facing condition explanations. | |
| clevelandclinic.org | `consumer_health` | Cleveland Clinic | Consumer-facing condition explanations. | |
| europepmc.org | `research_article` | Europe PMC | Biomedical literature and open-access records. | |
| ebi.ac.uk | `research_article` | EMBL European Bioinformatics Institute | Europe PMC full-text API and literature hosting. | |
| cochranelibrary.com | `systematic_review` | Cochrane Library | Evidence synthesis and systematic reviews. | |

## How a page becomes a guideline

The code checks HTTPS, rejects URL credentials and nonstandard ports, and allows exact hosts or their subdomains. The most specific configured domain wins. It then searches the host/path string against these exact case-insensitive patterns:

### nice.org.uk

```regex
^www\.nice\.org\.uk/guidance/
```

### acog.org

```regex
/clinical/(?:clinical-)?guidance/|practice-bulletin|committee-opinion|clinical-practice-guideline
```

### rcog.org.uk

```regex
/guidance/|green-top
```

### who.int

```regex
/publications/(?:i|m)/item/|/iris/
```

A matching path is labelled `guideline`; other pages keep their domain's default type. This is a URL heuristic, not confirmation that the page is a current, applicable guideline. PubMed/Europe PMC adapters also infer study type from publication metadata or title text (see [sources.py](../../health_tools/research/sources.py)). They look for guideline, systematic-review/meta-analysis, trial, and review labels; these labels do not independently establish study quality.

The focused guideline search uses WHO, NICE, ACOG, RCOG and CDC, through DuckDuckGo. Generic searches can read any of the configured domains. The reader rechecks the allowlist on redirects and the final URL, checks robots.txt, limits response size and pages, and strips navigation/script content. An unreadable robots.txt is treated as allowed. These technical controls do not validate clinical relevance, translation, or permission to reuse text.

Evidence display tiers: Strong = guideline / official_guidance / systematic_review; Moderate = professional_society / rct / narrative_review; Limited = research_article / consumer_health / web. A tier is a source-type label, not clinical approval.

## QUESTIONS FOR THE REVIEWER

- Q-SOURCE-01: Is a whole government or society domain a suitable basis for a Strong/Moderate label, including press releases and public information pages?
- Q-SOURCE-02: Could broad WHO publication paths or words in paper titles incorrectly label non-guidelines as guidelines? Should currency, jurisdiction, population and formal methodology be checked separately?
- Q-SOURCE-03: Are professional societies, consumer sites, general NIH/EBI subdomains and Cochrane pages appropriate as currently ranked? Review every row above.
- Q-SOURCE-04: The main evidence manifest contains a Monash PCOS guideline URL, but `monash.edu` is not in the research allowlist. Should the research agent be able to read the primary guideline directly? No domain has been added here.
- Q-SOURCE-05: Which materials require specific rights, language, update and conflict-of-interest review? Should unavailable/restricted guidance leave an explicit clinical gap rather than a substitute source?
- Q-SOURCE-06: Is it appropriate to omit visible non-English URL paths from search results, while otherwise lacking a reliable document-language check? What local-language sources are needed?
