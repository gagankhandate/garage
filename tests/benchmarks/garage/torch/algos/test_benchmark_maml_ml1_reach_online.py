"""This script creates a regression test over garage-MAML and ProMP-TRPO.

Unlike garage, baselines doesn't set max_path_length. It keeps steps the action
until it's done. So we introduced tests.wrappers.AutoStopEnv wrapper to set
done=True when it reaches max_path_length. We also need to change the
garage.tf.samplers.BatchSampler to smooth the reward curve.
"""
import argparse
import datetime
import os
import os.path as osp
import random
import sys
from functools import partial

import numpy as np
import dowel
from dowel import logger as dowel_logger
import pytest
import torch
import tensorflow as tf

from metaworld.benchmarks import ML1WithPinnedGoal

from meta_policy_search.baselines.linear_baseline import LinearFeatureBaseline as PM_LinearFeatureBaseline
from meta_policy_search.envs.normalized_env import normalize as PM_normalize
from meta_policy_search.meta_algos.trpo_maml import TRPOMAML
from meta_policy_search.meta_trainer import Trainer
from meta_policy_search.samplers.meta_sampler2 import MetaSampler2
from meta_policy_search.samplers.meta_sample_processor import MetaSampleProcessor
from meta_policy_search.policies.meta_gaussian_mlp_policy import MetaGaussianMLPPolicy
from meta_policy_search.utils import logger as PM_logger

from garage.envs import normalize
from garage.envs.base import GarageEnv
from garage.envs.TaskIdWrapper import TaskIdWrapper
from garage.experiment import deterministic, LocalRunner, SnapshotConfig, \
    MetaEvaluator
from garage.experiment.task_sampler import AllSetTaskSampler
from garage.np.baselines import LinearFeatureBaseline
from garage.torch.algos import MAMLTRPO
from garage.torch.policies import GaussianMLPPolicy

from tests import benchmark_helper
import tests.helpers as Rh

test_garage = False
test_promp = True

# Same as promp:full_code/config/trpo_maml_config.json
hyper_parameters = {
    'hidden_sizes': [100, 100],
    'max_kl': 0.01,
    'inner_lr': 0.05,
    'gae_lambda': 1.0,
    'discount': 0.99,
    'max_path_length': 100,
    'fast_batch_size': 10,  # num of rollouts per task
    'meta_batch_size': 20,  # num of tasks
    'n_epochs': 1250,
    # 'n_epochs': 1,
    'n_trials': 5,
    'num_grad_update': 1,
    'n_parallel': 1,
    'inner_loss': 'log_likelihood'
}


class TestBenchmarkMAML:  # pylint: disable=too-few-public-methods
    """Compare benchmarks between garage and baselines."""

    @pytest.mark.huge
    def test_benchmark_maml(self, _):  # pylint: disable=no-self-use
        """Compare benchmarks between garage and baselines."""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f')
        benchmark_dir = './data/local/benchmarks/maml-ml1-push/%s/' % timestamp
        result_json = {}
        env_id = 'ML1-Reach'
        meta_train_env = TaskIdWrapper(
            ML1WithPinnedGoal.get_train_tasks('reach-v1'))
        meta_test_env = TaskIdWrapper(
            ML1WithPinnedGoal.get_test_tasks('reach-v1'))

        seeds = random.sample(range(100), hyper_parameters['n_trials'])
        task_dir = osp.join(benchmark_dir, env_id)
        plt_file = osp.join(benchmark_dir, '{}_benchmark.png'.format(env_id))
        promp_csvs = []
        garage_csvs = []

        for trial in range(hyper_parameters['n_trials']):
            seed = seeds[trial]
            trial_dir = task_dir + '/trial_%d_seed_%d' % (trial + 1, seed)
            garage_dir = trial_dir + '/garage'
            promp_dir = trial_dir + '/promp'

            if test_garage:
                # Run garage algorithm
                train_env = GarageEnv(
                    normalize(meta_train_env, expected_action_scale=10.))
                test_env_cls = partial(
                    GarageEnv,
                    normalize(meta_test_env, expected_action_scale=10.))
                garage_csv = run_garage(train_env, test_env_cls, seed,
                                        garage_dir)
                garage_csvs.append(garage_csv)
                train_env.close()

            if test_promp:
                with tf.Graph().as_default():
                    # Run promp algorithm
                    promp_train_env = PM_normalize(meta_train_env)
                    promp_test_env = PM_normalize(meta_test_env)
                    promp_csv = run_promp(promp_train_env, promp_test_env, seed, promp_dir)
                promp_csvs.append(promp_csv)
                promp_train_env.close()
                promp_test_env.close()

        if test_garage and test_promp:
            benchmark_helper.plot_average_over_trials(
                [promp_csvs, promp_csvs, garage_csvs, garage_csvs],
                ys=[
                    'Step_0-AverageReturn', 'Step_1-AverageReturn',
                    'Update_0/AverageReturn', 'Update_1/AverageReturn'
                ],
                xs=[
                    'n_timesteps', 'n_timesteps', 'TotalEnvSteps',
                    'TotalEnvSteps'
                ],
                plt_file=plt_file,
                env_id=env_id,
                x_label='TotalEnvSteps',
                y_label='AverageReturn',
                names=['ProMP_0', 'ProMP_1', 'garage_0', 'garage_1'],
            )

            batch_size = hyper_parameters[
                'meta_batch_size'] * hyper_parameters['max_path_length']
            result_json[env_id] = benchmark_helper.create_json(
                [promp_csvs, promp_csvs, garage_csvs, garage_csvs],
                seeds=seeds,
                trials=hyper_parameters['n_trials'],
                xs=[
                    'n_timesteps', 'n_timesteps', 'TotalEnvSteps',
                    'TotalEnvSteps'
                ],
                ys=[
                    'Step_0-AverageReturn', 'Step_1-AverageReturn',
                    'Update_0/AverageReturn', 'Update_1/AverageReturn'
                ],
                factors=[batch_size] * 4,
                names=['ProMP_0', 'ProMP_1', 'garage_0', 'garage_1'])

            Rh.write_file(result_json, 'MAML')


def run_garage(train_env, test_env_cls, seed, log_dir):
    """Create garage PyTorch MAML model and training.

    Args:
        train_env (GarageEnv): Training environment of the task.
        test_env (GarageEnv): Testing environment of the task.
        seed (int): Random positive integer for the trial.
        log_dir (str): Log dir path.

    Returns:
        str: Path to output csv file

    """
    deterministic.set_seed(seed)

    # Set up logger since we are not using run_experiment
    tabular_log_file = osp.join(log_dir, 'progress.csv')
    dowel_logger.add_output(dowel.StdOutput())
    dowel_logger.add_output(dowel.CsvOutput(tabular_log_file))
    dowel_logger.add_output(dowel.TensorBoardOutput(log_dir))

    snapshot_config = SnapshotConfig(snapshot_dir=log_dir,
                                     snapshot_mode='all',
                                     snapshot_gap=1)

    runner = LocalRunner(snapshot_config=snapshot_config)

    policy = GaussianMLPPolicy(
        env_spec=train_env.spec,
        hidden_sizes=hyper_parameters['hidden_sizes'],
        hidden_nonlinearity=torch.tanh,
        output_nonlinearity=None,
    )

    baseline = LinearFeatureBaseline(env_spec=train_env.spec)

    algo = MAMLTRPO(env=train_env,
                    policy=policy,
                    baseline=baseline,
                    max_path_length=hyper_parameters['max_path_length'],
                    discount=hyper_parameters['discount'],
                    gae_lambda=hyper_parameters['gae_lambda'],
                    meta_batch_size=hyper_parameters['meta_batch_size'],
                    inner_lr=hyper_parameters['inner_lr'],
                    max_kl_step=hyper_parameters['max_kl'],
                    num_grad_updates=hyper_parameters['num_grad_update'])

    runner.setup(algo, train_env, sampler_args=dict(n_envs=5))

    meta_sampler = AllSetTaskSampler(test_env_cls)

    meta_evaluator = MetaEvaluator(
        runner,
        test_task_sampler=meta_sampler,
        max_path_length=hyper_parameters['max_path_length'],
        n_test_tasks=meta_sampler.n_tasks,
        n_exploration_traj=hyper_parameters['fast_batch_size'])

    algo._meta_evaluator = meta_evaluator

    runner.train(n_epochs=hyper_parameters['n_epochs'],
                 batch_size=(hyper_parameters['fast_batch_size'] *
                             hyper_parameters['max_path_length']))

    dowel_logger.remove_all()

    return tabular_log_file


def run_promp(train_env, test_env, seed, log_dir):
    """Create ProMP model and training.

    Args:
        train_env : Environment of the task.
        seed (int): Random positive integer for the trial.
        log_dir (str): Log dir path.

    Returns:
        str: Path to output csv file

    """
    deterministic.set_seed(seed)

    # configure logger
    PM_logger.configure(dir=log_dir,
                        format_strs=['stdout', 'log', 'csv', 'tensorboard'],
                        snapshot_mode='all')

    baseline = PM_LinearFeatureBaseline()

    policy = MetaGaussianMLPPolicy(
        name='meta-policy',
        obs_dim=np.prod(train_env.observation_space.shape),
        action_dim=np.prod(train_env.action_space.shape),
        meta_batch_size=hyper_parameters['meta_batch_size'],
        hidden_sizes=hyper_parameters['hidden_sizes'],
    )

    sampler = MetaSampler2(
        train_env=train_env,
        test_env=test_env,
        policy=policy,
        rollouts_per_meta_task=hyper_parameters['fast_batch_size'],
        meta_batch_size=hyper_parameters['meta_batch_size'],
        max_path_length=hyper_parameters['max_path_length'],
        parallel=hyper_parameters['n_parallel'],
    )

    sample_processor = MetaSampleProcessor(
        baseline=baseline,
        discount=hyper_parameters['discount'],
        gae_lambda=hyper_parameters['gae_lambda'],
        normalize_adv=True,
    )

    algo = TRPOMAML(
        policy=policy,
        step_size=hyper_parameters['max_kl'],
        inner_type=hyper_parameters['inner_loss'],
        inner_lr=hyper_parameters['inner_lr'],
        meta_batch_size=hyper_parameters['meta_batch_size'],
        num_inner_grad_steps=hyper_parameters['num_grad_update'],
        exploration=False,
    )

    trainer = Trainer(
        algo=algo,
        policy=policy,
        env=train_env,
        sampler=sampler,
        sample_processor=sample_processor,
        n_itr=hyper_parameters['n_epochs'],
        num_inner_grad_steps=hyper_parameters['num_grad_update'],
    )

    trainer.train()
    tabular_log_file = osp.join(log_dir, 'progress.csv')
    sampler.close()

    return tabular_log_file


def worker(variant):
    variant_str = '-'.join(['{}_{}'.format(k, v) for k, v in variant.items()])
    if 'hidden_sizes' in variant:
        hidden_sizes = variant['hidden_sizes']
        variant['hidden_sizes'] = [hidden_sizes, hidden_sizes]
    hyper_parameters.update(variant)

    test_cls = TestBenchmarkMAML()
    test_cls.test_benchmark_maml(variant_str)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('who', nargs='?')
    parser.add_argument('--parallel', action='store_true', default=False)
    parser.add_argument('--combined', action='store_true', default=False)

    known_args, unknown_args = parser.parse_known_args()

    for arg in unknown_args:
        if arg.startswith('--'):
            parser.add_argument(arg, type=float)

    args = parser.parse_args()
    print(args)

    if args.who:
        test_garage = args.who in ('both', 'garage')
        test_promp = args.who in ('both', 'promp')

    parallel = args.parallel
    combined = args.combined
    args = vars(args)
    del args['who']
    del args['parallel']
    del args['combined']

    n_variants = len(args)
    if combined:
        variants = [{
            k: int(v) if v.is_integer() else v
            for k, v in args.items()
        }]
    else:
        if n_variants > 0:
            variants = [{
                k: int(v) if v.is_integer() else v
            } for k, v in args.items()]
        else:
            variants = [
                dict(n_trials=1) for _ in range(hyper_parameters['n_trials'])
            ]

    for key in args:
        assert key in hyper_parameters, '{} is not a hyperparameter'.format(
            key)

    children = []
    for i, variant in enumerate(variants):
        random.seed(i)
        pid = os.fork()
        if pid == 0:
            worker(variant)
            exit()
        else:
            if parallel:
                children.append(pid)
            else:
                os.waitpid(pid, 0)

    if parallel:
        for child in children:
            os.waitpid(child, 0)