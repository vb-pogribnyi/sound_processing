import os
import yaml

def run_experiment(base_path, config):
    os.makedirs(os.path.join(base_path, 'outputs'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'slices'), exist_ok=True)
    for i, _ in enumerate(config['slices']):
        os.makedirs(os.path.join(base_path, 'slices', str(i).zfill(3)), exist_ok=True)

if __name__ == '__main__':
    experiments_base = '/app/Experiments'
    for exp_f in os.scandir(experiments_base):
        if not os.path.isdir(exp_f):
            continue
        descr = os.path.join(exp_f.path, 'experiment.yml')
        if not os.path.exists(descr):
            print('--------------------------------- Experiment yml is not found!', exp_f.path)
            continue
        if os.path.exists(os.path.join(exp_f.path, 'done.flag')):
            print('Experiment done, skipping.', exp_f.path)
            continue
        with open(descr, 'r') as descr_f:
            config = yaml.load(descr_f, Loader=yaml.FullLoader)
            run_experiment(exp_f.path, config)
