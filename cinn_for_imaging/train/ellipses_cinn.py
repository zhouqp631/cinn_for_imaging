"""
Train CINNReconstructor on 'ellipses'.
"""

import os

from pytorch_lightning.callbacks import ModelCheckpoint, LearningRateMonitor
from pytorch_lightning import loggers as pl_loggers

from cinn_for_imaging.reconstructors.cinn_reconstructor import CINNReconstructor
from cinn_for_imaging.datasets.ellipses.data_util import EllipsesDataModule


#%% path for logging and saving the model
experiment_name = 'cinn'
path_parts = ['..', 'experiments', 'ellipses', experiment_name]
log_dir = os.path.join(*path_parts)

#%% setup the LoDoPaB dataset
dataset = EllipsesDataModule(impl='astra_cuda', num_data_loader_workers=0)
dataset.prepare_data()
dataset.setup()
ray_trafo = dataset.ray_trafo

#%% configure the Pytorch Lightning trainer. 
# Visit https://pytorch-lightning.readthedocs.io/en/stable/trainer.html
# for all available trainer options.

checkpoint_callback = ModelCheckpoint(
    save_top_k=1,
    verbose=True,
    monitor='val_loss',
    mode='min',
)

lr_monitor = LearningRateMonitor(logging_interval=None) 


tb_logger = pl_loggers.TensorBoardLogger(log_dir)

trainer_args = {'distributed_backend': 'ddp',
                'gpus': -1,
                'default_root_dir': log_dir,
                'callbacks': [lr_monitor, checkpoint_callback],
                'benchmark': False,
                'fast_dev_run': False,
                'gradient_clip_val': 1.0,
                'logger': tb_logger}

#%% create the reconstructor
reconstructor = CINNReconstructor(
    ray_trafo=ray_trafo, 
    in_ch=1, 
    img_size=None,
    conditioning="fbp",
    max_samples_per_run=100,
    trainer_args=trainer_args,
    log_dir=log_dir)

#%% change some of the hyperparameters of the reconstructor
reconstructor.batch_size = 12
reconstructor.epochs = 500
reconstructor.downsampling = 'reshape'
reconstructor.sample_distribution = "normal"
reconstructor.torch_manual_seed = None

#%% train the reconstructor. Checkpointing and logging is enabled by default.
reconstructor.train(dataset)

#%% train the reconstructor. Checkpointing and logging is enabled by default.
# version = 'version_1' 
# chkp_name = 'epoch=4'


# experiment_name = 'ellipses'
# path_parts = ['..', 'experiments', experiment_name, 'default',
#             version, 'checkpoints', chkp_name + '.ckpt']

# chkp_path = os.path.join(*path_parts)
# reconstructor.train(dataset,checkpoint_path=chkp_path)
