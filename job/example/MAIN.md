---
frequency: daily
phase: ignore
---

# Example Job

This is a sample job for the Anya headless LLM agent.

## Instructions

Analyze any fetched data and produce a brief summary. If you find anything critical
that should be remembered across runs, wrap it in:

```
---MEMORY---
<critical finding>
---END MEMORY---
```

Otherwise, just output a short report. The report will be emailed and logged to the blotter.

## Fetch instructions

You can add fetch URLs in a `fetch.py` script in this directory, or use inline actions:

---ACTION---
fetch('https://old.reddit.com/r/LocalLLaMA/')
---END ACTION---

The executor runs any `.py` files in the job dir before calling the LLM.
