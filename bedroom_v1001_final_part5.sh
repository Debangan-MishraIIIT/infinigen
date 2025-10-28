#!/bin/bash
#SBATCH --job-name=Bedroom-v1001_Final_Part5
#SBATCH --partition=long
#SBATCH -c 48
#SBATCH --output=/network/scratch/a/ankur.sikarwar/infinigen/infinigen_debang/slurm_logs_output/bedroom_v1001_Final_Part5_job_output-%j.txt
#SBATCH --error=/network/scratch/a/ankur.sikarwar/infinigen/infinigen_debang/slurm_logs_error/bedroom_v1001_Final_Part5_job_error-%j.txt
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --time=24:00:00
#SBATCH --mem=512Gb

export __GLX_VENDOR_LIBRARY_NAME=nvidia
export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json

module load anaconda/3
conda activate infinigen


python -m infinigen.datagen.manage_jobs \
    --output_folder outputs/Bedroom_v1001_Final_Part5 \
    --overwrite \
    --num_scenes 1000 \
    --configs singleroom.gin studio.gin \
    --pipeline_overrides \
        get_cmd.driver_script=infinigen_examples.generate_indoors \
        LocalScheduleHandler.use_gpu=True \
        iterate_scene_tasks.n_camera_rigs=2 \
    --overrides \
        compose_indoors.terrain_enabled=False \
        restrict_solving.restrict_parent_rooms=\[\"Bedroom\"\] \
        compose_indoors.place_2=True \
    --pipeline_configs \
        local_256GB_custom.gin \
        monocular.gin \
        opengl_gt.gin \
        indoor_background_configs.gin