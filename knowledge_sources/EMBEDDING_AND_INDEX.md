# Local vector index

The repository includes `scripts/build_knowledge_index.py` for building a local
Chroma database with the Chinese-focused `BAAI/bge-small-zh-v1.5` model.
The model is downloaded by FastEmbed on first use. The generated database and
candidate rules belong in `knowledge_db/`, which is ignored by Git because it
contains generated binary data.

Candidate rules are review material only. An expert must approve them before
they become production `BaselineRule` entries.
