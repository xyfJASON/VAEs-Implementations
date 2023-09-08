import os
import tqdm
import argparse
from omegaconf import OmegaConf

import torch
import accelerate
import torch.nn as nn
from torchvision.utils import save_image

from utils.logger import get_logger
from utils.misc import instantiate_from_config, amortize


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config', type=str, required=True,
        help='Path to training configuration file',
    )
    parser.add_argument(
        '--seed', type=int, default=8888,
        help='Set random seed',
    )
    parser.add_argument(
        '--mode', type=str, default='sample',
        choices=['sample', 'interpolate', 'traverse'],
        help='Choose a sample mode',
    )
    parser.add_argument(
        '--weights', type=str, required=True,
        help='Path to pretrained model weights',
    )
    parser.add_argument(
        '--n_samples', type=int, required=True,
        help='Number of samples',
    )
    parser.add_argument(
        '--save_dir', type=str, required=True,
        help='Path to directory saving samples',
    )
    parser.add_argument(
        '--batch_size', type=int, default=500,
        help='Batch size during sampling',
    )
    parser.add_argument(
        '--n_interpolate', type=int, default=15,
        help='Number of intermidiate images when mode is interpolate',
    )
    parser.add_argument(
        '--n_traverse', type=int, default=15,
        help='Number of traversed images when mode is traverse',
    )
    parser.add_argument(
        '--traverse_range', type=float, default=3,
        help='Traversal range when mode is traverse',
    )
    parser.add_argument(
        '--traverse_dim', type=int, default=0,
        help='Traversal dimension when mode is traverse',
    )
    return parser


def main():
    # PARSE ARGS AND CONFIGS
    args, unknown_args = get_parser().parse_known_args()
    unknown_args = [(a[2:] if a.startswith('--') else a) for a in unknown_args]
    unknown_args = [f'{k}={v}' for k, v in zip(unknown_args[::2], unknown_args[1::2])]
    conf = OmegaConf.load(args.config)
    conf = OmegaConf.merge(conf, OmegaConf.from_dotlist(unknown_args))

    # INITIALIZE ACCELERATOR
    accelerator = accelerate.Accelerator()
    device = accelerator.device
    print(f'Process {accelerator.process_index} using device: {device}')
    accelerator.wait_for_everyone()

    # INITIALIZE LOGGER
    logger = get_logger(
        use_tqdm_handler=True,
        is_main_process=accelerator.is_main_process,
    )

    # SET SEED
    accelerate.utils.set_seed(args.seed, device_specific=True)
    logger.info('=' * 19 + ' System Info ' + '=' * 18)
    logger.info(f'Number of processes: {accelerator.num_processes}')
    logger.info(f'Distributed type: {accelerator.distributed_type}')
    logger.info(f'Mixed precision: {accelerator.mixed_precision}')

    accelerator.wait_for_everyone()

    # BUILD MODELS
    logger.info('=' * 19 + ' Model Info ' + '=' * 19)
    encoder: nn.Module = instantiate_from_config(conf.encoder).eval().to(device)
    decoder: nn.Module = instantiate_from_config(conf.decoder).eval().to(device)

    # LOAD WEIGHTS
    ckpt = torch.load(args.weights, map_location='cpu')
    encoder.load_state_dict(ckpt['encoder'])
    logger.info(f'Successfully load encoder from {args.weights}')
    decoder.load_state_dict(ckpt['decoder'])
    logger.info(f'Successfully load decoder from {args.weights}')
    logger.info('=' * 50)

    accelerator.wait_for_everyone()

    @accelerator.on_main_process
    @torch.no_grad()
    def sample():
        idx = 0
        os.makedirs(args.save_dir, exist_ok=True)
        folds = amortize(args.n_samples, args.batch_size)
        for bs in tqdm.tqdm(folds):
            z = torch.randn((bs, conf.encoder.params.z_dim), device=device)
            samples = decoder(z).cpu()
            for x in samples:
                save_image(
                    x, os.path.join(args.save_dir, f'{idx}.png'),
                    nrow=1, normalize=True, range=(-1, 1),
                )
                idx += 1

    @accelerator.on_main_process
    @torch.no_grad()
    def interpolate():
        idx = 0
        os.makedirs(args.save_dir, exist_ok=True)
        folds = amortize(args.n_samples, args.batch_size)
        for bs in tqdm.tqdm(folds):
            z1 = torch.randn((bs, conf.encoder.params.z_dim), device=device)
            z2 = torch.randn((bs, conf.encoder.params.z_dim), device=device)
            samples = torch.stack([
                decoder(z1 * t + z2 * (1 - t))
                for t in torch.linspace(0, 1, args.n_interpolate)
            ], dim=1).cpu()
            for x in samples:
                save_image(
                    x, os.path.join(args.save_dir, f'{idx}.png'),
                    nrow=len(x), normalize=True, range=(-1, 1),
                )
                idx += 1

    @accelerator.on_main_process
    @torch.no_grad()
    def traverse():
        idx = 0
        os.makedirs(args.save_dir, exist_ok=True)
        folds = amortize(args.n_samples, args.batch_size)
        for bs in tqdm.tqdm(folds):
            z = torch.randn((bs, 1, conf.encoder.params.z_dim), device=device).repeat(1, args.n_traverse, 1)
            z[:, :, args.traverse_dim] = torch.linspace(
                -args.traverse_range, args.traverse_range, args.n_traverse, device=device,
            ).unsqueeze(0)
            z = z.reshape(-1, conf.encoder.params.z_dim)  # [bs * n_traverse, z_dim]
            samples = decoder(z).cpu()
            samples = samples.reshape(bs, args.n_traverse, *samples.shape[1:])
            for x in samples:
                save_image(
                    x, os.path.join(args.save_dir, f'{idx}.png'),
                    nrow=len(x), normalize=True, range=(-1, 1),
                )
                idx += 1

    # START SAMPLING
    logger.info('Start sampling...')
    if args.mode == 'sample':
        sample()
    elif args.mode == 'interpolate':
        interpolate()
    elif args.mode == 'traverse':
        traverse()
    else:
        raise ValueError(f'Unknown sample mode: {args.mode}')
    logger.info(f'Sampled images are saved to {args.save_dir}')
    logger.info('End of sampling')


if __name__ == '__main__':
    main()
