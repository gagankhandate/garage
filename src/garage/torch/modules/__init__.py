"""Pytorch modules."""

from garage.torch.modules.gaussian_mlp_module import \
    GaussianMLPIndependentStdModule, GaussianMLPModule, \
    GaussianMLPTwoHeadedModule
from garage.torch.modules.mlp_module import MLPModule, \
    FlattenMLP, MLPEncoder
from garage.torch.modules.multi_headed_mlp_module import MultiHeadedMLPModule
from garage.torch.modules.tanh_gaussian_mlp_module_2 import TanhGaussianMLPTwoHeadedModule2
__all__ = [
    'MLPModule', 'MultiHeadedMLPModule', 'GaussianMLPModule',
    'GaussianMLPIndependentStdModule', 'GaussianMLPTwoHeadedModule',
    'FlattenMLP', 'MLPEncoder', 'TanhGaussianMLPTwoHeadedModule2'
]
