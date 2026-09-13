"""News tool: acquisitions and events that could move the price.

Fetches recent headlines for a symbol (source pending: yfinance news,
NewsAPI, or a Kaggle set). Feeds the prompt-chaining workflow: ingest ->
preprocess -> classify -> extract -> summarize.
"""
