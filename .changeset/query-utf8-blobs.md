---
"trackio": patch
---

fix: decode UTF-8 blobs in `trackio query` output instead of hex-encoding them, so JSON columns like `config` and `metrics` are readable
