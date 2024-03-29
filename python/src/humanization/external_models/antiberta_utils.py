from typing import List

import numpy as np
from transformers import pipeline, RoFormerForMaskedLM, RoFormerTokenizer

antiberta_tokenizer = RoFormerTokenizer.from_pretrained("alchemab/antiberta2")
antiberta_model = RoFormerForMaskedLM.from_pretrained("alchemab/antiberta2")
filler = pipeline("fill-mask", model=antiberta_model, tokenizer=antiberta_tokenizer)


def get_antiberta_embeddings(seqs: List[str]) -> np.array:
    inputs = antiberta_tokenizer(seqs, return_tensors="pt")
    outputs = antiberta_model(**inputs, output_hidden_states=True)
    embedding_2d = outputs.hidden_states[-1][:, 0, :].detach().numpy()
    return embedding_2d


def get_antiberta_embedding(seq: str) -> np.array:
    return get_antiberta_embeddings([seq])[0, :]


def fill_mask(seq: str) -> str:
    result = filler(seq)
    return result[0]['sequence'].replace(' ', '').replace('Ḣ', 'H')


def get_mask_values(seq: List[str]) -> List[str]:
    result = filler(seq)
    if len(seq) == 1:
        result = [result]
    return [res[0]['token_str'].replace('Ḣ', 'H') for res in result]


def get_mask_value(seq: str) -> str:
    return get_mask_values([seq])[0]
