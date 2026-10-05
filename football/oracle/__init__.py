"""Oracle: a from-scratch match predictor. One scraped report JSON in -> facts -> quantitative engine (goal rates from
several sources, player-level absence impact, exact score distribution) -> LLM panel that reads the context and
proposes bounded, evidence-cited adjustments -> calibrated final prediction with a full trace.

    python -m football.oracle report.json [--llm auto|none|nvidia|openrouter|ollama] [--with-odds]

Modules: facts (JSON -> Facts), quant (rates + exact score distribution), llm (providers, cache), context (LLM panel), oracle (pipeline, report).
"""
