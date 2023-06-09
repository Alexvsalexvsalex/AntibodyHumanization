import argparse
from typing import Optional, List, Tuple

from humanization import config_loader
from humanization.abstract_humanizer import seq_to_str, IterationDetails, is_change_less, SequenceChange, \
    AbstractHumanizer, read_humanizer_options, run_humanizer, abstract_humanizer_parser_options
from humanization.annotations import annotate_single
from humanization.models import ModelWrapper, load_model
from humanization.utils import configure_logger, parse_list, read_sequences, write_sequences
from humanization.v_gene_scorer import VGeneScorer, build_v_gene_scorer, is_v_gene_score_less

config = config_loader.Config()
logger = configure_logger(config, "Reverse humanizer")


class ReverseHumanizer(AbstractHumanizer):
    def __init__(self, model_wrapper: ModelWrapper, v_gene_scorer: Optional[VGeneScorer],
                 skip_positions: List[str], use_aa_similarity: bool):
        super().__init__(model_wrapper, v_gene_scorer)
        self.skip_positions = skip_positions
        self.use_aa_similarity = use_aa_similarity

    def _test_single_change(self, sequence: List[str], column_idx: int, new_aa: str) -> SequenceChange:
        aa_backup = sequence[column_idx]
        if aa_backup == new_aa:
            return SequenceChange(None, aa_backup, None, -1.0)
        sequence[column_idx] = new_aa
        new_value = self.model_wrapper.model.predict_proba(sequence)[1]
        candidate_change = SequenceChange(column_idx, aa_backup, new_aa, new_value)
        sequence[column_idx] = aa_backup
        return candidate_change

    def _find_best_change(self, current_seq: List[str], original_seq: List[str]):
        best_change = SequenceChange(None, None, None, -1.0)
        for idx, column_name in enumerate(self.model_wrapper.annotation.segmented_positions):
            if column_name in self.skip_positions:
                continue
            candidate_change = self._test_single_change(current_seq, idx, original_seq[idx])
            if is_change_less(best_change, candidate_change, self.use_aa_similarity):
                best_change = candidate_change
        return best_change

    def query(self, sequence: str, target_model_metric: float,
              target_v_gene_score: float = 0.0, human_sample: str = None) -> Tuple[str, List[IterationDetails]]:
        current_seq = annotate_single(sequence, self.model_wrapper.annotation)
        if current_seq is None:
            raise RuntimeError(f"{sequence} cannot be annotated")
        original_seq = [x for x in current_seq]
        logger.debug(f"Annotated sequence: {seq_to_str(current_seq, True)}")
        if human_sample:
            human_sample = annotate_single(human_sample, self.model_wrapper.annotation)
        if not human_sample:
            logger.debug(f"Retrieve human sample from V Gene scorer")
            human_sample, _ = self.v_gene_scorer.query(current_seq)
        logger.info(f"Used human sample: {human_sample}")
        for idx, column_name in enumerate(self.model_wrapper.annotation.segmented_positions):
            if column_name.startswith("fwr"):
                current_seq[idx] = human_sample[idx]
        logger.info(f"Chimeric sequence: {seq_to_str(current_seq, True)}")
        iterations = []
        current_value, v_gene_score = self._calc_metrics(current_seq, human_sample)
        iterations.append(IterationDetails(0, current_value, v_gene_score, None))
        for it in range(1, config.get(config_loader.MAX_CHANGES) + 1):
            current_value, v_gene_score = self._calc_metrics(current_seq, human_sample)
            logger.info(f"Iteration {it}. "
                        f"Current model metric = {round(current_value, 6)}, V Gene score = {v_gene_score}")
            best_change = self._find_best_change(current_seq, original_seq)
            if best_change.is_defined():
                prev_aa = current_seq[best_change.position]
                current_seq[best_change.position] = best_change.aa
                best_value, v_gene_score = self._calc_metrics(current_seq, human_sample)
                if not (target_model_metric <= best_value and is_v_gene_score_less(target_v_gene_score, v_gene_score)):
                    current_seq[best_change.position] = prev_aa
                    logger.info(f"Current metrics are best ({round(current_value, 6)})")
                    break
                column_name = self.model_wrapper.annotation.segmented_positions[best_change.position]
                logger.info(f"Best change position {column_name}: {prev_aa} -> {best_change.aa}")
                iterations.append(IterationDetails(it, best_value, v_gene_score, best_change))
            else:
                logger.info(f"No effective changes found. Stop algorithm on model metric = {round(current_value, 6)}")
                break
        return seq_to_str(current_seq, False), iterations


def main(models_dir, input_file, dataset_file, annotated_data, human_sample, skip_positions,
         use_aa_similarity, output_file):
    chain_type, target_model_metric, target_v_gene_score = read_humanizer_options(dataset_file)
    model_wrapper = load_model(models_dir, chain_type)
    v_gene_scorer = build_v_gene_scorer(model_wrapper.annotation, dataset_file, annotated_data)
    humanizer = ReverseHumanizer(
        model_wrapper, v_gene_scorer, parse_list(skip_positions), use_aa_similarity
    )
    sequences = read_sequences(input_file)
    results = run_humanizer(sequences,
                            lambda seq: humanizer.query(seq, target_model_metric, target_v_gene_score, human_sample))
    write_sequences(output_file, results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='''Reverse humanizer''')
    abstract_humanizer_parser_options(parser)
    parser.add_argument('--input', type=str, required=False, help='Path to input fasta file')
    parser.add_argument('--output', type=str, required=False, help='Path to output fasta file')
    parser.add_argument('--human-sample', type=str, required=False,
                        help='Human sample used for creation chimeric sequence')

    args = parser.parse_args()

    main(models_dir=args.models,
         input_file=args.input,
         dataset_file=args.dataset,
         annotated_data=args.annotated_data,
         human_sample=args.human_sample,
         skip_positions=args.skip_positions,
         use_aa_similarity=args.use_aa_similarity,
         output_file=args.output)
