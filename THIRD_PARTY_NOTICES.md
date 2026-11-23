# Third-Party Notices

## llama.cpp

The server image includes `llama-server` and its shared libraries from
llama.cpp, release `b12413` (Ubuntu x64 build), to run the built-in local model.
The archive is checked against a pinned SHA-256 before use
(`deploy/nas/llama_runtime.py`).

- Source: https://github.com/ggml-org/llama.cpp
- License: MIT (the upstream `LICENSE` is shipped next to the binary, `/opt/llama/LICENSE`)

## Qwen3-4B (GGUF, Q4_K_M)

When the user switches on the built-in local model, the server downloads
`Qwen3-4B-Q4_K_M.gguf` from the `unsloth/Qwen3-4B-GGUF` repository on Hugging
Face (or its mirror). It is not bundled in the image or the repository; the
download is checked against a pinned SHA-256 before use.

- Source: https://huggingface.co/unsloth/Qwen3-4B-GGUF (model by the Qwen team)
- License declared upstream: Apache-2.0
- License text: `licenses/Apache-2.0.txt`
