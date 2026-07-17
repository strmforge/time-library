# Third-Party Notices

## IBM Granite Embedding 97M Multilingual R2

Time Library can optionally download `ibm-granite/granite-embedding-97m-multilingual-r2`
when the user enables vector recall. The model is not bundled in the Time Library
release archive.

- Source: https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2
- Pinned revision: `835ad14087e140460703cf0fae09f97d469d65c2`
- License declared by the upstream model card: Apache-2.0
- License text shipped with Time Library: `licenses/Apache-2.0.txt`

Downloaded model files are verified against the pinned per-file SHA-256 manifest
in `src/granite_vector_assets.py` before they become active.

## PyYAML

Time Library's macOS and Linux installers use PyYAML to update an existing Hermes
configuration through a structured parser. PyYAML is installed as a runtime
dependency and is not bundled in the release archive.

- Source: https://github.com/yaml/pyyaml
- License: MIT
- License text shipped with Time Library: `licenses/PyYAML-MIT.txt`
