#!/bin/bash
#SBATCH --job-name=Kitchen-v1001_Final_Part4
#SBATCH --partition=long
#SBATCH -c 48
#SBATCH --output=/network/scratch/a/ankur.sikarwar/infinigen/slurm_logs_output/kitchen_v1001_Final_Part4_job_output-%j.txt
#SBATCH --error=/network/scratch/a/ankur.sikarwar/infinigen/slurm_logs_error/kitchen_v1001_Final_Part4_job_error-%j.txt
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --constraint=80gb
#SBATCH --time=48:00:00
#SBATCH --mem=512Gb

export __GLX_VENDOR_LIBRARY_NAME=nvidia
export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json

module load anaconda/3
conda activate infinigen


python -m infinigen.datagen.manage_jobs \
    --output_folder outputs/Kitchen_v1001_Final_Part4 \
    --overwrite \
    --num_scenes 1000 \
    --configs singleroom.gin studio.gin \
    --pipeline_overrides \
        get_cmd.driver_script=infinigen_examples.generate_indoors \
        LocalScheduleHandler.use_gpu=True \
        iterate_scene_tasks.n_camera_rigs=2 \
    --overrides \
        compose_indoors.terrain_enabled=False \
        restrict_solving.restrict_parent_rooms=\[\"Kitchen\"\] \
        compose_indoors.place_2=True \
    --pipeline_configs \
        local_256GB_custom.gin \
        monocular.gin \
        opengl_gt.gin \
        indoor_background_configs.gin