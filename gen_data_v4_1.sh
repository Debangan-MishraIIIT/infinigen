#!/bin/bash
#SBATCH --job-name=CSI-v4-1
#SBATCH --partition=long
#SBATCH -c 48
#SBATCH --output=/network/scratch/a/ankur.sikarwar/infinigen/slurm_logs_output/csi_v4_1_job_output-%j.txt
#SBATCH --error=/network/scratch/a/ankur.sikarwar/infinigen/slurm_logs_error/csi_v4_1_job_error-%j.txt
#SBATCH --ntasks=1
#SBATCH --gres=gpu:a100l:1
#SBATCH --constraint=80gb
#SBATCH --time=24:00:00
#SBATCH --mem=512Gb

export __GLX_VENDOR_LIBRARY_NAME=nvidia
export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json

module load anaconda/3
conda activate infinigen

python -m infinigen.datagen.manage_jobs \
    --output_folder outputs/csi_v4_1 \
    --num_scenes 400 \
    --configs fast_solve.gin singleroom.gin \
    --pipeline_overrides \
        get_cmd.driver_script=infinigen_examples.generate_indoors \
        LocalScheduleHandler.use_gpu=True \
        iterate_scene_tasks.n_camera_rigs=2 \
    --overrides \
        compose_indoors.terrain_enabled=False \
        compose_indoors.restrict_single_supported_roomtype=True \
        compose_indoors.place_2=True \
    --pipeline_configs \
        local_256GB_custom.gin \
        monocular.gin \
        opengl_gt.gin \
        indoor_background_configs.gin \
    --overwrite