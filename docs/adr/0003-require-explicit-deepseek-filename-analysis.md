# Require explicit DeepSeek filename analysis

The application must not send filenames to DeepSeek during directory scanning, file loading, selection changes, or other automatic background work. Each filename-analysis request requires an explicit user action for the chosen track or tracks; this trades automatic convenience for a clear privacy boundary, predictable API cost and latency, and uninterrupted local browsing when DeepSeek is unavailable.
