#!/bin/bash
#
## BEGIN SBATCH directives
#SBATCH --job-name=Robust_RL_1
#SBATCH --output=res_TQC_VAR10.txt
#
#SBATCH --error=error_cont1
#SBATCH --ntasks=1
#SBATCH --time=20:00:00
#SBATCH --partition=cpu_shared
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
##SBATCH --mail-type=ALL
##SBATCH --mail-user=pierre.clavier@polytechnique.edu
## END SBATCH directives

## To clean and load modules defined at the compile and link phase

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
## Execution
python multiprocessing2_continuous.py --penal_value=0.001 --n_env=8 --total_timesteps=500_000 --log_dir='/mnt/beegfs/home/CMAP/pierre.clavier/Software/results_mp/' --name_exp='TQC_HOPPER_print' --seed=20
