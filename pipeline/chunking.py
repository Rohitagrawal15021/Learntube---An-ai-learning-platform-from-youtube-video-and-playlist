import nltk
from nltk.tokenize import sent_tokenize


def _ensure_punkt():
    """Download the sentence tokenizer data on first use if it's missing.

    NLTK 3.9+ ships the sentence splitter as the 'punkt_tab' resource, which
    isn't bundled — without this a fresh install crashes with a LookupError.
    """
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)


def chunk_text(text, chunk_size=10000):
    _ensure_punkt()
    sentences = sent_tokenize(text)

    # If sent_tokenize couldn't split well (e.g. no punctuation in non-English
    # auto-captions), break oversized "sentences" on word boundaries so no
    # single piece ever exceeds chunk_size.
    split_sentences = []
    for sentence in sentences:
        if len(sentence) <= chunk_size:
            split_sentences.append(sentence)
        else:
            # Split on spaces to preserve whole words
            words = sentence.split(" ")

            # Some languages (Chinese, Japanese, Thai, ...) have no spaces, so
            # a single "word" can itself exceed chunk_size. Hard-slice any such
            # token on character boundaries so no piece ever overflows.
            tokens = []
            for word in words:
                if len(word) <= chunk_size:
                    tokens.append(word)
                else:
                    for start in range(0, len(word), chunk_size):
                        tokens.append(word[start:start + chunk_size])

            piece = ""
            for word in tokens:
                if len(piece) + len(word) + 1 <= chunk_size:
                    piece = f"{piece} {word}" if piece else word
                else:
                    if piece:
                        split_sentences.append(piece)
                    piece = word
            if piece:
                split_sentences.append(piece)

    chunks = []
    current_chunk = ""

    # for traversing in the sentences-------
    for sentence in split_sentences:
        if len(current_chunk) + len(sentence) <= chunk_size:
            current_chunk += sentence + " "
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # ---- Debug: show chunking results ----
    print(f"\n{'='*60}")
    print(f"CHUNKING REPORT — {len(chunks)} chunks from {len(text)} chars (limit: {chunk_size})")
    print(f"{'='*60}")
    for idx, chunk in enumerate(chunks, 1):
        preview = chunk[:100].replace('\n', ' ')
        print(f"  Chunk {idx}: {len(chunk)} chars | \"{preview}...\"")
    print(f"{'='*60}\n")

    return chunks                

# the below method is basic practise for the chunking by using the python loops we set the token size ans add into the chunk list
# of the size of the token ---- with some overlapping size for the context preservation 
# but htis fails due to translation i have to done after chunking so we use nlp 
# def chunk_text(text, chunk_size=2000, overlap=200):


#     chunks = []

#     start = 0

#     while start < len(text):

#         end = start + chunk_size

#         chunk = text[start:end]

#         chunks.append(chunk)

#         start += chunk_size - overlap

#     return chunks

