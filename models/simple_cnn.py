from typing import List

import torch.nn as nn
from torch import Tensor

from models.init_weights import init_weights


class Encoder(nn.Module):
    def __init__(
            self,
            z_dim: int = 128,
            in_dim: int = 3,
            dim: int = 64,
            dim_mults: List[int] = (1, 2, 4, 8),
            with_bn: bool = True,
            init_type: str = 'normal',
    ):
        """ A simple CNN encoder.

        Args:
            z_dim: Dimension of the latent variable.
            in_dim: Input dimension.
            dim: Base dimension.
            dim_mults: Multiplies of dimensions.
            with_bn: Use batch normalization.
            init_type: Type of weight initialization.

        """
        super().__init__()

        self.first_conv = nn.Conv2d(in_dim, dim * dim_mults[0], (4, 4), stride=2, padding=1)
        self.layers = nn.ModuleList([])
        for i in range(len(dim_mults) - 1):
            self.layers.append(nn.Sequential(
                nn.BatchNorm2d(dim * dim_mults[i]) if i > 0 and with_bn else nn.Identity(),
                nn.LeakyReLU(0.2),
                nn.Conv2d(dim * dim_mults[i], dim * dim_mults[i+1], (4, 4), stride=2, padding=1)
            ))
        self.last_conv = nn.Sequential(
            nn.BatchNorm2d(dim * dim_mults[-1]) if with_bn else nn.Identity(),
            nn.LeakyReLU(0.2),
            nn.Conv2d(dim * dim_mults[-1], dim * dim_mults[-1], (4, 4), stride=1, padding=0),
        )

        cur_dim = dim * dim_mults[-1]
        self.fc_mean = nn.Sequential(
            nn.Flatten(),
            nn.Linear(cur_dim, cur_dim // 2),
            nn.BatchNorm1d(cur_dim // 2),
            nn.LeakyReLU(),
            nn.Linear(cur_dim // 2, z_dim),
        )
        self.fc_logvar = nn.Sequential(
            nn.Flatten(),
            nn.Linear(cur_dim, cur_dim // 2),
            nn.BatchNorm1d(cur_dim // 2),
            nn.LeakyReLU(),
            nn.Linear(cur_dim // 2, z_dim),
        )

        self.apply(init_weights(init_type))

    def forward(self, X: Tensor):
        X = self.first_conv(X)
        for layer in self.layers:
            X = layer(X)
        X = self.last_conv(X)
        mean = self.fc_mean(X)
        logvar = self.fc_logvar(X)
        return mean, logvar


class Decoder(nn.Module):
    def __init__(
            self,
            z_dim: int = 128,
            dim: int = 64,
            dim_mults: List[int] = (8, 4, 2, 1),
            out_dim: int = 3,
            with_bn: bool = True,
            with_tanh: bool = True,
            init_type: str = 'normal',
    ):
        """ A simple CNN decoder.

        Args:
            z_dim: Dimension of the latent variable.
            dim: Base dimension.
            dim_mults: Multiplies of dimensions.
            out_dim: Output dimension.
            with_bn: Use batch normalization.
            with_tanh: Use nn.Tanh() at last.
            init_type: Type of weight initialization.

        """
        super().__init__()
        self.first_conv = nn.ConvTranspose2d(z_dim, dim * dim_mults[0], (4, 4), stride=1, padding=0)
        self.layers = nn.ModuleList([])
        for i in range(len(dim_mults) - 1):
            self.layers.append(nn.Sequential(
                nn.BatchNorm2d(dim * dim_mults[i]) if with_bn else nn.Identity(),
                nn.LeakyReLU(0.2),
                nn.ConvTranspose2d(dim * dim_mults[i], dim * dim_mults[i+1], (4, 4), stride=2, padding=1),
            ))
        self.last_conv = nn.Sequential(
            nn.BatchNorm2d(dim * dim_mults[-1]) if with_bn else nn.Identity(),
            nn.LeakyReLU(0.2),
            nn.ConvTranspose2d(dim * dim_mults[-1], out_dim, (4, 4), stride=2, padding=1),
        )
        self.act = nn.Tanh() if with_tanh else nn.Identity()

        self.apply(init_weights(init_type))

    def forward(self, X: Tensor):
        if X.ndim == 2:
            X = X.view(-1, X.shape[1], 1, 1)
        X = self.first_conv(X)
        for layer in self.layers:
            X = layer(X)
        X = self.last_conv(X)
        X = self.act(X)
        return X


def _test():
    import torch
    enc = Encoder(100)
    dec = Decoder(100)
    x = torch.randn(10, 3, 64, 64)
    mean, logvar = enc(x)
    z = mean + torch.randn_like(mean) * torch.exp(0.5 * logvar)
    decx = dec(z)
    print(mean.shape, logvar.shape)
    print(decx.shape)


if __name__ == '__main__':
    _test()
