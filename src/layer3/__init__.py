"""Layer 3 on the database: German and French summaries of the selected rulings, every call traced (docs/LAYER3.md).

The engine (src/summarize/engine.py, v3@a4a1504) reads one ruling and returns an EngineResult
(src/summarize/engine_types.py); this package selects the rulings, splits their considerations (segment V0.1.0),
calls the engine, writes the run's files, then stores everything in summ.* and ops.* in one transaction.
"""
