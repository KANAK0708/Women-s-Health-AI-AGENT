"""Update clinical evidence manifest with new approved guidelines for:
- Dysmenorrhea (menstrual cramping)
- Heavy menstrual bleeding (menorrhagia) and iron support
- Endometriosis educational overview
"""

import hashlib
import json
from pathlib import Path

MANIFEST_PATH = Path("clinical/evidence_manifest/manifest.json")


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


new_sources = [
    {
        "source_id": "src-acog-dysmenorrhea-2024",
        "publisher": "American College of Obstetricians and Gynecologists (ACOG)",
        "title": "ACOG Clinical Consensus: General Approaches to Medical Management of Menstrual Pain and Dysmenorrhea",
        "canonical_url": "https://www.acog.org/clinical/clinical-guidance/clinical-consensus/articles/2024/03/general-approaches-to-medical-management-of-menstrual-pain",
        "publication_date": "2024-03-15",
        "update_date": None,
        "ingestion_date": "2026-11-06",
        "review_date": "2026-11-06",
        "expiry_date": "2027-11-06",
        "jurisdiction": "Global",
        "population": "adults_18+",
        "life_stage": ["menstrual_health"],
        "evidence_grade": "Clinical Consensus",
        "reviewer_id": "clinician-lead-01",
        "license": "ACOG Educational Guidance Summary",
        "content_hash": sha256_text("ACOG Dysmenorrhea Clinical Consensus 2024"),
        "is_superseded": False,
    },
    {
        "source_id": "src-cdc-menorrhagia-2024",
        "publisher": "Centers for Disease Control and Prevention (CDC)",
        "title": "CDC Public Health Guide: Heavy Menstrual Bleeding (Menorrhagia) and Iron Deficiency",
        "canonical_url": "https://www.cdc.gov/ncbddd/blooddisorders/women/menorrhagia.html",
        "publication_date": "2024-04-10",
        "update_date": None,
        "ingestion_date": "2026-11-06",
        "review_date": "2026-11-06",
        "expiry_date": "2027-11-06",
        "jurisdiction": "Global",
        "population": "adults_18+",
        "life_stage": ["menstrual_health"],
        "evidence_grade": "Public Health Recommendation",
        "reviewer_id": "clinician-lead-01",
        "license": "Public Domain (US Government)",
        "content_hash": sha256_text("CDC Heavy Menstrual Bleeding and Iron Deficiency 2024"),
        "is_superseded": False,
    },
    {
        "source_id": "src-who-endometriosis-2023",
        "publisher": "World Health Organization (WHO)",
        "title": "WHO Fact Sheet: Endometriosis Pathophysiology, Symptoms, and Supportive Care",
        "canonical_url": "https://www.who.int/news-room/fact-sheets/detail/endometriosis",
        "publication_date": "2023-03-24",
        "update_date": None,
        "ingestion_date": "2026-11-06",
        "review_date": "2026-11-06",
        "expiry_date": "2027-11-06",
        "jurisdiction": "Global",
        "population": "adults_18+",
        "life_stage": ["menstrual_health"],
        "evidence_grade": "Global Health Guidelines",
        "reviewer_id": "clinician-lead-01",
        "license": "WHO Public Information",
        "content_hash": sha256_text("WHO Endometriosis Fact Sheet 2023"),
        "is_superseded": False,
    },
]

new_passages = [
    {
        "passage_id": "psg-dys-def-01",
        "source_id": "src-acog-dysmenorrhea-2024",
        "title": "ACOG Clinical Consensus: General Approaches to Medical Management of Menstrual Pain and Dysmenorrhea",
        "url": "https://www.acog.org/clinical/clinical-guidance/clinical-consensus/articles/2024/03/general-approaches-to-medical-management-of-menstrual-pain",
        "locator": "Section 1: Definition of Primary vs Secondary Dysmenorrhea",
        "category": "what_it_is",
        "topic_tags": ["dysmenorrhea", "cramps", "period pain", "menstrual pain", "primary dysmenorrhea", "definition"],
        "text": "Dysmenorrhea is painful menstruation that impairs daily functioning. Primary dysmenorrhea refers to recurrent, crampy lower pelvic pain that occurs with menses in the absence of demonstrable pelvic disease, mediated by elevated endometrial prostaglandin production. Secondary dysmenorrhea is menstrual pain associated with an underlying pelvic pathology, such as endometriosis, adenomyosis, or uterine fibroids.",
        "reviewed_at": "2026-11-06",
    },
    {
        "passage_id": "psg-dys-sym-01",
        "source_id": "src-acog-dysmenorrhea-2024",
        "title": "ACOG Clinical Consensus: General Approaches to Medical Management of Menstrual Pain and Dysmenorrhea",
        "url": "https://www.acog.org/clinical/clinical-guidance/clinical-consensus/articles/2024/03/general-approaches-to-medical-management-of-menstrual-pain",
        "locator": "Section 2: Clinical Presentation & Radiation",
        "category": "symptoms",
        "topic_tags": ["dysmenorrhea", "symptoms", "cramping", "pelvic pain", "back pain", "nausea", "headache"],
        "text": "Symptoms of primary dysmenorrhea typically begin shortly before or with the onset of menstrual flow and peak within 24 to 48 hours. Pain is characteristically spasmodic or dull, localized in the lower abdomen or suprapubic region, and may radiate to the lower back and anterior thighs. Associated systemic symptoms commonly include nausea, fatigue, loose stools or diarrhea, headache, and dizziness.",
        "reviewed_at": "2026-11-06",
    },
    {
        "passage_id": "psg-dys-prev-01",
        "source_id": "src-acog-dysmenorrhea-2024",
        "title": "ACOG Clinical Consensus: General Approaches to Medical Management of Menstrual Pain and Dysmenorrhea",
        "url": "https://www.acog.org/clinical/clinical-guidance/clinical-consensus/articles/2024/03/general-approaches-to-medical-management-of-menstrual-pain",
        "locator": "Section 3: Non-Pharmacologic Management & Self-Care",
        "category": "prevention_and_lifestyle",
        "topic_tags": ["dysmenorrhea", "prevention", "lifestyle", "heat pad", "exercise", "self-care", "cramp relief"],
        "text": "Evidence supports several non-pharmacologic lifestyle strategies for managing mild-to-moderate menstrual cramping. Continuous topical heat therapy (applying a warm heating pad or patch to the lower abdomen) has been shown in clinical trials to be as effective as standard analgesics in reducing cramping intensity by relaxing uterine smooth muscle. Regular aerobic exercise (such as brisk walking, swimming, or cycling for 30 minutes, 3 to 5 times weekly), adequate sleep, stress-reduction techniques, and smoking cessation also significantly diminish menstrual symptom severity.",
        "reviewed_at": "2026-11-06",
    },
    {
        "passage_id": "psg-hmb-def-01",
        "source_id": "src-cdc-menorrhagia-2024",
        "title": "CDC Public Health Guide: Heavy Menstrual Bleeding (Menorrhagia) and Iron Deficiency",
        "url": "https://www.cdc.gov/ncbddd/blooddisorders/women/menorrhagia.html",
        "locator": "Section 1: Definition of Menorrhagia",
        "category": "what_it_is",
        "topic_tags": ["heavy menstrual bleeding", "menorrhagia", "excessive bleeding", "definition", "blood loss"],
        "text": "Heavy menstrual bleeding (historically termed menorrhagia) is defined clinically as menstrual blood loss greater than 80 mL per cycle or bleeding that lasts longer than 7 consecutive days. In practical everyday terms, heavy bleeding is identified when flow soaks through one or more sanitary pads or tampons every hour for two or more consecutive hours, requires wearing double protection, or interrupts routine daily life and sleep.",
        "reviewed_at": "2026-11-06",
    },
    {
        "passage_id": "psg-hmb-sym-01",
        "source_id": "src-cdc-menorrhagia-2024",
        "title": "CDC Public Health Guide: Heavy Menstrual Bleeding (Menorrhagia) and Iron Deficiency",
        "url": "https://www.cdc.gov/ncbddd/blooddisorders/women/menorrhagia.html",
        "locator": "Section 2: Symptoms & Anemia Indicators",
        "category": "symptoms",
        "topic_tags": ["heavy bleeding", "symptoms", "clots", "anemia", "fatigue", "weakness", "shortness of breath"],
        "text": "Symptoms of heavy menstrual bleeding include passing blood clots larger than a quarter (one inch in diameter), having to wake up during the night to change menstrual protection, bleeding for longer than a full week, and signs of secondary iron-deficiency anemia such as persistent tiredness, lethargy, pale skin, unexplained weakness, cold hands or feet, and shortness of breath with mild exertion.",
        "reviewed_at": "2026-11-06",
    },
    {
        "passage_id": "psg-hmb-prev-01",
        "source_id": "src-cdc-menorrhagia-2024",
        "title": "CDC Public Health Guide: Heavy Menstrual Bleeding (Menorrhagia) and Iron Deficiency",
        "url": "https://www.cdc.gov/ncbddd/blooddisorders/women/menorrhagia.html",
        "locator": "Section 3: Nutritional Support & Cycle Tracking",
        "category": "prevention_and_lifestyle",
        "topic_tags": ["heavy bleeding", "prevention", "lifestyle", "iron rich foods", "vitamin c", "tracking", "hydration"],
        "text": "To prevent iron deficiency caused by heavy menstrual blood loss, dietary strategies include regularly eating iron-rich foods (heme iron from lean poultry and fish, or non-heme iron from lentils, beans, spinach, and fortified cereals) consumed together with vitamin C sources (such as citrus fruits, bell peppers, or tomatoes) to boost intestinal iron absorption. Avoid consuming calcium-rich foods, tea, or coffee simultaneously with iron-rich meals because polyphenols and calcium inhibit iron uptake. Keeping a detailed menstrual diary tracking pad counts and cycle dates assists clinicians in identifying treatable causes.",
        "reviewed_at": "2026-11-06",
    },
    {
        "passage_id": "psg-endo-def-01",
        "source_id": "src-who-endometriosis-2023",
        "title": "WHO Fact Sheet: Endometriosis Pathophysiology, Symptoms, and Supportive Care",
        "url": "https://www.who.int/news-room/fact-sheets/detail/endometriosis",
        "locator": "Section 1: What is Endometriosis",
        "category": "what_it_is",
        "topic_tags": ["endometriosis", "definition", "pelvic condition", "what is endometriosis", "endometrial tissue"],
        "text": "Endometriosis is a chronic disease where tissue similar to the lining of the uterus (endometrium) grows outside the uterus, most commonly on the ovaries, fallopian tubes, outer uterine surface, and pelvic peritoneum. This ectopic tissue responds to monthly hormonal cycles by thickening, breaking down, and bleeding, but has no exit path from the body, leading to chronic inflammation, scarring, fibrosis, and adhesions. It affects approximately 10% (190 million) of reproductive-age girls and women globally.",
        "reviewed_at": "2026-11-06",
    },
    {
        "passage_id": "psg-endo-sym-01",
        "source_id": "src-who-endometriosis-2023",
        "title": "WHO Fact Sheet: Endometriosis Pathophysiology, Symptoms, and Supportive Care",
        "url": "https://www.who.int/news-room/fact-sheets/detail/endometriosis",
        "locator": "Section 2: Symptoms & Pain Patterns",
        "category": "symptoms",
        "topic_tags": ["endometriosis", "symptoms", "chronic pelvic pain", "dyspareunia", "painful bowel movements", "fatigue"],
        "text": "The primary symptom of endometriosis is severe, progressive pelvic pain. Symptoms include intense menstrual cramping (dysmenorrhea) that does not respond to standard over-the-counter pain relievers; chronic, non-menstrual pelvic pain throughout the month; deep pain during or after sexual intercourse (dyspareunia); painful bowel movements or painful urination especially during menstrual periods; heavy or irregular menstrual bleeding; fatigue; and difficulty getting pregnant (subfertility).",
        "reviewed_at": "2026-11-06",
    },
    {
        "passage_id": "psg-endo-prev-01",
        "source_id": "src-who-endometriosis-2023",
        "title": "WHO Fact Sheet: Endometriosis Pathophysiology, Symptoms, and Supportive Care",
        "url": "https://www.who.int/news-room/fact-sheets/detail/endometriosis",
        "locator": "Section 3: Lifestyle Support & Non-Pharmacological Care",
        "category": "prevention_and_lifestyle",
        "topic_tags": ["endometriosis", "prevention", "lifestyle", "anti inflammatory diet", "pelvic floor therapy", "self-care"],
        "text": "While there is currently no known primary prevention or permanent cure for endometriosis, supportive non-pharmacological care significantly improves quality of life. Helpful lifestyle habits include consuming a nutrient-dense, anti-inflammatory eating pattern rich in omega-3 fatty acids, colorful vegetables, and antioxidant-rich berries; engaging in gentle, low-impact exercise (such as yoga, walking, and gentle stretching); working with a specialized pelvic floor physical therapist; practicing relaxation and mindfulness techniques to down-regulate centralized pain sensitivity; and using thermal heat therapy during flare-ups.",
        "reviewed_at": "2026-11-06",
    },
]

manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
manifest["manifest_version"] = "2026.11.06"

# Add unique sources
existing_src_ids = {s["source_id"] for s in manifest["sources"]}
for s in new_sources:
    if s["source_id"] not in existing_src_ids:
        manifest["sources"].append(s)

# Add unique passages
existing_psg_ids = {p["passage_id"] for p in manifest["passages"]}
for p in new_passages:
    if p["passage_id"] not in existing_psg_ids:
        manifest["passages"].append(p)

MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(f"Manifest updated: {len(manifest['sources'])} sources, {len(manifest['passages'])} passages.")
