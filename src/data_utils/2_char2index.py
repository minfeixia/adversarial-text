import os
import logging
import argparse
import itertools

import numpy as np
from tqdm import tqdm


logging.basicConfig(format='%(asctime)-15s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
info = logger.info


def parse_args():
    parser = argparse.ArgumentParser(
        description='Convert each character to its UTF-8 encoding with ord.')
    parser.add_argument('--train', type=str, help='train.txt')
    parser.add_argument('--test', type=str, help='test.txt')
    parser.add_argument('--validation', type=str, help='validation.txt')
    parser.add_argument('--output', type=str, required=True,
                        help='output file name')
    return parser.parse_args()


def char2index(fname):
    info('reading {}'.format(fname))
    with open(fname, 'r') as r:
        sents = r.read().splitlines()
    sents = [sent.split(maxsplit=1) for sent in sents]
    info('converting to indices')
    vec = [[int(sent[0])] +
           list(itertools.chain(*[[ord(c) for c in w] for w in sent[1]]))
           for sent in tqdm(sents)]
    vec = np.array(vec)
    info('data shape {}'.format(vec.shape))
    X_data, y_data = vec[:, 1:], vec[:, 0]
    return X_data, y_data


def main(args):
    data = {}
    if args.train is not None:
        info('generate training data')
        X_train, y_train = char2index(os.path.expanduser(args.train))
        data['X_train'], data['y_train'] = X_train, y_train
    if args.test is not None:
        info('generate test data')
        X_test, y_test = char2index(os.path.expanduser(args.test))
        data['X_test'], data['y_test'] = X_test, y_test
    if args.validation is not None:
        info('generate validation data')
        X_valid, y_valid = char2index(os.path.expanduser(args.validation))
        data['X_valid'], data['y_valid'] = X_valid, y_valid
    info('saving {}'.format(args.output))
    np.savez(os.path.expanduser(args.output), **data)


if __name__ == '__main__':
    info('THE BEGIN')
    main(parse_args())
    info('THE END')
