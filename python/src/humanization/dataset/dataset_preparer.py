import json
import os
from itertools import accumulate
from typing import List, Tuple, Any, NoReturn, Callable, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix
from tqdm import tqdm

from humanization.common import config_loader
from humanization.common.annotations import Annotation, annotate_batch, ChainType
from humanization.common.utils import configure_logger

config = config_loader.Config()
logger = configure_logger(config, "Dataset reader")


def read_imgt_file(csv_path: str) -> Tuple[pd.DataFrame, Any]:
    df: pd.DataFrame = pd.read_csv(csv_path, names=['v_call', 'sequence_alignment_aa'], header=None)
    df.dropna(inplace=True)
    return df, True


def read_oas_file(csv_path: str, requested_columns: List[str]) -> Tuple[pd.DataFrame, Any]:
    metadata = json.loads(','.join(pd.read_csv(csv_path, nrows=0).columns))
    df: pd.DataFrame = pd.read_csv(csv_path, skiprows=1)  # Drop row with running info
    if requested_columns is not None:
        df = df[requested_columns]
    df.dropna(inplace=True)
    return df, metadata['Species'] == 'human'


def correct_v_call(df: pd.DataFrame, is_human: bool) -> NoReturn:
    if not is_human:
        df['v_call'] = 'NOT_HUMAN'
    else:
        df['v_call'].replace(r'^(....\d+).*$', r'\1', regex=True, inplace=True)


def make_annotated_df(df: pd.DataFrame, annotation: Annotation, is_human: bool = False) -> pd.DataFrame:
    aa_columns = annotation.segmented_positions
    annotated_indexes, annotated_list = annotate_batch(
        df['sequence_alignment_aa'].tolist(), annotation,
        is_human=is_human
    )
    X = pd.DataFrame(annotated_list, columns=aa_columns)  # Make column for every aa
    y = df['v_call'][annotated_indexes]
    y.reset_index(drop=True, inplace=True)
    dataset = pd.concat([X, y], axis=1)
    nan_errors = dataset['v_call'].isna().sum()
    if nan_errors > 0:
        raise RuntimeError(f"Found {nan_errors} NaNs in target chain types")
    return dataset


def filter_df(df: pd.DataFrame, annotation: Annotation) -> pd.DataFrame:
    if len(annotation.required_positions) > 0:
        masks = [df[pos] == aa for pos, aa in annotation.required_positions.items()]
        mask = next(accumulate(masks, func=lambda a, b: a & b))
        return df[mask]
    return df


def read_datasets(input_dir: str, read_function: Callable[[str], pd.DataFrame],
                  only_human: bool = False, v_type: Optional[ChainType] = None) -> List[pd.DataFrame]:
    logger.info("Dataset reading...")
    file_paths = []
    if os.path.isdir(input_dir):
        for input_file_name in os.listdir(input_dir):
            file_paths.append(os.path.join(input_dir, input_file_name))
    elif os.path.isfile(input_dir):
        file_paths.append(input_dir)
    else:
        raise RuntimeError(f"Unexpected dataset path: {input_dir}")
    original_data_size = 0
    dfs = []
    for input_file_path in tqdm(file_paths):
        df: pd.DataFrame = read_function(input_file_path)
        if v_type is not None:  # Only specific v type
            df = df[df['v_call'] == v_type.oas_type()]
        elif only_human:  # Only human samples
            df = df[df['v_call'] != 'NOT_HUMAN']
        df.reset_index(drop=True, inplace=True)
        dfs.append(df)
        original_data_size += df.shape[0]
    logger.info(f"Original dataset: {original_data_size} rows")
    return dfs


def read_dataset(*args, **kwargs) -> Tuple[pd.DataFrame, pd.Series]:
    dfs = read_datasets(*args, **kwargs)
    dataset = pd.concat(dfs, axis=0, ignore_index=True, copy=False)
    dataset.drop_duplicates(ignore_index=True, inplace=True)
    logger.info(f"Dataset: {dataset.shape[0]} rows (duplicates removed)")
    X = dataset.drop(['v_call'], axis=1)
    y = dataset['v_call']
    return X, y


def read_annotated_dataset(input_dir: str, **kwargs) -> Tuple[pd.DataFrame, pd.Series]:
    return read_dataset(input_dir, pd.read_csv, **kwargs)


def merge_all_columns(df: pd.DataFrame) -> List[str]:
    values: List[List[str]] = df.to_numpy().tolist()
    result = list(map("".join, values))
    return result


def make_binary_target(y, target_v_type):
    return np.where(y.apply(lambda x: x == target_v_type), 1, 0)


def format_confusion_matrix(y_test, y_pred):
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred).ravel()
    recall = round(tp / (tp + fn), 5)
    precision = round(tp / (tp + fp), 5)
    accuracy = round((tp + tn) / (tp + tn + fp + fn), 5)
    return f"TP={tp}, TN={tn}, FP={fp}, FN={fn}. Recall={recall}. Precision={precision}. Accuracy={accuracy}"
