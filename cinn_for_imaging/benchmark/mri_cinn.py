"""
Benchmark CINNReconstructor on the 'fastmri' validation set.
"""
print("Start benchmark")

import os

from dival import reconstructors
from pathlib import Path

import torch
import yaml
from tqdm import tqdm
import numpy as np
import pytorch_lightning as pl
#from dival.measure import PSNR, SSIM
from dival.util.plot import plot_images
from matplotlib.pyplot import plot, savefig

from cinn_for_imaging.reconstructors.mri_reconstructor import CINNReconstructor
from cinn_for_imaging.util.torch_losses import CINNNLLLoss
from cinn_for_imaging.datasets.fast_mri.data_util import FastMRIDataModule

from skimage.metrics import structural_similarity

def PSNR(reconstruction, ground_truth):
    gt = np.asarray(ground_truth)
    mse = np.mean((np.asarray(reconstruction) - gt)**2)
    if mse == 0.:
        return float('inf')
    data_range = np.max(gt)
    return 20*np.log10(data_range) - 10*np.log10(mse)

def SSIM(reconstruction, ground_truth):
    gt = np.asarray(ground_truth)
    data_range = (np.max(gt))
    return structural_similarity(reconstruction, gt, data_range=data_range)



#%% configure the dataset
dataset = FastMRIDataModule(batch_size=1, num_data_loader_workers=8)
dataset.prepare_data()
dataset.setup()
num_val_images = 500 #len(dataset.val_dataloader())
#%% initialize the reconstructor
reconstructor = CINNReconstructor(
    in_ch=1, 
    img_size=(320, 320),
    max_samples_per_run=100)
#%% load the desired model checkpoint
version = 'version_7' 
chkp_name = 'epoch=252-step=137378'
path_parts = ['..', 'experiments', 'fast_mri', 'default', version, 'checkpoints', chkp_name + '.ckpt']
chkp_path = os.path.join(*path_parts)
reconstructor.load_learned_params(path=chkp_path, checkpoint=True)
#reconstructor.init_model()
#reconstructor.model.init_params()


criterion = CINNNLLLoss(
    distribution='normal')

#%% move model to the GPU
reconstructor.model.to('cuda')

print(reconstructor.model.img_size)
print(reconstructor.img_size)

#%% settings for the evaluation - deactivate seed if needed
eval_seed = 42
reconstructor.samples_per_reco = 100
reconstructor.max_samples_per_run = 100
pl.seed_everything(eval_seed)
reconstructor.model.eval()

# save report of the evaluation result
save_report = True

# check for the invertibility of the samples
check_inv = True
check_inv_gt = True

# calculate the NLL loss
check_loss = True
check_loss_gt = True

# plot the first three reconstructions & gt
plot_examples = True
plot_examples_gt = False

#%% evaluate the model 
if save_report:
    report_path_parts = path_parts[:-2]
    report_path_parts.append('benchmark')
    report_name = version + '_' + chkp_name + '_seed=' + str(eval_seed) + \
                    '_images=' + str(num_val_images) + \
                    '_samples=' + str(reconstructor.samples_per_reco)
    report_path_parts.append(report_name)
    report_path = os.path.join(*report_path_parts)
    Path(report_path).mkdir(parents=True, exist_ok=True)

recos = []
recos_std = []
losses = []
psnrs = []
ssims = []
inv_psnr = []
with torch.no_grad():
    for i, batch in tqdm(zip(range(num_val_images),dataset.val_dataloader()), 
                         total=num_val_images):
        obs, gt, mean, std, fname, slice_num, max_value = batch

        obs = obs.to('cuda')
        gt = gt.to('cuda')
        
        # create reconstruction from observation
        reco, reco_std = reconstructor._reconstruct(obs,return_std=True)
        recos.append(reco)
        recos_std.append(reco_std)

        # calculate quality metrics
        psnrs.append(PSNR(reco, gt.cpu().numpy()[0][0]))
        ssims.append(SSIM(reco, gt.cpu().numpy()[0][0]))
        
        if check_inv or check_loss:
            # create torch tensor from reconstruction and observation
            reco_torch = torch.from_numpy(reco.asarray()[None, None]).to(
                    reconstructor.model.device).float()
            #obs_torch = torch.from_numpy(np.asarray(obs)[None, None]).to(
            #                reconstructor.model.device)
            
            # calculate sample and log det Jacobian of the reconstruction 
            z, log_jac = reconstructor.model(cinn_input=reco_torch, 
                                             cond_input=obs,
                                             rev=False)

        if check_loss:
            # calculate the NLL loss of the sample
            loss = criterion(zz=z, log_jac=log_jac)
            losses.append(loss.detach().cpu().numpy())
        
        if check_inv:
            # calculate back from the sample to the reconstruction to test 
            # invertibility
            reco_inv, _ = reconstructor.model(cinn_input=z, 
                                             cond_input=obs,
                                             rev=True)
            inv_psnr.append(PSNR(reco_inv.detach().cpu().numpy(), reco))

mean_psnr = np.mean(psnrs)
std_psnr = np.std(psnrs)
mean_ssim = np.mean(ssims)
std_ssim = np.std(ssims)
mean_loss = np.mean(losses) if check_loss else None
std_loss = np.std(losses) if check_loss else None
mean_inv_psnr = np.mean(inv_psnr) if check_inv else None
std_inv_psnr = np.std(inv_psnr) if check_inv else None

print('---')
print('Results:')
print('mean psnr: {:f}'.format(mean_psnr))
print('std psnr: {:f}'.format(std_psnr))
print('mean ssim: {:f}'.format(mean_ssim))
print('std ssim: {:f}'.format(std_ssim))
if check_loss:
    print('mean loss: {:f}'.format(mean_loss))
    print('std loss: {:f}'.format(std_loss))
if check_inv:
    print('mean inversion psnr: {:f}'.format(mean_inv_psnr))
    print('std inversion psnr: {:f}'.format(std_inv_psnr))

#%% plot results for the first 5 images + reconstruction
if plot_examples:
    for i, batch in tqdm(zip(range(10), dataset.val_dataloader()),
                         total=10):
        _, gt, mean, std, fname, slice_num, max_value = batch
        #print(recos[i].shape, recos_std[i].shape, gt.shape)
        _, ax = plot_images([recos[i], gt[0][0], recos_std[i]],
                            fig_size=(10, 4), vrange='individual')
        ax[0].set_xlabel('PSNR: {:.2f}, SSIM: {:.2f}'.format(psnrs[i],
                                                             ssims[i]))
        ax[0].set_title('CINNReconstructor')
        ax[1].set_title('ground truth')
        ax[2].set_title('CINNReconstructor std')
        ax[0].figure.suptitle('val sample {:d}'.format(i))
        
        if save_report:
            img_save_path = os.path.join(report_path,
                                    'val sample {:d}'.format(i)+'.png')
                
            savefig(img_save_path, dpi=None, facecolor='w', edgecolor='w',
                    orientation='portrait', format=None, transparent=False,
                    bbox_inches=None, pad_inches=0.1, metadata=None)

# plot random samples for the first 5 images
if plot_examples:
    for i, batch in tqdm(zip(range(10), dataset.val_dataloader()),
                         total=10):
        obs, gt, mean, std, fname, slice_num, max_value = batch
        obs = obs.to("cuda")
        gt = gt.numpy()[0][0]
        
        cond_input = reconstructor.model.cond_net(obs)
        z = torch.randn((3, np.prod(reconstructor.img_size)),
                                    device=reconstructor.model.device)

        cond_input_rep = [torch.repeat_interleave(c,3,dim = 0) for c in cond_input]
     
        xgen, _ = reconstructor.model.cinn(z, c=cond_input_rep, rev=True)
        xgen = xgen.detach().cpu()
        _, ax = plot_images([gt, xgen[0,0,:,:], xgen[1,0,:,:], xgen[2,0,:,:]],
                            fig_size=(10, 4), vrange='individual')
        ax[0].set_title('ground truth')
        ax[1].set_title('sample 1')
        ax[2].set_title('sample 2')
        ax[3].set_title('sample 2')

        ax[0].figure.suptitle('val sample {:d}'.format(i))
        
        if save_report:
            img_save_path = os.path.join(report_path,
                                    'val sample {:d}_samples'.format(i)+'.png')
                
            savefig(img_save_path, dpi=None, facecolor='w', edgecolor='w',
                    orientation='portrait', format=None, transparent=False,
                    bbox_inches=None, pad_inches=0.1, metadata=None)


#%% sanity check for invertibility and loss on 3 ground truth images
if check_inv_gt or check_loss_gt:
    recos_gt = []
    z_gt = []
    losses_gt = []
    inv_psnr_gt = []
    with torch.no_grad():
        for i, batch in tqdm(zip(range(3), dataset.val_dataloader()),
                             total=3):
            obs, gt, mean, std, fname, slice_num, max_value = batch
            obs = obs.to('cuda')
            gt = gt.to('cuda')

            # reconstruct with gt to check invertibility
            z, log_jac = reconstructor.model(cinn_input=gt, 
                                             cond_input=obs,
                                             rev=False)
            z_gt.append(z.detach().cpu().numpy())
            
            if check_loss_gt:
                # calculate the NLL loss of the sample
                loss_gt = criterion(zz=z, log_jac=log_jac)
                losses_gt.append(loss_gt.detach().cpu().numpy())
            
            if check_inv_gt:
                 # calculate back from the sample to the reconstruction to test 
                 # invertibility
                reco_gt, _  = reconstructor.model(cinn_input=z,
                                              cond_input=obs,
                                              rev=True)
                reco_gt[0][0]
                recos_gt.append(reco_gt.detach().cpu().numpy())
                inv_psnr_gt.append(PSNR(reco_gt.detach().cpu().numpy(),
                                        gt.detach().cpu().numpy()[0][0]))
        
    mean_loss_gt = np.mean(losses_gt) if check_loss_gt else None
    std_loss_gt = np.std(losses_gt) if check_loss_gt else None
    mean_inv_psnr_gt = np.mean(inv_psnr_gt) if check_inv_gt else None
    std_inv_psnr_gt = np.std(inv_psnr_gt) if check_inv_gt else None    
        
    print('---')
    print('Results on Ground Truth:')
    if check_loss_gt:
        print('mean loss gt: {:f}'.format(mean_loss_gt))
        print('std loss gt: {:f}'.format(std_loss_gt))
    if check_inv_gt:
        print('mean inversion psnr gt: {:f}'.format(mean_inv_psnr_gt))
        print('std inversion psnr gt: {:f}'.format(std_inv_psnr_gt))    
        
    if plot_examples_gt:
        for i, batch in tqdm(zip(range(3), dataset.val_dataloader()),
                             total=3):
            _, gt, mean, std, fname, slice_num, max_value = batch
            gt = gt.numpy()[0][0]
            
            _, ax = plot_images([recos_gt[i], gt],
                                fig_size=(10, 4), vrange='individual')
            ax[0].set_xlabel('PSNR: {:.2f}'.format(inv_psnr_gt[i]))
            ax[0].set_title('Reconstructed gt')
            ax[1].set_title('ground truth')
            ax[0].figure.suptitle('val sample {:d}'.format(i))
            
            if save_report:
                img_save_path = os.path.join(report_path,
                                    'val sample {:d}'.format(i)+'_gt.png')
                
                savefig(img_save_path, dpi=None, facecolor='w', edgecolor='w',
                        orientation='portrait', format=None, transparent=False,
                        bbox_inches=None, pad_inches=0.1, metadata=None)

#%% create report file
if save_report:
    report_dict = {'settings': {'num_val_images': num_val_images,
                                'seed': eval_seed,
                                'samples_per_reco': 
                                    reconstructor.samples_per_reco},
                   'results': {'mean_psnr': float(mean_psnr),
                               'std_psnr': float(std_psnr),
                               'mean_ssim': float(mean_ssim),
                               'std_ssim': float(std_ssim),
                               'mean_loss': float(mean_loss),
                               'std_loss': float(std_loss),
                               'mean_inv_psnr': float(mean_inv_psnr),
                               'std_inv_psnr': float(std_inv_psnr)},
                   'results_gt': {'mean_loss_gt': float(mean_loss_gt),
                                  'std_loss_gt': float(std_loss_gt),
                                  'mean_inv_psnr_gt': float(mean_inv_psnr_gt),
                                  'std_inv_psnr_gt': float(std_inv_psnr_gt)}
        }
    
    report_file_path =  os.path.join(report_path, 'report.yaml')
    with open(report_file_path, 'w') as file:
        documents = yaml.dump(report_dict, file)


