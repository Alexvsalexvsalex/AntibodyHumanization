from multiprocessing import Pool
from typing import List, Tuple, Optional

from humanization import config_loader
from humanization.annotations import Annotation, ChainType, GeneralChainType, annotate_single
from humanization.dataset_preparer import read_human_samples
from humanization.utils import configure_logger

config = config_loader.Config()
logger = configure_logger(config, "V Gene Scorer")


def calc_score(seq_1: List[str], seq_2: str, annotation: Annotation) -> float:
    same, total = 0, 0
    for i in range(annotation.v_gene_end + 1):
        if seq_1[i] != 'X' or seq_2[i] != 'X':
            total += 1
            if seq_1[i] == seq_2[i]:
                same += 1
    return same / total


def is_v_gene_score_less(first: Optional[float], second: Optional[float]) -> bool:
    if first is None or second is None:
        return True
    return first < second


def calc_score_wrapper(sample):
    return calc_score(sequence, sample, annotation)


def worker_init(seq, ann):
    global sequence, annotation
    sequence = seq
    annotation = ann


class VGeneScorer:
    def __init__(self, annotation: Annotation, human_samples: List[str], labels: List[str]):
        self.annotation = annotation
        self.human_samples = human_samples
        self.labels = labels
        if len(self.human_samples) != len(self.labels):
            raise RuntimeError(f"Lengths are different. Samples: {len(self.human_samples)}, labels: {len(self.labels)}")

    def query(self, sequence: List[str]) -> List[Tuple[str, float, str]]:
        worker_args = sequence, self.annotation
        with Pool(processes=config.get(config_loader.NCPU), initializer=worker_init, initargs=worker_args) as pool:
            v_gene_scores = pool.map(calc_score_wrapper, self.human_samples)
        result = []
        for idx, v_gene_score in sorted(enumerate(v_gene_scores), key=lambda x: x[1], reverse=True)[:2]:
            logger.debug(f"{idx + 1} candidate: {v_gene_score}")
            result.append((self.human_samples[idx], v_gene_score, self.labels[idx]))
        return result


def build_v_gene_scorer(annotation: Annotation, dataset_file: str,
                        v_type: ChainType = None) -> Optional[VGeneScorer]:
    human_dataset = read_human_samples(dataset_file, annotation, v_type)
    if human_dataset is not None:
        v_gene_scorer = VGeneScorer(annotation, human_dataset[0], human_dataset[1])
        logger.info(f"Created VGeneScorer with {len(human_dataset[0])} samples")
        return v_gene_scorer
    else:
        return None


def get_similar_human_samples(annotation: Annotation, dataset_file: str, sequences: List[str],
                              chain_type: GeneralChainType) -> List[Optional[List[Tuple[str, float, str]]]]:
    v_gene_scorer = build_v_gene_scorer(annotation, dataset_file)
    result = []
    for seq in sequences:
        aligned_seq = annotate_single(seq, annotation, chain_type)
        result.append(v_gene_scorer.query(aligned_seq) if aligned_seq is not None else None)
    return result
