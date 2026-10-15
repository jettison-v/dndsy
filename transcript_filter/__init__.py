"""Local transcript filter. Runs only on Brett's Mac; raw text never leaves it.

Pipeline: MacWhisper segments JSON -> echo de-dup -> Ollama off-topic filter
-> filtered transcript + local review page.
"""
