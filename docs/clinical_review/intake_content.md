# Symptom-intake wording — development content for review

This content is outside the approved-evidence manifest. It is reproduced from [symptom_intake.py](../../health_tools/symptom_intake.py), not endorsed or rewritten. Review its questions, conditional cause lists and safety-net wording for appropriateness and source support.

## Questions

| Slot | Exact question | Reviewer decision / changes |
| --- | --- | --- |
| location | Where exactly is the pain — lower belly, upper belly, one side (left or right), your back, or all over? | |
| cycle_timing | Does it seem linked to your cycle — before your period, during it, mid-cycle, or not related to your period at all? | |
| duration | How long has this been going on — since today, a few days, weeks, or longer? Does it come and go? | |
| severity | On a scale of 0 to 10, how bad is it at its worst? (0 is no pain, 10 is the worst you can imagine) | |
| pregnancy | Is there any chance you could be pregnant? (yes, no, or not sure) | |
| other_symptoms | Have you noticed anything else with it — fever, vomiting, burning when you pee, unusual discharge, bleeding, or feeling dizzy? It's fine to say none. | |
| bleeding_timing | When does the bleeding happen — between periods, after sex, after menopause, or is your period heavier or longer than usual? | |
| amount | How heavy is it — light spotting, like a normal period, or soaking through a pad or tampon every hour or two? | |
| last_period | When did your last period start, roughly? (for example 'about 6 weeks ago') | |
| usual_cycle | Are your periods usually regular, or have they always varied? | |
| discharge_desc | Can you describe it — colour, smell, and whether there's itching or burning? | |

## Order by complaint

- pain: location → cycle_timing → duration → severity → other_symptoms → pregnancy
- bleeding: bleeding_timing → amount → duration → pregnancy → other_symptoms
- cycle: last_period → usual_cycle → pregnancy → other_symptoms
- discharge: discharge_desc → duration → other_symptoms → pregnancy
- general: duration → cycle_timing → severity → other_symptoms → pregnancy

## Possible-cause statements and exact branch conditions

The conditions below are copied as code expressions so their limits remain explicit. They describe what the software selects, not a clinician's differential diagnosis. All review fields are blank.

### Statement

Period cramps (dysmenorrhea) — very common, caused by the womb contracting

Selected under:

```python
intake.complaint in {"pain", "general"}
AND timing == "during periods"
```

Reviewer / decision / required source or change: ____________________

### Statement

Conditions such as endometriosis or fibroids, which can make periods more painful

Selected under:

```python
intake.complaint in {"pain", "general"}
AND timing == "during periods"
AND severity >= 6 or "long-standing" in a.get("duration", "")
```

Reviewer / decision / required source or change: ____________________

### Statement

Ovulation pain — a one-sided twinge or ache around the middle of the cycle, usually short-lived

Selected under:

```python
intake.complaint in {"pain", "general"}
AND ELSE of: timing == "during periods"
AND timing == "mid-cycle"
```

Reviewer / decision / required source or change: ____________________

### Statement

Premenstrual symptoms (PMS), which can include cramping, bloating and tenderness

Selected under:

```python
intake.complaint in {"pain", "general"}
AND ELSE of: timing == "during periods"
AND ELSE of: timing == "mid-cycle"
AND timing == "before periods"
```

Reviewer / decision / required source or change: ____________________

### Statement

Digestive causes such as indigestion, gastritis or gallbladder problems — these are outside what I cover in detail, so a general doctor is the right place to start

Selected under:

```python
intake.complaint in {"pain", "general"}
AND "upper belly" in location
```

Reviewer / decision / required source or change: ____________________

### Statement

A urinary tract (bladder) infection, especially with burning or needing to pee often

Selected under:

```python
intake.complaint in {"pain", "general"}
AND ELSE of: "upper belly" in location
AND timing in {"not related to periods", "not sure", ""} or not timing
AND "burning when peeing" in other
```

Reviewer / decision / required source or change: ____________________

### Statement

Bowel causes such as constipation, trapped wind or irritable bowel

Selected under:

```python
intake.complaint in {"pain", "general"}
AND ELSE of: "upper belly" in location
AND timing in {"not related to periods", "not sure", ""} or not timing
AND "diarrhoea or constipation" in other or "bloating" in other or not other or other == "none"
```

Reviewer / decision / required source or change: ____________________

### Statement

An ovarian cyst, which can cause one-sided pelvic pain

Selected under:

```python
intake.complaint in {"pain", "general"}
AND ELSE of: "upper belly" in location
AND timing in {"not related to periods", "not sure", ""} or not timing
AND "lower belly" in location or "left side" in location or "right side" in location
```

Reviewer / decision / required source or change: ____________________

### Statement

A pelvic infection, which needs prompt testing and treatment

Selected under:

```python
intake.complaint in {"pain", "general"}
AND ELSE of: "upper belly" in location
AND timing in {"not related to periods", "not sure", ""} or not timing
AND "unusual discharge" in other or "fever" in other or "pain during sex" in other
```

Reviewer / decision / required source or change: ____________________

### Statement

Appendicitis is important to rule out if the pain gets worse or spreads, or if fever or vomiting start

Selected under:

```python
intake.complaint in {"pain", "general"}
AND ELSE of: "upper belly" in location
AND timing in {"not related to periods", "not sure", ""} or not timing
AND "right side" in location
```

Reviewer / decision / required source or change: ____________________

### Statement

Any bleeding after menopause should be checked by a doctor soon, even if it's light

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND intake.complaint == "bleeding"
AND timing_b == "after menopause"
```

Reviewer / decision / required source or change: ____________________

### Statement

Changes or inflammation of the cervix, or an infection — a check-up and up-to-date cervical screening help

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND intake.complaint == "bleeding"
AND ELSE of: timing_b == "after menopause"
AND timing_b == "after sex"
```

Reviewer / decision / required source or change: ____________________

### Statement

Hormonal changes, contraception side effects, polyps or infection

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND intake.complaint == "bleeding"
AND ELSE of: timing_b == "after menopause"
AND ELSE of: timing_b == "after sex"
AND timing_b == "between periods"
```

Reviewer / decision / required source or change: ____________________

### Statement

Heavy menstrual bleeding, which can be linked to fibroids, polyps or hormonal changes — it's also worth checking iron levels

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND intake.complaint == "bleeding"
AND ELSE of: timing_b == "after menopause"
AND ELSE of: timing_b == "after sex"
AND ELSE of: timing_b == "between periods"
```

Reviewer / decision / required source or change: ____________________

### Statement

Pregnancy — a home pregnancy test is a sensible first step

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND ELSE of: intake.complaint == "bleeding"
AND intake.complaint == "cycle"
AND a.get("pregnancy") in {"possible", "not sure"}
```

Reviewer / decision / required source or change: ____________________

### Statement

Stress, weight change, intense exercise, thyroid problems, PCOS or perimenopause, which can all change cycles

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND ELSE of: intake.complaint == "bleeding"
AND intake.complaint == "cycle"
```

Reviewer / decision / required source or change: ____________________

### Statement

A yeast (thrush) infection, which often causes itching and thick white discharge

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND ELSE of: intake.complaint == "bleeding"
AND ELSE of: intake.complaint == "cycle"
AND intake.complaint == "discharge"
AND "itch" in desc or "thick" in desc or "white" in desc
```

Reviewer / decision / required source or change: ____________________

### Statement

Bacterial vaginosis, which often causes a thin discharge with a fishy smell

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND ELSE of: intake.complaint == "bleeding"
AND ELSE of: intake.complaint == "cycle"
AND intake.complaint == "discharge"
AND "fish" in desc or "grey" in desc or "gray" in desc
```

Reviewer / decision / required source or change: ____________________

### Statement

A sexually transmitted infection — testing is simple and confidential

Selected under:

```python
ELSE of: intake.complaint in {"pain", "general"}
AND ELSE of: intake.complaint == "bleeding"
AND ELSE of: intake.complaint == "cycle"
AND intake.complaint == "discharge"
```

Reviewer / decision / required source or change: ____________________

### Statement

Several everyday causes are possible, and a doctor can narrow them down with a short examination

Selected under:

```python
not items
```

Reviewer / decision / required source or change: ____________________

## Exact safety-net statements

Get urgent care now if the pain becomes severe or sudden, you faint or feel very dizzy, you have a fever with the pain, you're vomiting and can't keep fluids down, or there's any chance you're pregnant and you have pain or bleeding.

Reviewer / decision / required change: ____________________

Book a doctor's appointment if it lasts more than a few days, keeps coming back, gets worse, or affects your daily life.

Reviewer / decision / required change: ____________________
