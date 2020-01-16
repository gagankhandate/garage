"""PyTorch Policies."""
from garage.torch.policies.base import Policy
from garage.torch.policies.context_conditioned_policy import (
    ContextConditionedPolicy)
from garage.torch.policies.deterministic_mlp_policy import (
    DeterministicMLPPolicy)
from garage.torch.policies.gaussian_mlp_policy import GaussianMLPPolicy
from garage.torch.policies.tanh_gaussian_mlp_policy import (
    DeterministicWrapper, TanhGaussianMLPPolicy)
from garage.torch.policies.tanh_gaussian_mlp_policy_2 import TanhGaussianMLPPolicy2

__all__ = [
    'ContextConditionedPolicy', 'DeterministicMLPPolicy', 'GaussianMLPPolicy',
    'Policy', 'TanhGaussianMLPPolicy', 'DeterministicWrapper',
    'TanhGaussianMLPPolicy2'
]
