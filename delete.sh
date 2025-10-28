#!/bin/bash
#SBATCH --job-name=delete
#SBATCH --partition=long-cpu
#SBATCH -c 4
#SBATCH --time=24:00:00
#SBATCH --mem=16Gb

module load anaconda/3
conda activate infinigen

python delete_coarse.py