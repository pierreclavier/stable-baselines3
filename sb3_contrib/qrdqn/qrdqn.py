from typing import Any, Dict, List, Optional, Tuple, Type, Union, Callable

import gym
import numpy as np
import torch as th
from stable_baselines3.common.buffers import ReplayBuffer
from stable_baselines3.common.off_policy_algorithm import OffPolicyAlgorithm
from stable_baselines3.common.preprocessing import maybe_transpose
from stable_baselines3.common.type_aliases import GymEnv, MaybeCallback, Schedule
from stable_baselines3.common.utils import get_linear_fn, is_vectorized_observation, polyak_update

from sb3_contrib.common.utils import quantile_huber_loss
from sb3_contrib.qrdqn.policies import QRDQNPolicy

from stable_baselines3.common import logger
from stable_baselines3.common.vec_env import VecEnv, is_vecenv_wrapped
from stable_baselines3.common.vec_env.wrappers import VecActionMasker
from gym import Env, spaces

import seaborn as sns
from matplotlib import pyplot as plt
sns.set()


print("hello_qrdqn")
class QRDQN(OffPolicyAlgorithm):
    """
    Quantile Regression Deep Q-Network (QR-DQN)
    Paper: https://arxiv.org/abs/1710.10044
    Default hyperparameters are taken from the paper and are tuned for Atari games.

    :param policy: The policy model to use (MlpPolicy, CnnPolicy, ...)
    :param env: The environment to learn from (if registered in Gym, can be str)
    :param learning_rate: The learning rate, it can be a function
        of the current progress remaining (from 1 to 0)
    :param buffer_size: size of the replay buffer
    :param learning_starts: how many steps of the model to collect transitions for before learning starts
    :param batch_size: Minibatch size for each gradient update
    :param tau: the soft update coefficient ("Polyak update", between 0 and 1) default 1 for hard update
    :param gamma: the discount factor
    :param train_freq: Update the model every ``train_freq`` steps. Alternatively pass a tuple of frequency and unit
        like ``(5, "step")`` or ``(2, "episode")``.
    :param gradient_steps: How many gradient steps to do after each rollout
        (see ``train_freq`` and ``n_episodes_rollout``)
        Set to ``-1`` means to do as many gradient steps as steps done in the environment
        during the rollout.
    :param replay_buffer_class: Replay buffer class to use (for instance ``HerReplayBuffer``).
        If ``None``, it will be automatically selected.
    :param replay_buffer_kwargs: Keyword arguments to pass to the replay buffer on creation.
    :param optimize_memory_usage: Enable a memory efficient variant of the replay buffer
        at a cost of more complexity.
        See https://github.com/DLR-RM/stable-baselines3/issues/37#issuecomment-637501195
    :param target_update_interval: update the target network every ``target_update_interval``
        environment steps.
    :param exploration_fraction: fraction of entire training period over which the exploration rate is reduced
    :param exploration_initial_eps: initial value of random action probability
    :param exploration_final_eps: final value of random action probability
    :param max_grad_norm: The maximum value for the gradient clipping (if None, no clipping)
    :param tensorboard_log: the log location for tensorboard (if None, no logging)
    :param create_eval_env: Whether to create a second environment that will be
        used for evaluating the agent periodically. (Only available when passing string for the environment)
    :param policy_kwargs: additional arguments to be passed to the policy on creation
    :param verbose: the verbosity level: 0 no output, 1 info, 2 debug
    :param seed: Seed for the pseudo random generators
    :param device: Device (cpu, cuda, ...) on which the code should be run.
        Setting it to auto, the code will be run on the GPU if possible.
    :param _init_setup_model: Whether or not to build the network at the creation of the instance
    """

    def __init__(
        self,
        policy: Union[str, Type[QRDQNPolicy]],
        env: Union[GymEnv, str],
        learning_rate: Union[float, Schedule] = 5e-5,
        buffer_size: int = 1000000,  # 1e6
        learning_starts: int = 50000,
        batch_size: Optional[int] = 32,
        tau: float = 1.0,
        gamma: Optional[float] = 0.99,
        train_freq: int = 4,
        gradient_steps: int = 1,
        replay_buffer_class: Optional[ReplayBuffer] = None,
        replay_buffer_kwargs: Optional[Dict[str, Any]] = None,
        optimize_memory_usage: bool = False,
        target_update_interval: int = 10000,
        exploration_fraction: float = 0.005,
        exploration_initial_eps: float = 1.0,
        exploration_final_eps: float = 0.01,
        max_grad_norm: Optional[float] = None,
        tensorboard_log: Optional[str] = None,
        create_eval_env: bool = False,
        policy_kwargs: Optional[Dict[str, Any]] = None,
        verbose: int = 0,
        seed: Optional[int] = None,
        device: Union[th.device, str] = "auto",
        _init_setup_model: bool = True,
        action_mask_fn: Union[str, Callable[[Env], np.ndarray]] = None,
        all_masks : Optional[Callable] =None,
        penal : Optional[Union[bool,Dict[str, Any]]] ={},  #a moodifier
    ):

        super(QRDQN, self).__init__(
            policy,
            env,
            QRDQNPolicy,
            learning_rate,
            buffer_size,
            learning_starts,
            batch_size,
            tau,
            gamma,
            train_freq,
            gradient_steps,
            action_noise=None,  # No action noise
            replay_buffer_class=replay_buffer_class,
            replay_buffer_kwargs=replay_buffer_kwargs,
            policy_kwargs=policy_kwargs,
            tensorboard_log=tensorboard_log,
            verbose=verbose,
            device=device,
            create_eval_env=create_eval_env,
            seed=seed,
            sde_support=False,
            optimize_memory_usage=optimize_memory_usage,
            supported_action_spaces=(gym.spaces.Discrete,),
            action_mask_fn=action_mask_fn,
            all_masks=all_masks,
            penal=penal,


        )

        self.exploration_initial_eps = exploration_initial_eps
        self.exploration_final_eps = exploration_final_eps
        self.exploration_fraction = exploration_fraction
        self.target_update_interval = target_update_interval
        self.max_grad_norm = max_grad_norm
        # "epsilon" for the epsilon-greedy exploration
        self.exploration_rate = 0.0
        # Linear schedule will be defined in `_setup_model()`
        self.exploration_schedule = None
        self.quantile_net, self.quantile_net_target = None, None

        if all_masks is not None:
            self.all_masks=all_masks()

        # if var_penal!= False:
        #
        #
        #     self.var_penal=var_penal

        self.penal=penal

        if self.penal !={}:
             if 'var_penal' in self.penal.keys():
                 self.var_penal=self.penal['var_penal']
             if 'entropic_penal' in self.penal.keys():
                 self.ent_penal=self.penal['ent_penal']

        self.gamma=gamma


        if "optimizer_class" not in self.policy_kwargs:
            self.policy_kwargs["optimizer_class"] = th.optim.Adam
            # Proposed in the QR-DQN paper where `batch_size = 32`
            self.policy_kwargs["optimizer_kwargs"] = dict(eps=0.01 / batch_size)

        if _init_setup_model:
            self._setup_model()

    def _setup_model(self) -> None:
        super(QRDQN, self)._setup_model()
        self._create_aliases()
        self.exploration_schedule = get_linear_fn(
            self.exploration_initial_eps, self.exploration_final_eps, self.exploration_fraction
        )

    def _create_aliases(self) -> None:
        self.quantile_net = self.policy.quantile_net
        self.quantile_net_target = self.policy.quantile_net_target
        self.n_quantiles = self.policy.n_quantiles

    def _on_step(self) -> None:
        """
        Update the exploration rate and target network if needed.
        This method is called in ``collect_rollouts()`` after each step in the environment.
        """
        if self.num_timesteps % self.target_update_interval == 0:
            polyak_update(self.quantile_net.parameters(), self.quantile_net_target.parameters(), self.tau)

        self.exploration_rate = self.exploration_schedule(self._current_progress_remaining)
        #self.logger.record("rollout/exploration rate", self.exploration_rate)
        logger.record("rollout/exploration rate", self.exploration_rate)

    def plot_graph(self):
        """
        A function to plot some graphs of densities of rewards

        """

        #print(self.all_masks.shape)
        states=th.tensor(np.arange(self.all_masks.shape[0],dtype='int'),dtype=th.int).reshape(-1,1)
        #print(state)

        next_quantiles=self.quantile_net_target(states)



        for state in states:#[0:24]: ### a modifier
            #print(state)
            print(state)

            nb_graphs=self.all_masks[state,:].sum()


            fig, axes = plt.subplots(1, np.int(nb_graphs)  , figsize=(15, 5), sharey=True)
            fig.suptitle('Distribution of returns for state {}'.format(state[0]))



            for count,action in enumerate( self.all_masks[state,:].nonzero()[0].astype(np.int)  ):
                #print(action)
                points=next_quantiles[np.int(state),:,action].detach().numpy()
                var=points.var()
                #print(var)
                #var=float(round(var,3))
                np.savetxt("Points/state_{}_action_{}_varpenal{}_gamma{}.csv".format(state,action,self.var_penal,self.gamma), points, delimiter=",")

                if nb_graphs>1:
                    sns.distplot(points, hist = True, rug = True,  kde=True,
                    color = 'darkblue',
                    kde_kws={'linewidth': 3},
                    rug_kws={'color': 'black'} ,ax=axes[count])
                    #fig.add_subplot(1,np.int(nb_graphs),count+1)
                    # sns.displot(points,kind='kde')

                    #sns.kdeplot(points,ax=axes[count])

                    axes[count].set_title("action {0}, var {1:.4f}".format(action,var))
                else :
                    # fig.add_subplot(1,np.int(nb_graphs),count+1)
                    # sns.displot(points,kind='kde')
                    #sns.kdeplot(points)
                    sns.distplot(points, hist = True,  rug = True,  kde=True,
                    color = 'darkblue',
                    kde_kws={'linewidth': 3},
                    rug_kws={'color': 'black'})

            plt.legend()
            #plt.show()

            plt.savefig("Fig/test10/state{}_action_{}_var_penal{}_gamma{}.jpeg".format(np.int(state),action,self.var_penal,self.gamma))



    def plot_graph2(self,state):
        """
        to plot densities of reward
        """

        #print(self.all_masks.shape)
        states=th.tensor(np.arange(self.all_masks.shape[0],dtype='int'),dtype=th.int).reshape(-1,1)
        #print(state)

        next_quantiles=self.quantile_net_target(states)

        nb_graphs=24
        state=states[3]

        fig, axes = plt.subplots(1, np.int(nb_graphs)  , figsize=(15, 5), sharey=True)
        fig.suptitle('Distribution of returns for state {}'.format(np.int(state)))

        for count,action in enumerate( np.arange(24,dtype='int') ):
            #print(action)
            points=next_quantiles[np.int(state),:,action].detach().numpy()
            var=points.var()


            sns.distplot(points, hist = False, kde = True, rug = True,
                color = 'darkblue',
                kde_kws={'linewidth': 3},
                rug_kws={'color': 'black'} ,ax=axes[count])

            axes[count].set_title("action {}, var {}".format(action,var))


        #print("var",distrib_1,distrib_2)

        plt.legend()
        #plt.show()
        plt.savefig(' teststate {} action {} distribution .jpeg'.format(state,action))


        ############### for Variance



    def train(self, gradient_steps: int, batch_size: int = 100) -> None:
        # Update learning rate according to schedule
        self._update_learning_rate(self.policy.optimizer)

        losses = []
        for _ in range(gradient_steps):
            # Sample replay buffer

            #a modifer pour sampler les bonnes trajectoires
            replay_data = self.replay_buffer.sample(batch_size, env=self._vec_normalize_env)


            #  for action masking for some environment
            if is_vecenv_wrapped(self.env, VecActionMasker):
                action_mask=np.array([self.all_masks[replay_data.next_observations[k]] for k in range(len(replay_data.next_observations))])
                action_mask=action_mask.reshape(action_mask.shape[0],1,action_mask.shape[1])

            # core of the algorithm
            with th.no_grad():
                # Compute the quantiles of next observation
                next_quantiles = self.quantile_net_target(replay_data.next_observations)

                #print(next_quantiles.shape)
                #print("next_quantiles",next_quantiles.shape,next_quantiles[0,:,30])
                # Compute the greedy actions which maximize the next Q values size batch*nb_quantiles*nb_action
                # if var_penal==True:
                #     next_greedy_actions= next_quantiles.mean(dim=1, keepdim=True) - self.var_reg*next_quantiles.std(dim=1, keepdim=True)

                if 'var_penal' in self.penal.keys():
                    next_greedy_actions= next_quantiles.mean(dim=1, keepdim=True) - self.var_penal*next_quantiles.std(dim=1, keepdim=True)
                    #print(next_greedy_actions)
                #
                if 'ent_penal' in self.penal.keys():  # a modifier
                #     #signe à regarder
                    next_greedy_actions= next_greedy_actions - self.ent_reg


                else :
                    next_greedy_actions = next_quantiles.mean(dim=1, keepdim=True)

                if is_vecenv_wrapped(self.env, VecActionMasker):

                    next_greedy_actions[np.logical_not(action_mask)]=-1000

                #print("next_greedy_quantiles",next_greedy_actions)
                next_greedy_actions =next_greedy_actions.argmax(dim=2, keepdim=True)


                # Make "n_quantiles" copies of actions, and reshape to (batch_size, n_quantiles, 1)
                next_greedy_actions = next_greedy_actions.expand(batch_size, self.n_quantiles, 1)
                # Follow greedy policy: use the one with the highest Q values
                next_quantiles = next_quantiles.gather(dim=2, index=next_greedy_actions).squeeze(dim=2)
                # 1-step TD target
                target_quantiles = replay_data.rewards + (1 - replay_data.dones) * self.gamma * next_quantiles # rajouter ici la penalisation?
                #print('taget', target_quantiles.shape)
            # Get current quantile estimates
            current_quantiles = self.quantile_net(replay_data.observations)

            # Make "n_quantiles" copies of actions, and reshape to (batch_size, n_quantiles, 1).
            actions = replay_data.actions[..., None].long().expand(batch_size, self.n_quantiles, 1)
            # Retrieve the quantiles for the actions from the replay buffer
            current_quantiles = th.gather(current_quantiles, dim=2, index=actions).squeeze(dim=2)

            # Compute Quantile Huber loss, summing over a quantile dimension as in the paper.
            loss = quantile_huber_loss(current_quantiles, target_quantiles, sum_over_quantiles=True)
            losses.append(loss.item())

            # Optimize the policy
            self.policy.optimizer.zero_grad()
            loss.backward()
            # Clip gradient norm
            if self.max_grad_norm is not None:
                th.nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
            self.policy.optimizer.step()

        # Increase update counter
        self._n_updates += gradient_steps

        #if self.num_timesteps==self.total_timesteps:
            #self.plot_graph()






        #self.logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        #self.logger.record("train/loss", np.mean(losses))

        logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        logger.record("train/loss", np.mean(losses))

    def predict(
        self,
        observation: np.ndarray,
        state: Optional[np.ndarray] = None,
        mask: Optional[np.ndarray] = None,
        deterministic: bool = False,
        action_masks: Optional[np.ndarray] =None,
        penal : Optional[Union[bool,Dict[str, Any]]] =False,
        gamma : float = 0.99
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Overrides the base_class predict function to include epsilon-greedy exploration.

        :param observation: the input observation
        :param state: The last states (can be None, used in recurrent policies)
        :param mask: The last masks (can be None, used in recurrent policies)
        :param deterministic: Whether or not to return deterministic actions.
        :return: the model's action and the next state
            (used in recurrent policies)
        """
        if not deterministic and np.random.rand() < self.exploration_rate:
            if is_vectorized_observation(maybe_transpose(observation, self.observation_space), self.observation_space):
                if isinstance(self.observation_space, gym.spaces.Dict):
                    n_batch = observation[list(observation.keys())[0]].shape[0]
                else:
                    n_batch = observation.shape[0]

                if is_vecenv_wrapped(self.env, VecActionMasker):

                        action_masks = np.array(self.env.valid_actions())
                        action_masks=action_masks.reshape(action_masks.shape[1],)
                        prop=np.array(self.env.valid_actions()).reshape(-1,)
                        action=np.array([np.random.choice(len(prop), 1,p= prop/prop.sum())   for _ in range(n_batch)  ]).reshape(1)
                else :
                    action = np.array([self.action_space.sample() for _ in range(n_batch)])
            else: # pas vectorisé
                if is_vecenv_wrapped(self.env, VecActionMasker):

                        action_masks = np.array(self.env.valid_actions())
                        action_masks=action_masks.reshape(action_masks.shape[1],)
                        action=np.random.choice(len(action_masks), 1,p= action_masks/action_masks.sum())
                else:
                    action = np.array(self.action_space.sample())
        else:
            #print('2', self.var_penal,var_penal)
            #print("qrdqn predict ",self.penal)
            action, state = self.policy.predict(observation, state, mask, deterministic,action_masks=action_masks,penal=self.penal,gamma=gamma)





        return action, state

    def learn(
        self,
        total_timesteps: int,
        callback: MaybeCallback = None,
        log_interval: int = 4,
        eval_env: Optional[GymEnv] = None,
        eval_freq: int = -1,
        n_eval_episodes: int = 5,
        tb_log_name: str = "QRDQN",
        eval_log_path: Optional[str] = None,
        reset_num_timesteps: bool = True,
        penal : Optional[Union[bool,Dict[str, Any]]] ={},
    ) -> OffPolicyAlgorithm:

        return super(QRDQN, self).learn(
            total_timesteps=total_timesteps,
            callback=callback,
            log_interval=log_interval,
            eval_env=eval_env,
            eval_freq=eval_freq,
            n_eval_episodes=n_eval_episodes,
            tb_log_name=tb_log_name,
            eval_log_path=eval_log_path,
            reset_num_timesteps=reset_num_timesteps,
            penal=penal
        )

    def _excluded_save_params(self) -> List[str]:
        return super(QRDQN, self)._excluded_save_params() + ["quantile_net", "quantile_net_target"]

    def _get_torch_save_params(self) -> Tuple[List[str], List[str]]:
        state_dicts = ["policy", "policy.optimizer"]

        return state_dicts, []
