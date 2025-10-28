#!/bin/bash
#SBATCH --job-name=LivingRoom-v1001_Final_Parttesting
#SBATCH --partition=long
#SBATCH -c 48
#SBATCH --output=/network/scratch/a/ankur.sikarwar/infinigen/slurm_logs_output/living_room_v1001_Final_Parttesting_job_output-%j.txt
#SBATCH --error=/network/scratch/a/ankur.sikarwar/infinigen/slurm_logs_error/living_room_v1001_Final_Parttesting_job_error-%j.txt
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --time=24:00:00
#SBATCH --mem=512Gb

export __GLX_VENDOR_LIBRARY_NAME=nvidia
export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json

module load anaconda/3
conda activate infinigen


python -m infinigen.datagen.manage_jobs \
    --output_folder outputs/LivingRoom_v1001_Final_Parttesting_v995_sol3 \
    --overwrite \
    --num_scenes 1000 \
    --configs singleroom.gin studio.gin \
    --pipeline_overrides \
        get_cmd.driver_script=infinigen_examples.generate_indoors \
        LocalScheduleHandler.use_gpu=True \
        iterate_scene_tasks.n_camera_rigs=2 \
    --overrides \
        compose_indoors.terrain_enabled=False \
        restrict_solving.restrict_parent_rooms=\[\"LivingRoom\"\] \
        compose_indoors.place_2=True \
        compose_indoors.solve_small_enabled=False \
        solve_objects.abort_unsatisfied=True \
    --pipeline_configs \
        local_256GB_custom.gin \
        monocular.gin \
        indoor_background_configs.gin
