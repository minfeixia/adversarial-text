import os
import logging
import argparse

import numpy as np
import tensorflow as tf
from tqdm import tqdm

from charlstm import CharLSTM

from utils.core import train, evaluate
from utils.misc import load_data, build_metric

from attacks import hf_replace


os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

logging.basicConfig(format='%(asctime)-15s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
info = logger.info


def parse_args():
    parser = argparse.ArgumentParser(description='Attach CharLSTM.')

    parser.add_argument('--batch_size', metavar='N', type=int, default=64)
    parser.add_argument('--data', metavar='FILE', type=str, required=True)
    parser.add_argument('--drop_rate', metavar='N', type=float, default=0.2)
    parser.add_argument('--embedding_dim', metavar='N', type=int)
    parser.add_argument('--feature_maps', metavar='N1 [N2 N3 ...]', nargs='+',
                        default=[25, 50, 75, 100, 125, 150])
    parser.add_argument('--kernel_sizes', metavar='N1 [N2 N3 ...]', nargs='+',
                        default=[1, 2, 3, 4, 5, 6])
    parser.add_argument('--highways', metavar='N', type=int, default=1)
    parser.add_argument('--lstm_units', metavar='N', type=int, default=256)
    parser.add_argument('--lstms', metavar='N', type=int, default=2)
    parser.add_argument('--n_classes', metavar='N', type=int, required=True)
    parser.add_argument('--name', metavar='MODEL', type=str)
    parser.add_argument('--seqlen', metavar='N', type=int, default=300)
    parser.add_argument('--vocab_size', metavar='N', type=int, default=128)
    parser.add_argument('--wordlen', metavar='N', type=int, required=True)

    parser.add_argument('--maxchars', metavar='N', type=int, default=10,
                        help='maximum number of chars to perturb')
    parser.add_argument('--beam_width', metavar='N', type=int, default=1)
    parser.add_argument('--outfile', metavar='FILE', type=str, required=True)
    parser.add_argument('--samples', metavar='N', type=int, default=-1)

    bip = parser.add_mutually_exclusive_group()
    bip.add_argument('--bipolar', dest='bipolar', action='store_true',
                     help='-1/1 for output.')
    bip.add_argument('--unipolar', dest='bipolar', action='store_false',
                     help='0/1 for output.')
    parser.set_defaults(bipolar=False)

    return parser.parse_args()


def config(args, embedding):
    class _Dummy():
        pass
    cfg = _Dummy()

    cfg.batch_size = args.batch_size
    cfg.bipolar = args.bipolar
    cfg.data = args.data
    cfg.drop_rate = args.drop_rate
    cfg.embedding_dim = args.embedding_dim
    cfg.feature_maps = args.feature_maps
    cfg.highways = args.highways
    cfg.kernel_sizes = args.kernel_sizes
    cfg.lstm_units = args.lstm_units
    cfg.lstms = args.lstms
    cfg.n_classes = args.n_classes
    cfg.name = args.name
    cfg.seqlen = args.seqlen
    cfg.vocab_size = args.vocab_size
    cfg.wordlen = args.wordlen

    cfg.samples = args.samples
    cfg.beam_width = args.beam_width
    cfg.maxchars = args.maxchars
    cfg.outfile = args.outfile

    cfg.charlen = (cfg.seqlen * (cfg.wordlen
                                 + 2         # start/end of word symbol
                                 + 1)        # whitespace between tokens
                   + 1)                      # end of sentence symbol

    if args.n_classes > 2:
        cfg.output = tf.nn.softmax
    elif 2 == args.n_classes:
        cfg.output = tf.tanh if args.bipolar else tf.sigmoid

    cfg.embedding = tf.placeholder(tf.float32, embedding.shape)

    return cfg


def build_graph(cfg):
    class _Dummy:
        pass

    env = _Dummy()

    env.x = tf.placeholder(tf.int32, [cfg.batch_size, cfg.charlen], 'x')
    env.y = tf.placeholder(tf.int32, [cfg.batch_size, 1], 'y')
    env.training = tf.placeholder_with_default(False, (), 'mode')

    m = CharLSTM(cfg)
    env.model = m
    env.ybar = m.predict(env.x, env.training)
    env.saver = tf.train.Saver()
    env = build_metric(env, cfg)

    with tf.variable_scope('hotflip'):
        env.xadv = hf_replace(m, env.x, seqlen=cfg.charlen,
                              embedding_dim=cfg.embedding_dim,
                              beam_width=cfg.beam_width, chars=cfg.maxchars)
    return env


def make_adversarial(env, X_data):
    batch_size = env.cfg.batch_size
    n_sample = X_data.shape[0]
    n_batch = int((n_sample + batch_size - 1) / batch_size)
    X_adv = np.empty([env.cfg.beam_width] + list(X_data.shape))
    for batch in tqdm(range(n_batch), total=n_batch):
        end = min((batch + 1) * batch_size, n_sample)
        start = end - batch_size
        feed_dict = {env.x: X_data[start:end]}
        xadv = env.sess.run(env.xadv, feed_dict=feed_dict)
        X_adv[:, start:end] = xadv
    return X_adv


def main(args):
    info('loading embedding vec')
    embedding = np.eye(args.vocab_size).astype(np.float32)

    info('constructing config')
    cfg = config(args, embedding)

    info('constructing graph')
    env = build_graph(cfg)
    env.cfg = cfg

    info('initializing session')
    sess = tf.Session()
    sess.run(tf.global_variables_initializer(),
             feed_dict={cfg.embedding: embedding})
    sess.run(tf.local_variables_initializer())
    env.sess = sess

    info('loading data')
    (X_train, y_train), (X_test, y_test), (X_valid, y_valid) = load_data(
        os.path.expanduser(cfg.data), cfg.bipolar)

    info('loading model')
    train(env, load=True, name=cfg.name)
    info('evaluating against clean test samples')
    evaluate(env, X_test, y_test, batch_size=cfg.batch_size)

    if cfg.samples > 0:
        ind = np.random.permutation(X_test.shape[0])[:cfg.samples]
        X_data, y_data = X_test[ind], y_test[ind]
    else:
        X_data, y_data = X_test, y_test

    info('making adversarial texts')
    X_adv = make_adversarial(env, X_data)
    X_adv = np.reshape(X_adv, [-1, cfg.charlen])
    y_data = np.tile(y_data, [cfg.beam_width, 1])
    info('evaluating against adversarial texts')
    evaluate(env, X_adv, y_data, batch_size=cfg.batch_size)
    env.sess.close()

    fname = os.path.join('out', cfg.outfile)
    y_data = y_data.flatten()
    if cfg.bipolar:
        y_data = (y_data + 1) // 2
    for i in range(cfg.n_classes):
        fn = '{0}-{1}'.format(fname, i)
        info('saving {}'.format(fn))
        np.save(fn, X_adv[y_data == i])


if __name__ == '__main__':
    info('THE BEGIN')
    main(parse_args())
    info('THE END')